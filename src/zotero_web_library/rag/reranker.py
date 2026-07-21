from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class Reranker(Protocol):
    provider_name: str
    model: str

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


@dataclass(slots=True)
class HttpCrossEncoderReranker:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 12.0
    provider_name: str = "http_cross_encoder"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        payload = json.dumps(
            {"model": self.model, "query": query, "documents": documents},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.base_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        return _response_scores(body, expected=len(documents))


def reranker_from_environment() -> Reranker | None:
    base_url = os.environ.get("WEB_LIBRARY_RERANKER_URL", "").strip()
    model = os.environ.get("WEB_LIBRARY_RERANKER_MODEL", "").strip()
    if not base_url or not model:
        return None
    try:
        timeout = max(1.0, min(float(os.environ.get("WEB_LIBRARY_RERANKER_TIMEOUT", "12") or 12), 60.0))
    except ValueError:
        timeout = 12.0
    return HttpCrossEncoderReranker(
        base_url=base_url,
        model=model,
        api_key=os.environ.get("WEB_LIBRARY_RERANKER_API_KEY", "").strip(),
        timeout=timeout,
    )


def rerank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    reranker: Reranker | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    active = reranker or reranker_from_environment()
    if active is None or not results:
        return results, {"stage": "reranker", "status": "disabled", "result_count": len(results)}, ""

    documents = [_document_text(item) for item in results]
    try:
        scores = active.rerank(str(query or ""), documents)
        if len(scores) != len(results):
            raise ValueError(f"reranker returned {len(scores)} scores for {len(results)} documents")
        reranked: list[dict[str, Any]] = []
        for item, score in zip(results, scores):
            current = dict(item)
            current_scores = dict(current.get("scores") or {})
            current_scores["reranker_score"] = float(score)
            current["scores"] = current_scores
            current["score"] = float(score)
            reranked.append(current)
        reranked.sort(
            key=lambda item: (
                float((item.get("scores") or {}).get("reranker_score") or 0.0),
                float((item.get("scores") or {}).get("rrf_score") or 0.0),
            ),
            reverse=True,
        )
        return (
            reranked,
            {
                "stage": "reranker",
                "status": "ok",
                "provider": active.provider_name,
                "model": active.model,
                "result_count": len(reranked),
            },
            "",
        )
    except Exception as exc:  # noqa: BLE001
        return (
            results,
            {
                "stage": "reranker",
                "status": "failed",
                "provider": getattr(active, "provider_name", "unknown"),
                "model": getattr(active, "model", ""),
                "result_count": len(results),
                "error": str(exc),
            },
            "reranker_failed",
        )


def _response_scores(payload: Any, *, expected: int) -> list[float]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("scores"), list):
        values = payload["scores"]
    elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
        values = payload["results"]
    else:
        raise ValueError("reranker response must contain scores or results")

    scores: list[float | None] = [None] * expected
    sequential: list[float] = []
    for position, value in enumerate(values):
        if isinstance(value, dict):
            score = value.get("relevance_score", value.get("score"))
            index = value.get("index", position)
            try:
                scores[int(index)] = float(score)
            except (TypeError, ValueError, IndexError):
                raise ValueError("invalid reranker result") from None
        else:
            sequential.append(float(value))
    if sequential:
        scores = [*sequential]
    if len(scores) != expected or any(score is None for score in scores):
        raise ValueError("reranker response does not cover every document")
    return [float(score) for score in scores if score is not None]


def _document_text(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    values = [
        source.get("title"),
        item.get("section_path") or item.get("section_title") or source.get("section_title"),
        item.get("content") or item.get("snippet") or item.get("excerpt") or source.get("excerpt"),
    ]
    return "\n".join(str(value or "").strip() for value in values if str(value or "").strip())[:5000]
