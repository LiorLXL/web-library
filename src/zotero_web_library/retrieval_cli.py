from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import app_store
from .retrieval import retrieval_source_statuses, search_retrieval
from .retrieval.models import SearchOptions
from .sources import SourceError
from .web import (
    evaluate_retrieval_candidates_with_ai,
    guided_search_coverage,
    guided_search_options,
    normalize_guided_material_types,
    normalize_guided_search_mode,
    normalize_guided_time_range,
    normalize_retrieval_expansion_level,
    normalize_retrieval_language_policy,
    normalize_retrieval_search_route,
    retrieval_provider_registry_for_library,
    guided_search_plan_for_library,
)


def csv_values(value: str | None, default: list[str] | None = None) -> list[str]:
    if value is None or not str(value).strip():
        return list(default or [])
    values: list[str] = []
    for part in str(value).split(","):
        clean = part.strip()
        if clean:
            values.append(clean)
    return values


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def require_library(library_id: str) -> dict[str, Any]:
    app_store.ensure_app_store()
    library = app_store.get_library(str(library_id or "").strip())
    if not library:
        raise SourceError("文库不存在。")
    return library


def candidate_payload_from_run_row(row: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    candidate = dict(payload or row)
    candidate["stored_candidate_id"] = str(row.get("candidate_id") or candidate.get("candidate_id") or "")
    candidate["candidate_id"] = ""
    candidate["run_id"] = run_id
    return candidate


def candidates_from_run(library_id: str, run_id: str, *, limit: int) -> list[dict[str, Any]]:
    report = app_store.retrieval_run_report(library_id, run_id)
    candidates: list[dict[str, Any]] = []
    for row in report.get("candidates") or []:
        if isinstance(row, dict):
            candidates.append(candidate_payload_from_run_row(row, run_id=run_id))
        if len(candidates) >= limit:
            break
    return candidates


def candidates_from_guided_job(library_id: str, job_id: str, *, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    job = app_store.retrieval_guided_job(library_id, job_id)
    candidates: list[dict[str, Any]] = []
    for run_id in job.get("run_ids") or []:
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            continue
        for candidate in candidates_from_run(library_id, clean_run_id, limit=max(1, limit - len(candidates))):
            candidate["guided_job_id"] = str(job.get("job_id") or "")
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    return job, candidates


def candidates_from_json_file(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        raw_candidates = payload.get("candidates") or []
        return [item for item in raw_candidates if isinstance(item, dict)]
    return []


def command_sources(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    registry = retrieval_provider_registry_for_library(args.library_id)
    return {
        "ok": True,
        "library_id": args.library_id,
        "sources": retrieval_source_statuses(registry=registry, include_health=bool(args.check)),
        "custom_sources": app_store.list_retrieval_custom_sources(args.library_id),
    }


def command_plan(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    material_types = normalize_guided_material_types(csv_values(args.material_types, ["paper", "code", "model", "dataset", "benchmark", "website"]))
    mode = normalize_guided_search_mode(args.mode)
    plan = guided_search_plan_for_library(
        args.library_id,
        topic=str(args.input or "").strip(),
        mode=mode,
        sources=csv_values(args.sources),
        material_types=material_types,
        use_ai_planning=args.route != "keyword",
        search_route=normalize_retrieval_search_route(args.route, default="natural_language"),
        input_text=str(args.input or "").strip(),
        expansion_level=normalize_retrieval_expansion_level(args.expansion_level),
        language_policy=normalize_retrieval_language_policy(args.language_policy),
    )
    return {"ok": True, "library_id": args.library_id, "plan": plan}


def command_search(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    sources = csv_values(args.sources)
    options = SearchOptions.from_payload(
        {
            "start_year": args.start_year,
            "end_year": args.end_year,
            "material_types": csv_values(args.material_types),
            "sort_mode": args.sort_mode,
            "strategy_mode": args.strategy_mode,
        }
    )
    registry = retrieval_provider_registry_for_library(args.library_id)
    result = search_retrieval(
        args.query,
        sources=sources or None,
        limit=max(1, min(int(args.limit or 10), 50)),
        options=options,
        include_raw=bool(args.include_raw),
        registry=registry,
    )
    result["ai_evaluation_summary"] = evaluate_retrieval_candidates_with_ai(
        args.library_id,
        result["query"],
        result["candidates"],
        use_ai_evaluation=False,
    )
    stored = app_store.create_retrieval_run(
        args.library_id,
        result["query"],
        result["sources"],
        result["source_stats"],
        result["candidates"],
    )
    return {
        "ok": True,
        "library_id": args.library_id,
        "run_id": stored["run_id"],
        "query": result["query"],
        "sources": result["sources"],
        "source_stats": result["source_stats"],
        "candidate_count": len(stored.get("candidates") or []),
        "candidates": stored.get("candidates") or [],
        "ai_evaluation_summary": result["ai_evaluation_summary"],
    }


def command_candidates(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    limit = max(1, min(int(args.limit or 100), 500))
    if args.guided_job_id:
        job, candidates = candidates_from_guided_job(args.library_id, args.guided_job_id, limit=limit)
        coverage = guided_search_coverage(job=job, candidates=candidates, auto_expanded=bool((job.get("coverage") or {}).get("auto_expanded")))
        return {"ok": True, "library_id": args.library_id, "job": job, "candidates": candidates, "coverage": coverage}
    if args.run_id:
        return {"ok": True, "library_id": args.library_id, "run_id": args.run_id, "candidates": candidates_from_run(args.library_id, args.run_id, limit=limit)}
    raise ValueError("请提供 --run-id 或 --guided-job-id。")


def command_ai_score(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    limit = max(1, min(int(args.limit or 100), 300))
    if args.candidates_json:
        candidates = candidates_from_json_file(args.candidates_json)[:limit]
    elif args.guided_job_id:
        _job, candidates = candidates_from_guided_job(args.library_id, args.guided_job_id, limit=limit)
    elif args.run_id:
        candidates = candidates_from_run(args.library_id, args.run_id, limit=limit)
    else:
        raise ValueError("请提供 --candidates-json、--run-id 或 --guided-job-id。")
    summary = evaluate_retrieval_candidates_with_ai(
        args.library_id,
        str(args.query or "multi-source retrieval"),
        candidates,
        use_ai_evaluation=True,
    )
    candidates.sort(
        key=lambda item: float((item.get("ai_evaluation") or {}).get("confidence") or item.get("quality_score") or 0),
        reverse=True,
    )
    return {"ok": True, "library_id": args.library_id, "summary": summary, "candidates": candidates}


def command_coverage(args: argparse.Namespace) -> dict[str, Any]:
    require_library(args.library_id)
    if args.guided_job_id:
        job, candidates = candidates_from_guided_job(args.library_id, args.guided_job_id, limit=max(1, min(int(args.limit or 300), 500)))
    else:
        mode = normalize_guided_search_mode(args.mode)
        material_types = normalize_guided_material_types(csv_values(args.material_types, ["paper", "code", "model", "dataset", "benchmark", "website"]))
        job = {
            "topic": str(args.query or ""),
            "mode": mode,
            "sources": csv_values(args.sources),
            "material_types": material_types,
            "options": guided_search_options(mode, normalize_guided_time_range({"preset": args.time_preset}, mode), material_types),
        }
        candidates = candidates_from_json_file(args.candidates_json) if args.candidates_json else []
    coverage = guided_search_coverage(job=job, candidates=candidates, auto_expanded=bool(args.auto_expanded))
    return {"ok": True, "library_id": args.library_id, "coverage": coverage, "candidate_count": len(candidates)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="多源异构检索 JSON CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources = subparsers.add_parser("sources", help="列出可用数据源")
    sources.add_argument("--library-id", required=True)
    sources.add_argument("--check", action="store_true")
    sources.set_defaults(func=command_sources)

    plan = subparsers.add_parser("plan", help="生成 V4 检索计划")
    plan.add_argument("--library-id", required=True)
    plan.add_argument("--input", required=True)
    plan.add_argument("--route", choices=["keyword", "natural_language"], default="natural_language")
    plan.add_argument("--mode", choices=["fast", "quality", "coverage"], default="quality")
    plan.add_argument("--sources", default="")
    plan.add_argument("--material-types", default="paper,code,model,dataset,benchmark,website")
    plan.add_argument("--expansion-level", default="balanced")
    plan.add_argument("--language-policy", default="source_adaptive")
    plan.set_defaults(func=command_plan)

    search = subparsers.add_parser("search", help="执行一次多源真实 API 检索并保存 run")
    search.add_argument("--library-id", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--sources", default="")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start-year", type=int)
    search.add_argument("--end-year", type=int)
    search.add_argument("--material-types", default="")
    search.add_argument("--sort-mode", default="relevance")
    search.add_argument("--strategy-mode", default="quality")
    search.add_argument("--include-raw", action="store_true")
    search.set_defaults(func=command_search)

    candidates = subparsers.add_parser("candidates", help="读取 run 或 guided job 候选")
    candidates.add_argument("--library-id", required=True)
    candidates.add_argument("--run-id", default="")
    candidates.add_argument("--guided-job-id", default="")
    candidates.add_argument("--limit", type=int, default=100)
    candidates.set_defaults(func=command_candidates)

    ai_score = subparsers.add_parser("ai-score", help="对候选进行 AI 推荐排序")
    ai_score.add_argument("--library-id", required=True)
    ai_score.add_argument("--query", required=True)
    ai_score.add_argument("--run-id", default="")
    ai_score.add_argument("--guided-job-id", default="")
    ai_score.add_argument("--candidates-json", default="")
    ai_score.add_argument("--limit", type=int, default=100)
    ai_score.set_defaults(func=command_ai_score)

    coverage = subparsers.add_parser("coverage", help="生成覆盖报告")
    coverage.add_argument("--library-id", required=True)
    coverage.add_argument("--guided-job-id", default="")
    coverage.add_argument("--candidates-json", default="")
    coverage.add_argument("--query", default="")
    coverage.add_argument("--mode", choices=["fast", "quality", "coverage"], default="quality")
    coverage.add_argument("--sources", default="")
    coverage.add_argument("--material-types", default="paper,code,model,dataset,benchmark,website")
    coverage.add_argument("--time-preset", default="10y")
    coverage.add_argument("--limit", type=int, default=300)
    coverage.add_argument("--auto-expanded", action="store_true")
    coverage.set_defaults(func=command_coverage)

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.func(args)
        emit_json(payload)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should always report JSON for agents.
        emit_json({"ok": False, "error": str(exc), "command": args.command})
        return 1


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
