from __future__ import annotations

import csv
import copy
import contextlib
import contextvars
import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from .merge import merge_candidates
from .models import RetrievedCandidate, SourceSearchResult
from zotero_web_library.metadata_import import (
    ImportedCreator,
    ImportedItem,
    normalize_ads_bibcode,
    normalize_arxiv_id,
    normalize_doi,
    normalize_isbn,
    normalize_pmcid,
    normalize_pmid,
    parse_pubmed_xml,
)


JsonFetcher = Callable[[str], Any]
TextFetcher = Callable[[str], str]
JsonPoster = Callable[[str, dict[str, str], dict[str, Any], int], Any]
HEALTH_CHECK_QUERY = "robot"
HTTP_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_HTTP_RETRY_COUNT = 1
MAX_HTTP_RETRY_COUNT = 3
DEFAULT_HTTP_RETRY_DELAY_SECONDS = 0.25
MAX_HTTP_RETRY_DELAY_SECONDS = 2.0
MAX_SOURCE_RATE_LIMIT_SECONDS = 10.0
SOURCE_RATE_LIMIT_ENV_PREFIX = "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_"
SOURCE_RATE_LIMIT_ENV_SUFFIX = "_SECONDS"
GLOBAL_SOURCE_RATE_LIMIT_ENV = "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_SECONDS"
HTTP_JSON_CONFIG_ENV = "WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG"
SQLITE_CONFIG_ENV = "WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG"
MANIFEST_CONFIG_ENV = "WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG"
AI_PIXEL_BASE_URL_ENV = "AI_PIXEL_BASE_URL"
AI_PIXEL_API_KEY_ENV = "AI_PIXEL_API_KEY"
AI_PIXEL_MODEL_ENV = "AI_PIXEL_MODEL"
AI_PIXEL_CHAT_PATH_ENV = "AI_PIXEL_CHAT_PATH"
AI_PIXEL_TIMEOUT_ENV = "AI_PIXEL_TIMEOUT_SECONDS"
AI_PIXEL_DEFAULT_BASE_URL = "https://ai-pixel.online"
AI_PIXEL_DEFAULT_CHAT_PATH = "/v1/chat/completions"
AI_PIXEL_DEFAULT_MODEL = "gpt-4o-mini"
FIELD_MAP_AI_ENABLED_ENV = "WEB_LIBRARY_RETRIEVAL_FIELD_MAP_AI"
MAX_HTTP_JSON_PAGES = 10
HTTP_JSON_ENV_REF_RE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
DEFAULT_PREPRINT_SERVER_SEARCH_DAYS = 365
MAX_PREPRINT_SERVER_SEARCH_DAYS = 3650
RETRIEVAL_SEARCH_CACHE_SECONDS_ENV = "WEB_LIBRARY_RETRIEVAL_SEARCH_CACHE_SECONDS"
RETRIEVAL_SEARCH_CACHE_MAX_ENTRIES = 128
_SOURCE_RATE_LIMIT_LOCK = threading.Lock()
_SOURCE_NEXT_ALLOWED_AT: dict[str, float] = {}
_RETRIEVAL_SEARCH_CACHE_LOCK = threading.Lock()
_RETRIEVAL_SEARCH_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_AI_PIXEL_CONFIG: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("ai_pixel_config", default={})


class RetrievalError(ValueError):
    pass


class MetadataProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        ...


def env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 100) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def retrieval_search_cache_seconds() -> int:
    return env_int(RETRIEVAL_SEARCH_CACHE_SECONDS_ENV, 90, minimum=0, maximum=600)


def http_retry_count(value: int | None = None) -> int:
    if value is not None:
        return max(0, min(int(value), MAX_HTTP_RETRY_COUNT))
    return env_int(
        "WEB_LIBRARY_RETRIEVAL_HTTP_RETRIES",
        DEFAULT_HTTP_RETRY_COUNT,
        minimum=0,
        maximum=MAX_HTTP_RETRY_COUNT,
    )


def retry_after_seconds(exc: BaseException) -> float:
    headers = getattr(exc, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    value = getter("Retry-After") if callable(getter) else None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(seconds, MAX_HTTP_RETRY_DELAY_SECONDS))


def retryable_http_error(exc: BaseException) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, "code", 0) or 0) in HTTP_RETRY_STATUS_CODES


def retryable_network_error(exc: BaseException) -> bool:
    if retryable_http_error(exc):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return False
    return isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError))


def http_retry_delay(attempt_index: int, exc: BaseException) -> float:
    retry_after = retry_after_seconds(exc)
    if retry_after:
        return retry_after
    delay = DEFAULT_HTTP_RETRY_DELAY_SECONDS * (2 ** max(0, attempt_index))
    return min(delay, MAX_HTTP_RETRY_DELAY_SECONDS)


def _http_read_bytes(
    url: str,
    *,
    timeout: int = 15,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    request_headers = {"User-Agent": "zotero-web-library/0.1 (retrieval)"}
    request_headers.update(headers or {})
    attempts = http_retry_count(retries) + 1
    for attempt_index in range(attempts):
        request = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            is_last_attempt = attempt_index >= attempts - 1
            if is_last_attempt or not retryable_network_error(exc):
                raise
            sleep(http_retry_delay(attempt_index, exc))
    raise RetrievalError("HTTP 请求失败。")


def _http_get_json(
    url: str,
    *,
    timeout: int = 15,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    return json.loads(_http_read_bytes(url, timeout=timeout, headers=headers, retries=retries, sleep=sleep).decode("utf-8"))


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int = 30) -> Any:
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_text(
    url: str,
    *,
    timeout: int = 15,
    retries: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    return _http_read_bytes(url, timeout=timeout, retries=retries, sleep=sleep).decode("utf-8", errors="replace")


def _semantic_scholar_get_json(url: str) -> Any:
    headers = {}
    api_key = os.environ.get(SemanticScholarProvider.api_key_env, "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return _http_get_json(url, headers=headers)


def _ads_get_json(url: str) -> Any:
    token = os.environ.get(ADSProvider.api_key_env, "").strip() or os.environ.get(ADSProvider.alternate_api_key_env, "").strip()
    if not token:
        raise RetrievalError(f"ADS 需要配置 {ADSProvider.api_key_env} 或 {ADSProvider.alternate_api_key_env} 后使用。")
    return _http_get_json(url, headers={"Authorization": f"Bearer {token}"})


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def truthy_config_value(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


@contextlib.contextmanager
def use_ai_pixel_config(config: dict[str, Any] | None) -> Iterator[None]:
    token = _AI_PIXEL_CONFIG.set(config or {})
    try:
        yield
    finally:
        _AI_PIXEL_CONFIG.reset(token)


def ai_pixel_config_value(*keys: str) -> str:
    config = _AI_PIXEL_CONFIG.get() or {}
    for key in keys:
        value = clean_text(config.get(key) if isinstance(config, dict) else "")
        if value:
            return value
    return ""


def ai_pixel_config_source(*keys: str, env_name: str = "") -> str:
    if ai_pixel_config_value(*keys):
        return "preference"
    if env_name and clean_text(os.environ.get(env_name)):
        return "environment"
    return "default"


def normalized_ai_pixel_chat_url(value: Any) -> str:
    text = clean_text(value)
    if not text:
        text = AI_PIXEL_DEFAULT_BASE_URL
    text = text.rstrip("/")
    if re.search(r"/chat/completions$", text):
        return text
    return f"{text}{AI_PIXEL_DEFAULT_CHAT_PATH}"


def ai_pixel_base_url() -> str:
    configured = ai_pixel_config_value("base_url", "request_url", "url")
    if configured:
        if re.search(r"/chat/completions/?$", configured):
            return re.sub(r"/v\d+/chat/completions/?$", "", configured.rstrip("/")).rstrip("/")
        return configured.rstrip("/")
    return clean_text(os.environ.get(AI_PIXEL_BASE_URL_ENV) or AI_PIXEL_DEFAULT_BASE_URL).rstrip("/")


def ai_pixel_chat_path() -> str:
    configured = ai_pixel_config_value("request_url", "url")
    if configured and re.search(r"/chat/completions/?$", configured):
        return "/" + "/".join(configured.rstrip("/").split("/")[-3:])
    path = clean_text(os.environ.get(AI_PIXEL_CHAT_PATH_ENV) or AI_PIXEL_DEFAULT_CHAT_PATH)
    return f"/{path.lstrip('/')}" if path else AI_PIXEL_DEFAULT_CHAT_PATH


def ai_pixel_chat_url() -> str:
    configured = ai_pixel_config_value("base_url", "request_url", "url")
    if configured:
        return normalized_ai_pixel_chat_url(configured)
    return f"{ai_pixel_base_url()}{ai_pixel_chat_path()}"


def ai_pixel_model() -> str:
    return ai_pixel_config_value("model", "model_name") or clean_text(os.environ.get(AI_PIXEL_MODEL_ENV) or AI_PIXEL_DEFAULT_MODEL)


def ai_pixel_api_key() -> str:
    return ai_pixel_config_value("api_key", "key") or clean_text(os.environ.get(AI_PIXEL_API_KEY_ENV))


def ai_pixel_timeout_seconds() -> int:
    return env_int(AI_PIXEL_TIMEOUT_ENV, 30, minimum=1, maximum=120)


def retrieval_model_status() -> dict[str, Any]:
    return {
        "provider": "ai-pixel",
        "base_url": ai_pixel_base_url(),
        "chat_path": ai_pixel_chat_path(),
        "chat_url": ai_pixel_chat_url(),
        "model": ai_pixel_model(),
        "configured": bool(ai_pixel_api_key()),
        "source": ai_pixel_config_source("api_key", "key", env_name=AI_PIXEL_API_KEY_ENV),
        "api_key_env": AI_PIXEL_API_KEY_ENV,
        "base_url_env": AI_PIXEL_BASE_URL_ENV,
        "model_env": AI_PIXEL_MODEL_ENV,
        "chat_path_env": AI_PIXEL_CHAT_PATH_ENV,
        "field_map_enabled_env": FIELD_MAP_AI_ENABLED_ENV,
    }


def retrieval_model_health_check(
    *,
    post_json: JsonPoster = _http_post_json,
    now: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    status = retrieval_model_status()
    health: dict[str, Any] = {
        "checked": True,
        "ok": False,
        "configured": bool(status.get("configured")),
        "provider": status.get("provider", ""),
        "base_url": status.get("base_url", ""),
        "chat_path": status.get("chat_path", ""),
        "model": status.get("model", ""),
        "elapsed_ms": 0,
        "error_kind": "",
        "error": "",
        "message": "",
    }
    started_at = now()
    if not health["configured"]:
        health.update(
            {
                "error_kind": "configuration",
                "error": f"Set {AI_PIXEL_API_KEY_ENV} to enable AI Pixel model suggestions.",
                "message": "AI Pixel model endpoint check skipped because the API key is not configured.",
            }
        )
        health["elapsed_ms"] = round(max(0.0, now() - started_at) * 1000, 1)
        return health
    try:
        response = ai_pixel_chat_completion(
            [
                {
                    "role": "system",
                    "content": "Return a minimal JSON object and no extra text.",
                },
                {"role": "user", "content": '{"ok":true}'},
            ],
            post_json=post_json,
            temperature=0.0,
            max_tokens=32,
        )
        content = chat_completion_content(response)
        health.update(
            {
                "ok": True,
                "message": "AI Pixel model endpoint responded.",
                "response_preview": clean_text(content)[:80],
            }
        )
    except Exception as exc:  # noqa: BLE001 - health checks report model/network state without breaking status.
        details = retrieval_error_details(exc)
        health.update(
            {
                "error_kind": details.get("error_kind", "unknown"),
                "error": details.get("error", clean_text(str(exc))),
                "message": "AI Pixel model endpoint check failed.",
            }
        )
    finally:
        health["elapsed_ms"] = round(max(0.0, now() - started_at) * 1000, 1)
    return health


def ai_pixel_chat_completion(
    messages: list[dict[str, str]],
    *,
    post_json: JsonPoster = _http_post_json,
    temperature: float = 0.0,
    max_tokens: int = 900,
) -> Any:
    api_key = ai_pixel_api_key()
    if not api_key:
        raise RetrievalError(f"Set {AI_PIXEL_API_KEY_ENV} to enable AI Pixel model suggestions.")
    payload = {
        "model": ai_pixel_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return post_json(
        ai_pixel_chat_url(),
        {"Authorization": f"Bearer {api_key}"},
        payload,
        ai_pixel_timeout_seconds(),
    )


def chat_completion_content(response: Any) -> str:
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    return clean_text(message.get("content"))
                return clean_text(first.get("text"))
        return clean_text(response.get("content"))
    return clean_text(response)


def json_object_from_text(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def ai_pixel_chat_json(
    messages: list[dict[str, str]],
    *,
    post_json: JsonPoster = _http_post_json,
) -> dict[str, Any]:
    response = ai_pixel_chat_completion(messages, post_json=post_json)
    if isinstance(response, dict) and "field_map" in response:
        return response
    return json_object_from_text(chat_completion_content(response))


def clean_html_text(value: Any) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", str(value or "")))


def name_parts(name: str) -> ImportedCreator:
    clean = clean_text(name)
    if not clean:
        return ImportedCreator()
    if "," in clean:
        last, first = [part.strip() for part in clean.split(",", 1)]
        return ImportedCreator(first_name=first, last_name=last)
    parts = clean.split(" ")
    if len(parts) == 1:
        return ImportedCreator(last_name=parts[0])
    return ImportedCreator(first_name=" ".join(parts[:-1]), last_name=parts[-1])


def provider_timeout_seconds(provider: MetadataProvider) -> int:
    try:
        return int(getattr(provider, "timeout_seconds", 15) or 15)
    except (TypeError, ValueError):
        return 15


def source_rate_limit_env_key(source: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", source.upper()).strip("_")
    return f"{SOURCE_RATE_LIMIT_ENV_PREFIX}{normalized}{SOURCE_RATE_LIMIT_ENV_SUFFIX}"


def source_rate_limit_seconds(source: str, provider: MetadataProvider) -> float:
    default = float(getattr(provider, "rate_limit_seconds", 0.0) or 0.0)
    global_default = env_float(
        GLOBAL_SOURCE_RATE_LIMIT_ENV,
        default,
        minimum=0.0,
        maximum=MAX_SOURCE_RATE_LIMIT_SECONDS,
    )
    return env_float(
        source_rate_limit_env_key(source),
        global_default,
        minimum=0.0,
        maximum=MAX_SOURCE_RATE_LIMIT_SECONDS,
    )


SOURCE_PREFERENCE_CONFIG_APIS = {
    "localfile": "/retrieval/local-files",
    "httpjson": "/retrieval/http-json",
    "sqlite": "/retrieval/sqlite",
    "manifest": "/retrieval/manifest",
}

SOURCE_SETUP_NOTES = {
    "crossref": ["公共接口无需鉴权；批量检索时优先调大源级限流。"],
    "arxiv": ["公共接口无需鉴权；批量任务建议保留较慢默认限流。"],
    "pubmed": ["公共 E-utilities 可直接使用；高频场景后续可扩展 NCBI API Key。"],
    "biorxiv": ["公共 API 可直接使用；关键词检索会扫描近期记录后本地过滤。"],
    "medrxiv": ["公共 API 可直接使用；关键词检索会扫描近期记录后本地过滤。"],
    "openalex": ["必须配置 OPENALEX_API_KEY，本项目避免匿名配额不稳定。"],
    "semanticscholar": ["无 Key 可用；配置 SEMANTIC_SCHOLAR_API_KEY 后限额和稳定性更好。"],
    "datacite": ["公共 API 无需鉴权，适合数据集、软件和报告 DOI。"],
    "openlibrary": ["公共 Search API 无需鉴权，适合图书和 ISBN 元数据。"],
    "ads": ["配置 ADS_API_TOKEN 或 ADS_DEV_KEY 后启用 NASA ADS。"],
    "localfile": ["可在文库级配置路径，也可设置 WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS。"],
    "httpjson": ["可在文库级保存 JSON 配置，也可设置 WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG。"],
    "sqlite": ["可在文库级保存只读数据库配置，也可设置 WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG。"],
    "manifest": ["可在文库级保存对象清单配置，也可设置 WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG。"],
}


def source_setup_guide(
    name: str,
    provider: MetadataProvider,
    *,
    config_key: str,
    requires_config: bool,
    optional_config: bool,
) -> dict[str, Any]:
    alternate_env = clean_text(getattr(provider, "alternate_api_key_env", ""))
    preference_api = SOURCE_PREFERENCE_CONFIG_APIS.get(name, "")
    if optional_config:
        config_mode = "optional_env"
    elif preference_api and requires_config:
        config_mode = "preference_or_env"
    elif alternate_env and requires_config:
        config_mode = "required_any_env"
    elif config_key and requires_config:
        config_mode = "required_env"
    else:
        config_mode = "none"
    return {
        "config_mode": config_mode,
        "config_env": config_key,
        "alternate_config_env": alternate_env,
        "preference_api": preference_api,
        "rate_limit_env": source_rate_limit_env_key(name),
        "global_rate_limit_env": GLOBAL_SOURCE_RATE_LIMIT_ENV,
        "notes": SOURCE_SETUP_NOTES.get(name, []),
    }


def reset_source_rate_limit_state() -> None:
    with _SOURCE_RATE_LIMIT_LOCK:
        _SOURCE_NEXT_ALLOWED_AT.clear()


def reset_retrieval_search_cache() -> None:
    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        _RETRIEVAL_SEARCH_CACHE.clear()


def retrieval_search_cache_key(
    query: str,
    source_names: list[str],
    limits: dict[str, int],
    include_raw: bool,
    registry: dict[str, MetadataProvider],
) -> tuple[Any, ...]:
    provider_signature = tuple(
        (
            source,
            registry[source].__class__.__module__,
            registry[source].__class__.__qualname__,
        )
        for source in source_names
        if source in registry
    )
    return (
        query.casefold(),
        tuple(source_names),
        tuple((source, limits.get(source, 0)) for source in source_names),
        bool(include_raw),
        provider_signature,
    )


def get_retrieval_search_cache(key: tuple[Any, ...], now: float | None = None) -> dict[str, Any] | None:
    timestamp = time.monotonic() if now is None else now
    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        item = _RETRIEVAL_SEARCH_CACHE.get(key)
        if not item:
            return None
        expires_at, payload = item
        if expires_at <= timestamp:
            _RETRIEVAL_SEARCH_CACHE.pop(key, None)
            return None
        cached = copy.deepcopy(payload)
    for stats in (cached.get("source_stats") or {}).values():
        if isinstance(stats, dict):
            stats["cached"] = True
    cached["cached"] = True
    return cached


def set_retrieval_search_cache(key: tuple[Any, ...], payload: dict[str, Any], now: float | None = None) -> None:
    ttl = retrieval_search_cache_seconds()
    if ttl <= 0:
        return
    timestamp = time.monotonic() if now is None else now
    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        if len(_RETRIEVAL_SEARCH_CACHE) >= RETRIEVAL_SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(_RETRIEVAL_SEARCH_CACHE, key=lambda cache_key: _RETRIEVAL_SEARCH_CACHE[cache_key][0])
            _RETRIEVAL_SEARCH_CACHE.pop(oldest_key, None)
        _RETRIEVAL_SEARCH_CACHE[key] = (timestamp + ttl, copy.deepcopy(payload))


def wait_for_source_rate_limit(
    source: str,
    provider: MetadataProvider,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> float:
    interval = source_rate_limit_seconds(source, provider)
    if interval <= 0:
        return 0.0
    with _SOURCE_RATE_LIMIT_LOCK:
        current = now()
        next_allowed_at = _SOURCE_NEXT_ALLOWED_AT.get(source, 0.0)
        wait_seconds = max(0.0, next_allowed_at - current)
        _SOURCE_NEXT_ALLOWED_AT[source] = max(current, next_allowed_at) + interval
    if wait_seconds:
        sleep(wait_seconds)
    return wait_seconds


def retrieval_error_details(exc: BaseException) -> dict[str, str]:
    message = clean_text(str(exc) or exc.__class__.__name__)
    lowered = message.lower()
    if isinstance(exc, RetrievalError) and "需要配置" in message:
        return {
            "error_kind": "configuration",
            "error": message,
            "action": "补齐对应环境变量后重试；未配置源不会影响其他源检索。",
        }
    if isinstance(exc, urllib.error.HTTPError):
        status = int(getattr(exc, "code", 0) or 0)
        if status == 429:
            return {
                "error_kind": "rate_limited",
                "error": f"HTTP 429 限流：{message}",
                "action": "稍后重试，或配置该源 API Key / 降低批量检索频率。",
            }
        if status in {401, 403}:
            return {
                "error_kind": "auth",
                "error": f"HTTP {status} 权限失败：{message}",
                "action": "检查 API Key、访问权限或当前网络出口。",
            }
        if status >= 500:
            return {
                "error_kind": "upstream",
                "error": f"HTTP {status} 上游服务异常：{message}",
                "action": "保留本次检索记录，稍后重试该数据源。",
            }
        return {
            "error_kind": "http",
            "error": f"HTTP {status}：{message}",
            "action": "检查查询词、数据源状态或网络连通性。",
        }
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in lowered or "timeout" in lowered:
        return {
            "error_kind": "timeout",
            "error": message,
            "action": "该源响应超时；可稍后重试，或先用其他源完成候选导入。",
        }
    if isinstance(exc, urllib.error.URLError):
        return {
            "error_kind": "network",
            "error": message,
            "action": "检查网络、代理或该数据源是否临时不可达。",
        }
    if "解析失败" in message or "parse" in lowered or "xml" in lowered or "json" in lowered:
        return {
            "error_kind": "parse",
            "error": message,
            "action": "该源返回格式异常；保留原始错误，稍后重试或调整 provider 解析。",
        }
    if isinstance(exc, RetrievalError):
        return {
            "error_kind": "source_error",
            "error": message,
            "action": "该源本次检索失败，其他源结果仍可继续导入。",
        }
    return {
        "error_kind": "provider_error",
        "error": message,
        "action": "该源本次检索失败，其他源结果仍可继续导入。",
    }


def run_provider_search(
    source: str,
    provider: MetadataProvider,
    query: str,
    limit: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> SourceSearchResult:
    started = time.perf_counter()
    rate_limit_seconds = source_rate_limit_seconds(source, provider)
    wait_seconds = 0.0
    try:
        wait_seconds = wait_for_source_rate_limit(source, provider, sleep=sleep, now=now)
        candidates = provider.search(query, limit)
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        return SourceSearchResult(
            source=source,
            ok=True,
            candidates=candidates,
            elapsed_ms=elapsed_ms,
            rate_limit_wait_ms=int(round(wait_seconds * 1000)),
            rate_limit_seconds=rate_limit_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - per-source failures are part of the retrieval contract
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        details = retrieval_error_details(exc)
        return SourceSearchResult(
            source=source,
            ok=False,
            elapsed_ms=elapsed_ms,
            rate_limit_wait_ms=int(round(wait_seconds * 1000)),
            rate_limit_seconds=rate_limit_seconds,
            **details,
        )


class CrossrefProvider:
    name = "crossref"
    timeout_seconds = 15
    rate_limit_seconds = 0.25
    rate_limit_note = "Crossref 公共接口可直接使用；批量检索时建议控制频率。"

    def __init__(self, get_json: JsonFetcher = _http_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        params = urllib.parse.urlencode({"query.bibliographic": clean_query, "rows": rows})
        data = self.get_json(f"https://api.crossref.org/works?{params}")
        items = (data.get("message") or {}).get("items") or []
        return [crossref_candidate(item) for item in items if isinstance(item, dict)]


def crossref_candidate(message: dict[str, Any]) -> RetrievedCandidate:
    fields = {
        "title": clean_text(" ".join(message.get("title") or [])),
        "DOI": normalize_doi(message.get("DOI") or ""),
        "publicationTitle": clean_text(" ".join(message.get("container-title") or [])),
        "abstractNote": clean_html_text(message.get("abstract") or ""),
        "url": clean_text(message.get("URL") or ""),
        "publisher": clean_text(message.get("publisher") or ""),
    }
    date_parts = (message.get("published-print") or message.get("published-online") or message.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0]:
        fields["date"] = "-".join(str(part) for part in date_parts[0])
    for source_key, target_key in {"volume": "volume", "issue": "issue", "page": "pages"}.items():
        if message.get(source_key):
            fields[target_key] = clean_text(message[source_key])
    creators = [
        ImportedCreator(first_name=author.get("given", ""), last_name=author.get("family", ""), creator_type="author")
        for author in message.get("author") or []
        if isinstance(author, dict)
    ]
    crossref_type = message.get("type")
    item_type = "journalArticle"
    if crossref_type == "proceedings-article":
        item_type = "conferencePaper"
    elif crossref_type == "book":
        item_type = "book"
    identifiers = {"doi": fields["DOI"]} if fields.get("DOI") else {}
    evidence = ["Crossref metadata"]
    if identifiers:
        evidence.append("DOI")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        identifiers=identifiers,
        source="Crossref",
    )
    return RetrievedCandidate(
        source="crossref",
        external_id=fields.get("DOI") or clean_text(message.get("URL") or ""),
        item=item,
        raw=message,
        confidence=0.9 if identifiers else 0.65,
        evidence=evidence,
        landing_url=fields.get("url", ""),
    )


class ArxivProvider:
    name = "arxiv"
    timeout_seconds = 15
    rate_limit_seconds = 3.0
    rate_limit_note = "arXiv API 适合低频交互式检索；批量任务需要降低请求频率。"

    def __init__(self, get_text: TextFetcher = _http_get_text) -> None:
        self.get_text = get_text

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        search_query = f"all:{clean_query}"
        params = urllib.parse.urlencode({"search_query": search_query, "start": 0, "max_results": rows})
        return parse_arxiv_candidates(self.get_text(f"https://export.arxiv.org/api/query?{params}"))


def parse_arxiv_candidates(text: str) -> list[RetrievedCandidate]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RetrievalError(f"arXiv XML 解析失败：{exc}") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    candidates: list[RetrievedCandidate] = []
    for entry in root.findall("atom:entry", ns):
        arxiv_url = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = normalize_arxiv_id(arxiv_url)
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        summary = clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        published = entry.findtext("atom:published", default="", namespaces=ns) or ""
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ns) if node.attrib.get("term")]
        fields = {
            "title": title,
            "abstractNote": summary,
            "date": published[:10],
            "repository": "arXiv",
            "url": arxiv_url,
            "extra": f"arXiv: {arxiv_id}" if arxiv_id else "",
        }
        creators = [name_parts(author.findtext("atom:name", default="", namespaces=ns) or "") for author in entry.findall("atom:author", ns)]
        item = ImportedItem(
            item_type="preprint",
            fields={key: value for key, value in fields.items() if value},
            creators=[creator for creator in creators if creator.last_name],
            tags=categories,
            identifiers={"arxiv": arxiv_id} if arxiv_id else {},
            source="arXiv",
        )
        candidates.append(
            RetrievedCandidate(
                source="arxiv",
                external_id=arxiv_id or arxiv_url,
                item=item,
                raw={"id": arxiv_url, "categories": categories},
                confidence=0.88 if arxiv_id else 0.6,
                evidence=["arXiv metadata", "arXiv ID"] if arxiv_id else ["arXiv metadata"],
                landing_url=arxiv_url,
                pdf_url=pdf_url,
            )
        )
    return candidates


class PubMedProvider:
    name = "pubmed"
    timeout_seconds = 15
    rate_limit_seconds = 0.34
    rate_limit_note = "PubMed E-utilities 公共接口可用；高频批量任务建议后续接入 NCBI API Key。"

    def __init__(self, get_json: JsonFetcher = _http_get_json, get_text: TextFetcher = _http_get_text) -> None:
        self.get_json = get_json
        self.get_text = get_text

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        params = urllib.parse.urlencode({"db": "pubmed", "term": clean_query, "retmode": "json", "retmax": rows})
        data = self.get_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}")
        ids = ((data.get("esearchresult") or {}).get("idlist") or [])[:rows]
        ids = [str(value).strip() for value in ids if str(value).strip()]
        if not ids:
            return []
        fetch_params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
        try:
            items = parse_pubmed_xml(self.get_text(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}"))
        except Exception as exc:  # noqa: BLE001 - normalize parser errors as retrieval errors
            raise RetrievalError(str(exc)) from exc
        return [pubmed_candidate(item) for item in items]


def pubmed_candidate(item: ImportedItem) -> RetrievedCandidate:
    pmid = item.identifiers.get("pmid", "")
    landing_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else item.fields.get("url", "")
    fields = dict(item.fields)
    if landing_url and not fields.get("url"):
        fields["url"] = landing_url
    normalized_item = ImportedItem(
        item_type=item.item_type,
        fields=fields,
        creators=item.creators,
        tags=item.tags,
        identifiers=item.identifiers,
        source="PubMed",
    )
    evidence = ["PubMed metadata"]
    if pmid:
        evidence.append("PMID")
    if item.identifiers.get("doi"):
        evidence.append("DOI")
    return RetrievedCandidate(
        source="pubmed",
        external_id=pmid,
        item=normalized_item,
        raw={"pmid": pmid},
        confidence=0.87 if pmid else 0.62,
        evidence=evidence,
        landing_url=landing_url,
    )


class PreprintServerProvider:
    server = ""
    label = ""
    name = ""
    timeout_seconds = 15
    rate_limit_seconds = 1.0

    def __init__(self, get_json: JsonFetcher = _http_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        doi = normalize_doi(clean_query)
        if doi:
            data = self.get_json(f"https://api.biorxiv.org/details/{self.server}/{urllib.parse.quote(doi, safe='')}/na/json")
            records = data.get("collection") or []
            return [preprint_server_candidate(self.name, self.label, record) for record in records if isinstance(record, dict)][:rows]
        days = preprint_server_search_days()
        data = self.get_json(f"https://api.biorxiv.org/details/{self.server}/{days}d/0/json")
        records = data.get("collection") or []
        candidates = [
            preprint_server_candidate(self.name, self.label, record)
            for record in records
            if isinstance(record, dict) and preprint_record_matches_query(record, clean_query)
        ]
        return candidates[:rows]


class BioRxivProvider(PreprintServerProvider):
    name = "biorxiv"
    server = "biorxiv"
    label = "bioRxiv"
    rate_limit_note = "bioRxiv 公共 API 可无鉴权读取预印本详情；非 DOI 检索会扫描最近预印本并在本地过滤关键词。"


class MedRxivProvider(PreprintServerProvider):
    name = "medrxiv"
    server = "medrxiv"
    label = "medRxiv"
    rate_limit_note = "medRxiv 公共 API 可无鉴权读取预印本详情；非 DOI 检索会扫描最近预印本并在本地过滤关键词。"


def preprint_server_search_days() -> int:
    return env_int(
        "WEB_LIBRARY_RETRIEVAL_PREPRINT_DAYS",
        DEFAULT_PREPRINT_SERVER_SEARCH_DAYS,
        minimum=1,
        maximum=MAX_PREPRINT_SERVER_SEARCH_DAYS,
    )


def preprint_record_matches_query(record: dict[str, Any], query: str) -> bool:
    tokens = [token.casefold() for token in re.findall(r"[\w.-]+", query) if token.strip()]
    if not tokens:
        return False
    haystack = clean_text(
        " ".join(
            local_value_to_text(record.get(key))
            for key in ["title", "authors", "abstract", "category", "doi", "server", "type"]
        )
    ).casefold()
    return all(token in haystack for token in tokens)


def preprint_server_candidate(source: str, label: str, record: dict[str, Any]) -> RetrievedCandidate:
    doi = normalize_doi(record.get("doi") or "")
    title = clean_text(record.get("title") or "")
    category = clean_text(record.get("category") or "")
    version = clean_text(record.get("version") or "")
    published = clean_text(record.get("published") or "")
    fields = {
        "title": title,
        "date": clean_text(record.get("date") or ""),
        "DOI": doi,
        "abstractNote": clean_text(record.get("abstract") or ""),
        "repository": label,
        "url": f"https://doi.org/{doi}" if doi else "",
        "extra": "\n".join(
            value
            for value in [
                f"{label} DOI: {doi}" if doi else "",
                f"{label} Version: {version}" if version else "",
                f"Published DOI: {published}" if published else "",
                f"Preprint Category: {category}" if category else "",
            ]
            if value
        ),
    }
    creators = preprint_creators(record.get("authors"))
    tags = [category] if category else []
    identifiers = {"doi": doi} if doi else {}
    evidence = [f"{label} metadata"]
    if doi:
        evidence.append("DOI")
    if version:
        evidence.append(f"Version {version}")
    item = ImportedItem(
        item_type="preprint",
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source=label,
    )
    return RetrievedCandidate(
        source=source,
        external_id=doi or title,
        item=item,
        raw={"doi": doi, "version": version, "category": category, "published": published},
        confidence=0.86 if doi else 0.64,
        evidence=evidence,
        landing_url=fields.get("url", ""),
    )


def preprint_creators(value: Any) -> list[ImportedCreator]:
    text = clean_text(value)
    if not text:
        return []
    separator = ";" if ";" in text else "|"
    names = [clean_text(part) for part in text.split(separator) if clean_text(part)]
    return [creator for creator in (name_parts(name) for name in names) if creator.last_name]


class OpenAlexProvider:
    name = "openalex"
    api_key_env = "OPENALEX_API_KEY"
    timeout_seconds = 15
    rate_limit_seconds = 0.2
    rate_limit_note = "本项目当前要求配置 OpenAlex API Key 后启用，避免匿名限额不稳定。"

    def __init__(self, get_json: JsonFetcher = _http_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        select = ",".join(
            [
                "id",
                "doi",
                "ids",
                "title",
                "display_name",
                "publication_year",
                "publication_date",
                "type",
                "authorships",
                "primary_location",
                "best_oa_location",
                "biblio",
                "abstract_inverted_index",
            ]
        )
        params = {"search": clean_query, "per_page": rows, "select": select}
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise RetrievalError(f"OpenAlex 需要配置 {self.api_key_env} 后使用。")
        params["api_key"] = api_key
        data = self.get_json(f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}")
        rows_payload = data.get("results") or []
        return [openalex_candidate(work) for work in rows_payload if isinstance(work, dict)]


def openalex_candidate(work: dict[str, Any]) -> RetrievedCandidate:
    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    doi = normalize_doi(work.get("doi") or ids.get("doi") or "")
    pmid = normalize_pmid(ids.get("pmid") or "")
    pmcid = normalize_pmcid(ids.get("pmcid") or "")
    identifiers = {key: value for key, value in {"doi": doi, "pmid": pmid, "pmcid": pmcid}.items() if value}
    primary_location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    best_oa_location = work.get("best_oa_location") if isinstance(work.get("best_oa_location"), dict) else {}
    source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
    landing_url = clean_text(primary_location.get("landing_page_url") or best_oa_location.get("landing_page_url") or ids.get("openalex") or work.get("id") or "")
    pdf_url = clean_text(primary_location.get("pdf_url") or best_oa_location.get("pdf_url") or "")
    biblio = work.get("biblio") if isinstance(work.get("biblio"), dict) else {}
    first_page = clean_text(biblio.get("first_page") or "")
    last_page = clean_text(biblio.get("last_page") or "")
    pages = "-".join([first_page, last_page]) if first_page and last_page else first_page or last_page
    work_type = clean_text(work.get("type") or "")
    item_type = openalex_item_type(work_type)
    venue = clean_text(source.get("display_name") or "")
    fields = {
        "title": clean_text(work.get("title") or work.get("display_name") or ""),
        "date": clean_text(work.get("publication_date") or work.get("publication_year") or ""),
        "DOI": doi,
        "abstractNote": abstract_from_openalex_index(work.get("abstract_inverted_index")),
        "url": landing_url,
        "volume": clean_text(biblio.get("volume") or ""),
        "issue": clean_text(biblio.get("issue") or ""),
        "pages": pages,
    }
    if venue:
        if item_type == "conferencePaper":
            fields["proceedingsTitle"] = venue
        elif item_type == "preprint":
            fields["repository"] = venue
        else:
            fields["publicationTitle"] = venue
    creators = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") if isinstance(authorship.get("author"), dict) else {}
        creator = name_parts(str(author.get("display_name") or ""))
        if creator.last_name:
            creators.append(creator)
    evidence = ["OpenAlex work"]
    if doi:
        evidence.append("DOI")
    if pmid:
        evidence.append("PMID")
    if pmcid:
        evidence.append("PMCID")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        identifiers=identifiers,
        source="OpenAlex",
    )
    return RetrievedCandidate(
        source="openalex",
        external_id=clean_text(work.get("id") or ids.get("openalex") or doi or pmid or pmcid),
        item=item,
        raw={"id": work.get("id"), "type": work_type, "ids": ids},
        confidence=0.86 if identifiers else 0.7,
        evidence=evidence,
        landing_url=landing_url,
        pdf_url=pdf_url,
    )


def abstract_from_openalex_index(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positions: dict[int, str] = {}
    for term, indexes in value.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            try:
                positions[int(index)] = str(term)
            except (TypeError, ValueError):
                continue
    if not positions:
        return ""
    return clean_text(" ".join(positions[index] for index in sorted(positions)))


def openalex_item_type(value: str) -> str:
    normalized = clean_text(value).lower()
    if normalized in {"book", "monograph"}:
        return "book"
    if normalized in {"book-chapter", "book chapter"}:
        return "bookSection"
    if normalized in {"proceedings-article", "proceedings article"}:
        return "conferencePaper"
    if normalized in {"preprint", "posted-content"}:
        return "preprint"
    if normalized in {"dissertation", "thesis"}:
        return "thesis"
    if normalized == "dataset":
        return "dataset"
    if normalized == "report":
        return "report"
    return "journalArticle"


class SemanticScholarProvider:
    name = "semanticscholar"
    api_key_env = "SEMANTIC_SCHOLAR_API_KEY"
    optional_api_key = True
    timeout_seconds = 15
    rate_limit_seconds = 1.0
    rate_limit_note = "Semantic Scholar 无 Key 可用；配置 API Key 后限额和稳定性更好。"

    def __init__(self, get_json: JsonFetcher = _semantic_scholar_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        fields = ",".join(
            [
                "paperId",
                "corpusId",
                "title",
                "abstract",
                "venue",
                "year",
                "publicationDate",
                "publicationTypes",
                "authors",
                "externalIds",
                "url",
                "openAccessPdf",
                "journal",
            ]
        )
        params = urllib.parse.urlencode({"query": clean_query, "limit": rows, "fields": fields})
        data = self.get_json(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}")
        papers = data.get("data") or []
        return [semantic_scholar_candidate(paper) for paper in papers if isinstance(paper, dict)]


def semantic_scholar_candidate(paper: dict[str, Any]) -> RetrievedCandidate:
    external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
    doi = normalize_doi(external_ids.get("DOI") or "")
    arxiv_id = normalize_arxiv_id(external_ids.get("ArXiv") or "")
    pmid = normalize_pmid(external_ids.get("PubMed") or "")
    pmcid = normalize_pmcid(external_ids.get("PubMedCentral") or "")
    identifiers = {
        key: value
        for key, value in {"doi": doi, "arxiv": arxiv_id, "pmid": pmid, "pmcid": pmcid}.items()
        if value
    }
    open_access_pdf = paper.get("openAccessPdf") if isinstance(paper.get("openAccessPdf"), dict) else {}
    journal = paper.get("journal") if isinstance(paper.get("journal"), dict) else {}
    publication_types = [clean_text(value) for value in paper.get("publicationTypes") or [] if clean_text(value)]
    item_type = semantic_scholar_item_type(publication_types)
    venue = clean_text(journal.get("name") or paper.get("venue") or "")
    paper_id = clean_text(paper.get("paperId") or "")
    corpus_id = clean_text(paper.get("corpusId") or "")
    extra = "\n".join(
        [
            value
            for value in [
                f"Semantic Scholar Paper ID: {paper_id}" if paper_id else "",
                f"Semantic Scholar Corpus ID: {corpus_id}" if corpus_id else "",
                f"arXiv: {arxiv_id}" if arxiv_id else "",
                f"PMID: {pmid}" if pmid else "",
                f"PMCID: {pmcid}" if pmcid else "",
            ]
            if value
        ]
    )
    fields = {
        "title": clean_text(paper.get("title") or ""),
        "date": clean_text(paper.get("publicationDate") or paper.get("year") or ""),
        "DOI": doi,
        "abstractNote": clean_text(paper.get("abstract") or ""),
        "url": clean_text(paper.get("url") or ""),
        "volume": clean_text(journal.get("volume") or ""),
        "pages": clean_text(journal.get("pages") or ""),
        "extra": extra,
    }
    if venue:
        if item_type == "conferencePaper":
            fields["proceedingsTitle"] = venue
        elif item_type == "preprint":
            fields["repository"] = venue
        else:
            fields["publicationTitle"] = venue
    creators = []
    for author in paper.get("authors") or []:
        if not isinstance(author, dict):
            continue
        creator = name_parts(str(author.get("name") or ""))
        if creator.last_name:
            creators.append(creator)
    evidence = ["Semantic Scholar paper"]
    if doi:
        evidence.append("DOI")
    if arxiv_id:
        evidence.append("arXiv ID")
    if pmid:
        evidence.append("PMID")
    if pmcid:
        evidence.append("PMCID")
    if paper.get("corpusId"):
        evidence.append("Semantic Scholar Corpus ID")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        identifiers=identifiers,
        source="Semantic Scholar",
    )
    return RetrievedCandidate(
        source="semanticscholar",
        external_id=semantic_scholar_external_id(paper, identifiers),
        item=item,
        raw={"paperId": paper_id, "corpusId": paper.get("corpusId"), "externalIds": external_ids},
        confidence=0.86 if identifiers else 0.68,
        evidence=evidence,
        landing_url=fields.get("url", ""),
        pdf_url=clean_text(open_access_pdf.get("url") or ""),
    )


def semantic_scholar_external_id(paper: dict[str, Any], identifiers: dict[str, str]) -> str:
    return (
        clean_text(paper.get("paperId") or "")
        or identifiers.get("doi", "")
        or identifiers.get("arxiv", "")
        or identifiers.get("pmid", "")
        or identifiers.get("pmcid", "")
        or clean_text(paper.get("url") or "")
    )


def semantic_scholar_item_type(publication_types: list[str]) -> str:
    normalized = {value.strip().lower().replace(" ", "").replace("-", "") for value in publication_types}
    if normalized & {"booksection", "bookchapter"}:
        return "bookSection"
    if normalized & {"book", "monograph"}:
        return "book"
    if normalized & {"conference", "proceedings", "proceedingsarticle"}:
        return "conferencePaper"
    if normalized & {"preprint", "postedcontent"}:
        return "preprint"
    if normalized & {"dataset"}:
        return "dataset"
    return "journalArticle"


class DataCiteProvider:
    name = "datacite"
    timeout_seconds = 15
    rate_limit_seconds = 0.25
    rate_limit_note = "DataCite 公共 API 可无鉴权检索 DOI 元数据；适合补充数据集、软件和报告资源。"

    def __init__(self, get_json: JsonFetcher = _http_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        params = urllib.parse.urlencode({"query": clean_query, "page[size]": rows, "sort": "relevance"})
        data = self.get_json(f"https://api.datacite.org/dois?{params}")
        records = data.get("data") or []
        return [datacite_candidate(record) for record in records if isinstance(record, dict)]


def datacite_candidate(record: dict[str, Any]) -> RetrievedCandidate:
    attrs = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
    doi = normalize_doi(attrs.get("doi") or record.get("id") or "")
    types = attrs.get("types") if isinstance(attrs.get("types"), dict) else {}
    resource_type_general = clean_text(types.get("resourceTypeGeneral") or "")
    resource_type = clean_text(types.get("resourceType") or "")
    item_type = datacite_item_type(resource_type_general, resource_type)
    title = datacite_first_title(attrs.get("titles"))
    abstract = datacite_description(attrs.get("descriptions"))
    publisher = clean_text(attrs.get("publisher") or "")
    year = clean_text(attrs.get("publicationYear") or "")
    landing_url = clean_text(attrs.get("url") or (f"https://doi.org/{doi}" if doi else ""))
    version = clean_text(attrs.get("version") or "")
    tags = datacite_subjects(attrs.get("subjects"))
    extra = datacite_extra(record, attrs, resource_type_general, resource_type, version)
    fields = {
        "title": title,
        "date": year,
        "DOI": doi,
        "url": landing_url,
        "abstractNote": abstract,
        "publisher": publisher,
        "extra": extra,
    }
    creators = datacite_creators(attrs.get("creators"))
    identifiers = {"doi": doi} if doi else {}
    evidence = ["DataCite DOI metadata"]
    if doi:
        evidence.append("DOI")
    if resource_type_general:
        evidence.append(f"Resource type: {resource_type_general}")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source="DataCite",
    )
    return RetrievedCandidate(
        source="datacite",
        external_id=doi or clean_text(record.get("id") or landing_url),
        item=item,
        raw={"id": record.get("id"), "types": types},
        confidence=0.86 if doi else 0.66,
        evidence=evidence,
        landing_url=landing_url,
    )


def datacite_first_title(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    for title in value:
        if isinstance(title, dict) and clean_text(title.get("title") or ""):
            return clean_text(title.get("title") or "")
    return ""


def datacite_description(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    preferred = []
    fallback = []
    for description in value:
        if not isinstance(description, dict):
            continue
        text = clean_html_text(description.get("description") or "")
        if not text:
            continue
        description_type = clean_text(description.get("descriptionType") or "").lower()
        if description_type == "abstract":
            preferred.append(text)
        else:
            fallback.append(text)
    return (preferred or fallback or [""])[0]


def datacite_creators(value: Any) -> list[ImportedCreator]:
    if not isinstance(value, list):
        return []
    creators: list[ImportedCreator] = []
    for creator in value:
        if not isinstance(creator, dict):
            continue
        family = clean_text(creator.get("familyName") or "")
        given = clean_text(creator.get("givenName") or "")
        name = clean_text(creator.get("name") or "")
        if family or given:
            creators.append(ImportedCreator(first_name=given, last_name=family or name))
            continue
        if name:
            creators.append(name_parts(name))
    return [creator for creator in creators if creator.last_name]


def datacite_subjects(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for subject in value:
        if isinstance(subject, dict):
            text = clean_text(subject.get("subject") or "")
        else:
            text = clean_text(subject)
        if text and text not in tags:
            tags.append(text)
    return tags[:12]


def datacite_extra(
    record: dict[str, Any],
    attrs: dict[str, Any],
    resource_type_general: str,
    resource_type: str,
    version: str,
) -> str:
    values = [
        f"DataCite ID: {clean_text(record.get('id') or '')}",
        f"DataCite Resource Type: {resource_type_general}" if resource_type_general else "",
        f"DataCite Resource Type Detail: {resource_type}" if resource_type else "",
        f"Version: {version}" if version else "",
    ]
    rights = attrs.get("rightsList") if isinstance(attrs.get("rightsList"), list) else []
    for right in rights[:2]:
        if isinstance(right, dict):
            label = clean_text(right.get("rights") or right.get("rightsUri") or "")
            if label:
                values.append(f"Rights: {label}")
    return "\n".join(value for value in values if value and not value.endswith(": "))


def datacite_item_type(resource_type_general: str, resource_type: str = "") -> str:
    normalized = clean_text(resource_type_general).lower().replace(" ", "").replace("-", "")
    detail = clean_text(resource_type).lower()
    if normalized == "software" or "software" in detail:
        return "computerProgram"
    if normalized in {"dataset", "collection", "model", "workflow"}:
        return "dataset"
    if normalized == "datapaper":
        return "journalArticle"
    if normalized == "text":
        if "report" in detail:
            return "report"
        if "thesis" in detail or "dissertation" in detail:
            return "thesis"
        if "book chapter" in detail:
            return "bookSection"
        if "book" in detail:
            return "book"
        return "document"
    if normalized in {"image", "audiovisual", "sound", "physicalobject", "interactive resource", "interactiveresource"}:
        return "document"
    return "document"


class GitHubProvider:
    name = "github"
    api_key_env = "GITHUB_TOKEN"
    optional_api_key = True
    timeout_seconds = 8
    rate_limit_seconds = 1.0
    rate_limit_note = "GitHub public repository search works without a token; configure a token to improve rate limits."

    def __init__(self, api_key: str = "", get_json: JsonFetcher | None = None) -> None:
        self.api_key = clean_text(api_key)
        self.get_json = get_json

    def token(self) -> str:
        return self.api_key or clean_text(os.environ.get(self.api_key_env))

    def is_configured(self) -> bool:
        return bool(self.token())

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("Search query cannot be empty.")
        rows = max(1, min(int(limit or 10), 30))
        params = urllib.parse.urlencode({"q": clean_query, "per_page": rows, "sort": "stars", "order": "desc"})
        data = self.fetch_json(f"https://api.github.com/search/repositories?{params}")
        items = data.get("items") if isinstance(data, dict) else []
        return [github_candidate(item) for item in items or [] if isinstance(item, dict)]

    def fetch_json(self, url: str) -> Any:
        if self.get_json:
            return self.get_json(url)
        headers = {"Accept": "application/vnd.github+json"}
        token = self.token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return _http_get_json(url, timeout=provider_timeout_seconds(self), headers=headers)


def github_candidate(repo: dict[str, Any]) -> RetrievedCandidate:
    full_name = clean_text(repo.get("full_name") or repo.get("name") or "")
    description = clean_text(repo.get("description") or "")
    language = clean_text(repo.get("language") or "")
    license_value = github_license_name(repo.get("license"))
    landing_url = clean_text(repo.get("html_url") or "")
    updated_at = clean_text(repo.get("updated_at") or "")[:10]
    stars = clean_text(repo.get("stargazers_count") or "")
    forks = clean_text(repo.get("forks_count") or "")
    topics = github_topics(repo.get("topics"))
    extra = "\n".join(
        value
        for value in [
            f"GitHub Repository: {full_name}" if full_name else "",
            f"Language: {language}" if language else "",
            f"Stars: {stars}" if stars else "",
            f"Forks: {forks}" if forks else "",
            f"License: {license_value}" if license_value else "",
            f"Updated: {updated_at}" if updated_at else "",
        ]
        if value
    )
    fields = {
        "title": full_name,
        "abstractNote": description,
        "url": landing_url,
        "repository": "GitHub",
        "programmingLanguage": language,
        "version": clean_text(repo.get("default_branch") or ""),
        "date": updated_at,
        "extra": extra,
    }
    evidence = ["GitHub repository metadata"]
    if stars:
        evidence.append(f"Stars: {stars}")
    if license_value:
        evidence.append(f"License: {license_value}")
    item = ImportedItem(
        item_type="computerProgram",
        fields={key: value for key, value in fields.items() if value},
        creators=[],
        tags=topics,
        identifiers={},
        source="GitHub",
    )
    return RetrievedCandidate(
        source="github",
        external_id=clean_text(repo.get("id") or full_name or landing_url),
        item=item,
        raw={
            "id": repo.get("id"),
            "full_name": full_name,
            "language": language,
            "stars": repo.get("stargazers_count"),
            "license": license_value,
        },
        confidence=0.72 if description else 0.62,
        evidence=evidence,
        landing_url=landing_url,
    )


def github_license_name(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("spdx_id") or value.get("name") or "")
    return clean_text(value)


def github_topics(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_text(item) for item in value[:12] if clean_text(item)]


class HuggingFaceProvider:
    name = "huggingface"
    api_key_env = "HUGGINGFACE_TOKEN"
    optional_api_key = True
    timeout_seconds = 8
    rate_limit_seconds = 0.5
    rate_limit_note = "HuggingFace Hub public search works without a token; configure a token for private or higher-rate access."

    def __init__(self, api_key: str = "", get_json: JsonFetcher | None = None) -> None:
        self.api_key = clean_text(api_key)
        self.get_json = get_json

    def token(self) -> str:
        return self.api_key or clean_text(os.environ.get(self.api_key_env))

    def is_configured(self) -> bool:
        return bool(self.token())

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("Search query cannot be empty.")
        rows = max(1, min(int(limit or 10), 50))
        per_kind = max(1, min(rows, max(2, rows // 2)))
        params = urllib.parse.urlencode({"search": clean_query, "limit": per_kind, "full": "false"})
        model_records = self.fetch_json(f"https://huggingface.co/api/models?{params}")
        dataset_records = self.fetch_json(f"https://huggingface.co/api/datasets?{params}")
        candidates: list[RetrievedCandidate] = []
        if isinstance(model_records, list):
            candidates.extend(huggingface_candidate(record, kind="model") for record in model_records if isinstance(record, dict))
        if isinstance(dataset_records, list):
            candidates.extend(huggingface_candidate(record, kind="dataset") for record in dataset_records if isinstance(record, dict))
        return candidates[:rows]

    def fetch_json(self, url: str) -> Any:
        if self.get_json:
            return self.get_json(url)
        headers = {}
        token = self.token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return _http_get_json(url, timeout=provider_timeout_seconds(self), headers=headers)


def huggingface_candidate(record: dict[str, Any], *, kind: str) -> RetrievedCandidate:
    repo_id = clean_text(record.get("id") or record.get("modelId") or record.get("datasetId") or "")
    tags = huggingface_tags(record.get("tags"))
    downloads = clean_text(record.get("downloads") or "")
    likes = clean_text(record.get("likes") or "")
    pipeline_tag = clean_text(record.get("pipeline_tag") or record.get("pipelineTag") or "")
    last_modified = clean_text(record.get("lastModified") or record.get("last_modified") or "")[:10]
    private = bool(record.get("private"))
    url_path = "datasets" if kind == "dataset" else ""
    landing_url = f"https://huggingface.co/{url_path + '/' if url_path else ''}{repo_id}" if repo_id else ""
    extra = "\n".join(
        value
        for value in [
            f"HuggingFace Type: {kind}",
            f"Repo ID: {repo_id}" if repo_id else "",
            f"Pipeline: {pipeline_tag}" if pipeline_tag else "",
            f"Downloads: {downloads}" if downloads else "",
            f"Likes: {likes}" if likes else "",
            f"Private: {private}" if private else "",
            f"Last Modified: {last_modified}" if last_modified else "",
            f"Tags: {'; '.join(tags[:8])}" if tags else "",
        ]
        if value
    )
    abstract = " ; ".join(value for value in [pipeline_tag, "; ".join(tags[:6])] if value)
    fields = {
        "title": repo_id,
        "abstractNote": abstract,
        "url": landing_url,
        "repository": "HuggingFace Hub",
        "date": last_modified,
        "extra": extra,
    }
    evidence = [f"HuggingFace Hub {kind} metadata"]
    if downloads:
        evidence.append(f"Downloads: {downloads}")
    if likes:
        evidence.append(f"Likes: {likes}")
    item = ImportedItem(
        item_type="dataset" if kind == "dataset" else "computerProgram",
        fields={key: value for key, value in fields.items() if value},
        creators=[],
        tags=tags,
        identifiers={},
        source="HuggingFace",
    )
    return RetrievedCandidate(
        source="huggingface",
        external_id=f"{kind}:{repo_id}" if repo_id else clean_text(record.get("_id") or ""),
        item=item,
        raw={
            "id": repo_id,
            "kind": kind,
            "downloads": record.get("downloads"),
            "likes": record.get("likes"),
            "tags": tags,
        },
        confidence=0.72 if repo_id else 0.58,
        evidence=evidence,
        landing_url=landing_url,
    )


def huggingface_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_text(item) for item in value[:16] if clean_text(item)]


class ZenodoProvider:
    name = "zenodo"
    api_key_env = "ZENODO_ACCESS_TOKEN"
    optional_api_key = True
    timeout_seconds = 8
    rate_limit_seconds = 0.5
    rate_limit_note = "Zenodo public records search works without a token; configure a token for higher-rate access."

    def __init__(self, api_key: str = "", get_json: JsonFetcher | None = None) -> None:
        self.api_key = clean_text(api_key)
        self.get_json = get_json

    def token(self) -> str:
        return self.api_key or clean_text(os.environ.get(self.api_key_env))

    def is_configured(self) -> bool:
        return bool(self.token())

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("Search query cannot be empty.")
        rows = max(1, min(int(limit or 10), 50))
        params = {"q": clean_query, "size": rows}
        token = self.token()
        if token:
            params["access_token"] = token
        data = self.fetch_json(f"https://zenodo.org/api/records?{urllib.parse.urlencode(params)}")
        records = data.get("hits", {}).get("hits") if isinstance(data, dict) else []
        return [zenodo_candidate(record) for record in records or [] if isinstance(record, dict)]

    def fetch_json(self, url: str) -> Any:
        if self.get_json:
            return self.get_json(url)
        return _http_get_json(url, timeout=provider_timeout_seconds(self))


def zenodo_candidate(record: dict[str, Any]) -> RetrievedCandidate:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    doi = normalize_doi(metadata.get("doi") or record.get("doi") or "")
    title = clean_text(metadata.get("title") or "")
    description = clean_html_text(metadata.get("description") or "")
    publication_date = clean_text(metadata.get("publication_date") or "")
    upload_type = clean_text(metadata.get("upload_type") or "")
    resource_type = zenodo_resource_type(metadata)
    item_type = zenodo_item_type(upload_type, resource_type)
    landing_url = zenodo_landing_url(record, doi)
    creators = zenodo_creators(metadata.get("creators"))
    tags = zenodo_keywords(metadata.get("keywords"))
    extra = "\n".join(
        value
        for value in [
            f"Zenodo Record ID: {clean_text(record.get('id') or '')}" if clean_text(record.get("id") or "") else "",
            f"Zenodo Concept DOI: {normalize_doi(record.get('conceptdoi') or '')}" if normalize_doi(record.get("conceptdoi") or "") else "",
            f"Upload Type: {upload_type}" if upload_type else "",
            f"Resource Type: {resource_type}" if resource_type else "",
            f"Version: {clean_text(metadata.get('version') or '')}" if clean_text(metadata.get("version") or "") else "",
            f"License: {zenodo_license(metadata.get('license'))}" if zenodo_license(metadata.get("license")) else "",
        ]
        if value
    )
    fields = {
        "title": title,
        "date": publication_date,
        "DOI": doi,
        "url": landing_url,
        "abstractNote": description,
        "publisher": "Zenodo",
        "extra": extra,
    }
    identifiers = {"doi": doi} if doi else {}
    evidence = ["Zenodo record metadata"]
    if doi:
        evidence.append("DOI")
    if upload_type:
        evidence.append(f"Upload type: {upload_type}")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source="Zenodo",
    )
    return RetrievedCandidate(
        source="zenodo",
        external_id=doi or clean_text(record.get("id") or landing_url),
        item=item,
        raw={
            "id": record.get("id"),
            "doi": doi,
            "upload_type": upload_type,
            "resource_type": resource_type,
        },
        confidence=0.86 if doi else 0.68,
        evidence=evidence,
        landing_url=landing_url,
    )


def zenodo_resource_type(metadata: dict[str, Any]) -> str:
    resource_type = metadata.get("resource_type")
    if isinstance(resource_type, dict):
        return clean_text(resource_type.get("type") or resource_type.get("title") or "")
    return clean_text(resource_type)


def zenodo_item_type(upload_type: str, resource_type: str) -> str:
    normalized = f"{upload_type} {resource_type}".lower()
    if "software" in normalized:
        return "computerProgram"
    if "dataset" in normalized:
        return "dataset"
    if "poster" in normalized or "presentation" in normalized:
        return "presentation"
    if "report" in normalized:
        return "report"
    if "thesis" in normalized:
        return "thesis"
    if "book" in normalized:
        return "book"
    return "document"


def zenodo_landing_url(record: dict[str, Any], doi: str) -> str:
    links = record.get("links") if isinstance(record.get("links"), dict) else {}
    return clean_text(links.get("html") or links.get("latest_html") or (f"https://doi.org/{doi}" if doi else ""))


def zenodo_creators(value: Any) -> list[ImportedCreator]:
    if not isinstance(value, list):
        return []
    creators: list[ImportedCreator] = []
    for creator in value[:20]:
        if not isinstance(creator, dict):
            continue
        name = clean_text(creator.get("name") or "")
        if name:
            creators.append(name_parts(name))
    return [creator for creator in creators if creator.last_name]


def zenodo_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_text(item) for item in value[:12] if clean_text(item)]


def zenodo_license(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("id") or value.get("title") or "")
    return clean_text(value)


class OpenLibraryProvider:
    name = "openlibrary"
    timeout_seconds = 15
    rate_limit_seconds = 0.5
    rate_limit_note = "OpenLibrary 公共 Search API 可无鉴权检索图书/ISBN 元数据；适合补充书籍条目。"

    def __init__(self, get_json: JsonFetcher = _http_get_json) -> None:
        self.get_json = get_json

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        fields = ",".join(
            [
                "key",
                "title",
                "author_name",
                "first_publish_year",
                "isbn",
                "publisher",
                "subject",
                "language",
                "edition_key",
                "cover_edition_key",
                "ebook_access",
            ]
        )
        params = urllib.parse.urlencode({"q": clean_query, "limit": rows, "fields": fields})
        data = self.get_json(f"https://openlibrary.org/search.json?{params}")
        docs = data.get("docs") or []
        return [openlibrary_candidate(doc) for doc in docs if isinstance(doc, dict)]


def openlibrary_candidate(doc: dict[str, Any]) -> RetrievedCandidate:
    key = clean_text(doc.get("key") or "")
    title = clean_text(doc.get("title") or "")
    year = clean_text(doc.get("first_publish_year") or "")
    isbn = openlibrary_primary_isbn(doc.get("isbn"))
    publishers = openlibrary_list(doc.get("publisher"), limit=2)
    subjects = openlibrary_list(doc.get("subject"), limit=12)
    languages = openlibrary_list(doc.get("language"), limit=4)
    edition_keys = openlibrary_list(doc.get("edition_key"), limit=3)
    cover_edition_key = clean_text(doc.get("cover_edition_key") or "")
    ebook_access = clean_text(doc.get("ebook_access") or "")
    landing_url = f"https://openlibrary.org{key}" if key.startswith("/") else ""
    extra = "\n".join(
        value
        for value in [
            f"OpenLibrary Key: {key}" if key else "",
            f"OpenLibrary Edition Keys: {'; '.join(edition_keys)}" if edition_keys else "",
            f"OpenLibrary Cover Edition: {cover_edition_key}" if cover_edition_key else "",
            f"Languages: {'; '.join(languages)}" if languages else "",
            f"Ebook Access: {ebook_access}" if ebook_access else "",
        ]
        if value
    )
    fields = {
        "title": title,
        "date": year,
        "ISBN": isbn,
        "publisher": "; ".join(publishers),
        "url": landing_url,
        "extra": extra,
    }
    creators = [creator for creator in (name_parts(name) for name in openlibrary_list(doc.get("author_name"), limit=12)) if creator.last_name]
    identifiers = {"isbn": isbn} if isbn else {}
    evidence = ["OpenLibrary book metadata"]
    if isbn:
        evidence.append("ISBN")
    if key:
        evidence.append("OpenLibrary work key")
    item = ImportedItem(
        item_type="book",
        fields={field: value for field, value in fields.items() if value},
        creators=creators,
        tags=subjects,
        identifiers=identifiers,
        source="OpenLibrary",
    )
    return RetrievedCandidate(
        source="openlibrary",
        external_id=isbn or key or title,
        item=item,
        raw={
            "key": key,
            "edition_key": edition_keys,
            "cover_edition_key": cover_edition_key,
            "ebook_access": ebook_access,
        },
        confidence=0.84 if isbn else 0.62,
        evidence=evidence,
        landing_url=landing_url,
    )


def openlibrary_primary_isbn(value: Any) -> str:
    values = [normalize_isbn(item) for item in openlibrary_list(value, limit=50)]
    preferred_13 = [item for item in values if len(item) == 13]
    return (preferred_13 or values or [""])[0]


def openlibrary_list(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, list):
        values = [clean_text(item) for item in value if clean_text(item)]
    else:
        values = [clean_text(value)] if clean_text(value) else []
    unique: list[str] = []
    for item in values:
        if item and item not in unique:
            unique.append(item)
    return unique[: max(1, limit)]


class ADSProvider:
    name = "ads"
    api_key_env = "ADS_API_TOKEN"
    alternate_api_key_env = "ADS_DEV_KEY"
    timeout_seconds = 15
    rate_limit_seconds = 1.0
    rate_limit_note = "NASA ADS API 需要 token；通过 ADS_API_TOKEN 或 ADS_DEV_KEY 配置后启用，适合天文/物理 Bibcode 元数据。"

    def __init__(self, get_json: JsonFetcher = _ads_get_json) -> None:
        self.get_json = get_json

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip() or os.environ.get(self.alternate_api_key_env, "").strip())

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        fields = ",".join(
            [
                "bibcode",
                "title",
                "author",
                "year",
                "pubdate",
                "pub",
                "doi",
                "identifier",
                "abstract",
                "keyword",
                "volume",
                "issue",
                "page",
                "doctype",
            ]
        )
        params = urllib.parse.urlencode({"q": clean_query, "rows": rows, "fl": fields, "sort": "score desc"})
        data = self.get_json(f"https://api.adsabs.harvard.edu/v1/search/query?{params}")
        docs = ((data.get("response") or {}).get("docs") or []) if isinstance(data, dict) else []
        return [ads_candidate(doc) for doc in docs if isinstance(doc, dict)]


def ads_candidate(doc: dict[str, Any]) -> RetrievedCandidate:
    bibcode = normalize_ads_bibcode(doc.get("bibcode") or "")
    doi = ads_primary_doi(doc)
    title = ads_first_value(doc.get("title"))
    pubdate = clean_text(doc.get("pubdate") or "")
    year = clean_text(doc.get("year") or "")
    venue = clean_text(doc.get("pub") or "")
    pages = ads_pages(doc.get("page"))
    doctype = clean_text(doc.get("doctype") or "")
    item_type = ads_item_type(doctype)
    fields = {
        "title": title,
        "date": pubdate or year,
        "DOI": doi,
        "publicationTitle": venue,
        "abstractNote": clean_text(doc.get("abstract") or ""),
        "volume": clean_text(doc.get("volume") or ""),
        "issue": clean_text(doc.get("issue") or ""),
        "pages": pages,
        "url": f"https://ui.adsabs.harvard.edu/abs/{urllib.parse.quote(bibcode, safe='')}/abstract" if bibcode else "",
        "extra": f"ADS Bibcode: {bibcode}" if bibcode else "",
    }
    creators = [creator for creator in (name_parts(name) for name in ads_list(doc.get("author"), limit=20)) if creator.last_name]
    tags = ads_list(doc.get("keyword"), limit=12)
    identifiers = {key: value for key, value in {"ads_bibcode": bibcode, "doi": doi}.items() if value}
    evidence = ["ADS metadata"]
    if bibcode:
        evidence.append("ADS Bibcode")
    if doi:
        evidence.append("DOI")
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source="NASA ADS",
    )
    return RetrievedCandidate(
        source="ads",
        external_id=bibcode or doi or title,
        item=item,
        raw={"bibcode": bibcode, "doctype": doctype, "identifier": ads_list(doc.get("identifier"), limit=20)},
        confidence=0.9 if bibcode else 0.7 if doi else 0.6,
        evidence=evidence,
        landing_url=fields.get("url", ""),
    )


def ads_item_type(doctype: str) -> str:
    normalized = clean_text(doctype).casefold()
    if normalized in {"book"}:
        return "book"
    if normalized in {"inbook", "inproceedings"}:
        return "bookSection"
    if normalized in {"proceedings", "conference"}:
        return "conferencePaper"
    if normalized in {"eprint", "preprint"}:
        return "preprint"
    if normalized in {"thesis", "phdthesis", "mastersthesis"}:
        return "thesis"
    return "journalArticle"


def ads_primary_doi(doc: dict[str, Any]) -> str:
    for value in [*ads_list(doc.get("doi"), limit=20), *ads_list(doc.get("identifier"), limit=50)]:
        doi = normalize_doi(value)
        if doi:
            return doi
    return ""


def ads_first_value(value: Any) -> str:
    values = ads_list(value, limit=1)
    return values[0] if values else clean_text(value)


def ads_list(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, list):
        values = [clean_text(item) for item in value if clean_text(item)]
    else:
        values = [clean_text(value)] if clean_text(value) else []
    unique: list[str] = []
    for item in values:
        if item and item not in unique:
            unique.append(item)
    return unique[: max(1, limit)]


def ads_pages(value: Any) -> str:
    pages = ads_list(value, limit=2)
    if len(pages) >= 2:
        return f"{pages[0]}-{pages[1]}"
    return pages[0] if pages else ""


class LocalFileProvider:
    name = "localfile"
    api_key_env = "WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS"
    timeout_seconds = 5
    rate_limit_seconds = 0.0
    rate_limit_note = "读取本地 CSV / JSONL 文件，无外部限流；通过 WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS 配置一个或多个路径。"

    def __init__(self, paths: list[str | Path] | None = None, field_map: dict[str, Any] | None = None) -> None:
        self.paths = paths
        self.field_map = field_map or {}

    def is_configured(self) -> bool:
        if self.paths is not None:
            return bool(self.paths)
        return bool(os.environ.get(self.api_key_env, "").strip())

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        paths = configured_local_file_paths(self.paths)
        candidates: list[RetrievedCandidate] = []
        for path in paths:
            for row_number, row in iter_local_file_rows(path):
                mapped_row = local_file_mapped_row(row, self.field_map)
                if local_row_matches_query(mapped_row, clean_query):
                    candidates.append(local_file_candidate(row, path, row_number, clean_query, field_map=self.field_map))
                    if len(candidates) >= rows:
                        return candidates
        return candidates


class HttpJsonProvider:
    name = "httpjson"
    api_key_env = HTTP_JSON_CONFIG_ENV
    timeout_seconds = 15
    rate_limit_seconds = 0.5
    rate_limit_note = (
        "读取内部或团队 HTTP JSON 检索接口；通过文库偏好或 "
        "WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG 配置 url_template、items_path 和 field_map。"
    )

    def __init__(self, config: dict[str, Any] | str | None = None, get_json: JsonFetcher | None = None) -> None:
        self.config = config
        self.get_json = get_json

    def is_configured(self) -> bool:
        return not self.configuration_error()

    def configuration_error(self) -> str:
        try:
            config = http_json_config(self.config)
            if not config.get("url_template"):
                return f"需要配置 {HTTP_JSON_CONFIG_ENV}"
            http_json_headers(config)
        except RetrievalError as exc:
            return str(exc)
        return ""

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        config = http_json_config(self.config)
        template = clean_text(config.get("url_template"))
        if not template:
            raise RetrievalError(f"HTTP JSON 需要配置 {HTTP_JSON_CONFIG_ENV} 或文库偏好后使用。")
        candidates: list[RetrievedCandidate] = []
        next_url = ""
        result_index = 0
        max_pages = http_json_max_pages(config)
        page_start = http_json_page_start(config)
        can_page_by_template = http_json_template_supports_pagination(template)
        for page_index in range(max_pages):
            url = next_url or http_json_search_url(
                template,
                clean_query,
                rows,
                page=page_start + page_index,
                offset=page_index * rows,
            )
            if self.get_json is None:
                data = _http_get_json(
                    url,
                    timeout=provider_timeout_seconds(self),
                    headers=http_json_headers(config),
                )
            else:
                data = self.get_json(url)
            items = http_json_result_items(data, config)
            if not items:
                break
            for item in items:
                result_index += 1
                candidate = http_json_candidate(item, config, result_index, clean_query)
                if candidate is not None:
                    candidates.append(candidate)
                if len(candidates) >= rows:
                    break
            if len(candidates) >= rows:
                break
            next_url = http_json_next_url(data, config, base_url=url)
            if next_url:
                continue
            if not can_page_by_template:
                break
        return candidates


class SQLiteProvider:
    name = "sqlite"
    api_key_env = SQLITE_CONFIG_ENV
    timeout_seconds = 5
    rate_limit_seconds = 0.0
    rate_limit_note = "读取本地 SQLite 只读数据库；通过文库偏好或 WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG 配置 path、query 和 field_map。"

    def __init__(self, config: dict[str, Any] | str | None = None) -> None:
        self.config = config

    def is_configured(self) -> bool:
        return not self.configuration_error()

    def configuration_error(self) -> str:
        try:
            config = sqlite_config(self.config)
            if not config.get("path") or not config.get("query"):
                return f"需要配置 {SQLITE_CONFIG_ENV}"
            sqlite_config_path(config)
            sqlite_query(config)
        except RetrievalError as exc:
            return str(exc)
        return ""

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        config = sqlite_config(self.config)
        path = sqlite_config_path(config)
        sql = sqlite_query(config)
        candidates: list[RetrievedCandidate] = []
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=provider_timeout_seconds(self)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, sqlite_query_params(clean_query, rows))
            for index, row in enumerate(cursor.fetchmany(rows), start=1):
                candidate = sqlite_candidate(dict(row), config, index, clean_query)
                if candidate is not None:
                    candidates.append(candidate)
                if len(candidates) >= rows:
                    break
        return candidates


class ManifestProvider:
    name = "manifest"
    api_key_env = MANIFEST_CONFIG_ENV
    timeout_seconds = 10
    rate_limit_seconds = 0.5
    rate_limit_note = "Object Manifest 读取本地或远程对象清单 JSON；通过文库偏好或 WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG 配置 manifest_path/manifest_url、items_path 和 field_map。"

    def __init__(self, config: dict[str, Any] | str | None = None, get_json: JsonFetcher | None = None) -> None:
        self.config = config
        self.get_json = get_json

    def is_configured(self) -> bool:
        return not self.configuration_error()

    def configuration_error(self) -> str:
        try:
            config = manifest_config(self.config)
            if not (config.get("manifest_path") or config.get("manifest_url")):
                return f"需要配置 {MANIFEST_CONFIG_ENV}"
            manifest_source(config)
            http_json_headers(config)
        except RetrievalError as exc:
            return str(exc)
        return ""

    def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
        clean_query = clean_text(query)
        if not clean_query:
            raise RetrievalError("检索词不能为空。")
        rows = max(1, min(int(limit or 10), 50))
        config = manifest_config(self.config)
        items = manifest_items(config, get_json=self.get_json)
        candidates: list[RetrievedCandidate] = []
        for index, item in enumerate(items, start=1):
            if not local_row_matches_query(manifest_mapped_row(item, config), clean_query):
                continue
            candidate = manifest_candidate(item, config, index, clean_query)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) >= rows:
                break
        return candidates


def configured_local_file_paths(values: list[str | Path] | None = None) -> list[Path]:
    raw_values: list[str | Path]
    if values is not None:
        raw_values = values
    else:
        raw_values = split_local_path_config(os.environ.get(LocalFileProvider.api_key_env, ""))
    if not raw_values:
        raise RetrievalError(f"Local CSV/JSONL 需要配置 {LocalFileProvider.api_key_env} 后使用。")
    paths: list[Path] = []
    for value in raw_values:
        path = Path(value).expanduser()
        if not path.exists():
            raise RetrievalError(f"Local CSV/JSONL 需要配置有效路径：{path}")
        if path.is_dir():
            for suffix in ("*.csv", "*.jsonl", "*.ndjson"):
                paths.extend(sorted(child for child in path.glob(suffix) if child.is_file()))
            continue
        if path.suffix.lower() not in {".csv", ".jsonl", ".ndjson"}:
            raise RetrievalError(f"Local CSV/JSONL 不支持该文件类型：{path.name}")
        paths.append(path)
    if not paths:
        raise RetrievalError(f"Local CSV/JSONL 需要配置包含 CSV 或 JSONL 文件的路径。")
    return paths


def split_local_path_config(value: str) -> list[str]:
    paths: list[str] = []
    for line in str(value or "").replace("\r", "\n").splitlines():
        parts = line.split(os.pathsep)
        paths.extend(part.strip() for part in parts if part.strip())
    return paths


LOCAL_COLUMN_TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("item.fields.title", "title", ("title", "name", "display_name", "paper_title", "article_title")),
    ("item.fields.date", "date", ("date", "year", "publication_year", "publicationYear", "issued")),
    ("item.fields.abstractNote", "abstract", ("abstractNote", "abstract", "summary", "description")),
    ("item.fields.publicationTitle", "venue", ("publicationTitle", "journal", "container_title", "venue", "conference", "source_title")),
    ("item.fields.DOI", "doi", ("DOI", "doi")),
    ("item.fields.url", "url", ("url", "URL", "landing_url", "link")),
    ("item.fields.publisher", "publisher", ("publisher", "repository", "institution")),
    ("item.fields.volume", "volume", ("volume",)),
    ("item.fields.issue", "issue", ("issue", "number")),
    ("item.fields.pages", "pages", ("pages", "page")),
    ("item.item_type", "item type", ("item_type", "itemType", "type", "zotero_type", "resource_type", "genre")),
    ("item.creators", "creators", ("authors", "author", "creators", "creator", "contributors", "familyName", "givenName", "last_name", "first_name")),
    ("item.tags", "tags", ("tags", "keywords", "subjects", "subject")),
    ("item.identifiers.arxiv", "arXiv", ("arxiv", "arxiv_id", "arXiv")),
    ("item.identifiers.pmid", "PMID", ("pmid", "PMID")),
    ("item.identifiers.pmcid", "PMCID", ("pmcid", "PMCID")),
    ("item.identifiers.ads_bibcode", "ADS Bibcode", ("ads_bibcode", "bibcode")),
    ("item.identifiers.isbn", "ISBN", ("isbn", "ISBN")),
    ("item.external_id", "source id", ("local_id", "source_id", "external_id", "id", "key", "uuid")),
    ("candidate.pdf_url", "PDF URL", ("pdf_url", "pdf", "full_text_url", "attachment_url")),
)
LOCAL_FIELD_MAP_TARGETS: dict[str, tuple[str, str]] = {
    "title": ("item.fields.title", "title"),
    "date": ("item.fields.date", "date"),
    "abstract": ("item.fields.abstractNote", "abstract"),
    "venue": ("item.fields.publicationTitle", "venue"),
    "doi": ("item.fields.DOI", "doi"),
    "url": ("item.fields.url", "url"),
    "publisher": ("item.fields.publisher", "publisher"),
    "volume": ("item.fields.volume", "volume"),
    "issue": ("item.fields.issue", "issue"),
    "pages": ("item.fields.pages", "pages"),
    "item_type": ("item.item_type", "item type"),
    "authors": ("item.creators", "creators"),
    "creators": ("item.creators", "creators"),
    "tags": ("item.tags", "tags"),
    "arxiv": ("item.identifiers.arxiv", "arXiv"),
    "pmid": ("item.identifiers.pmid", "PMID"),
    "pmcid": ("item.identifiers.pmcid", "PMCID"),
    "ads_bibcode": ("item.identifiers.ads_bibcode", "ADS Bibcode"),
    "isbn": ("item.identifiers.isbn", "ISBN"),
    "external_id": ("item.external_id", "source id"),
    "pdf_url": ("candidate.pdf_url", "PDF URL"),
}

LOCAL_MAPPING_QUALITY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "field": "title",
        "label": "Title",
        "weight": 0.35,
        "severity": "error",
        "missing_message": "缺少标题；导入后难以人工识别，也会削弱候选排序。",
    },
    {
        "field": "identifier",
        "label": "Strong identifier",
        "weight": 0.3,
        "severity": "warning",
        "missing_message": "缺少 DOI/arXiv/PMID/PMCID/ADS Bibcode/ISBN；入库去重会变弱。",
    },
    {
        "field": "date",
        "label": "Date",
        "weight": 0.15,
        "severity": "warning",
        "missing_message": "缺少年份或日期；弱相似判断和筛选会变弱。",
    },
    {
        "field": "creators",
        "label": "Creators",
        "weight": 0.2,
        "severity": "warning",
        "missing_message": "缺少作者或创建者；人工核对和弱相似判断会变弱。",
    },
)


def normalize_local_column_key(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "_")


def local_field_map_column_target(column: str, field_map: dict[str, Any] | None = None) -> tuple[str, str] | None:
    if not field_map:
        return None
    normalized = normalize_local_column_key(column)
    for target, raw_paths in field_map.items():
        target_info = LOCAL_FIELD_MAP_TARGETS.get(str(target))
        if not target_info:
            continue
        for path in flatten_field_map_values(raw_paths):
            if normalize_local_column_key(path) == normalized or normalize_local_column_key(str(path).split(".")[-1]) == normalized:
                return target_info
    return None


def local_column_mappings(columns: list[str], field_map: dict[str, Any] | None = None) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for column in columns:
        normalized = normalize_local_column_key(column)
        target = ""
        label = "unmapped"
        configured_target = local_field_map_column_target(column, field_map)
        if configured_target:
            target, label = configured_target
        else:
            for candidate_target, candidate_label, aliases in LOCAL_COLUMN_TARGETS:
                if normalized in {normalize_local_column_key(alias) for alias in aliases}:
                    target = candidate_target
                    label = candidate_label
                    break
        values.append({"column": column, "target": target, "label": label})
    return values


def local_mapping_quality_status(score: float, has_error: bool) -> str:
    if has_error:
        return "poor" if score < 0.65 else "warning"
    if score >= 0.85:
        return "good"
    if score >= 0.55:
        return "warning"
    return "poor"


def local_row_mapping_quality(
    fields: dict[str, str],
    identifiers: dict[str, str],
    creators: list[ImportedCreator],
) -> dict[str, Any]:
    present = {
        "title": bool(fields.get("title")),
        "identifier": bool(identifiers),
        "date": bool(fields.get("date")),
        "creators": bool(creators),
    }
    issues: list[dict[str, str]] = []
    score = 0.0
    for spec in LOCAL_MAPPING_QUALITY_FIELDS:
        field = str(spec["field"])
        if present.get(field):
            score += float(spec["weight"])
            continue
        issues.append(
            {
                "field": field,
                "label": str(spec["label"]),
                "severity": str(spec["severity"]),
                "message": str(spec["missing_message"]),
            }
        )
    return {
        "score": round(score, 2),
        "status": local_mapping_quality_status(score, any(issue["severity"] == "error" for issue in issues)),
        "coverage": present,
        "issues": issues,
    }


def local_file_mapping_quality_summary(row_qualities: list[dict[str, Any]], *, truncated: bool) -> dict[str, Any]:
    row_count = len(row_qualities)
    if row_count == 0:
        return {
            "status": "empty",
            "score": 0.0,
            "row_count": 0,
            "rows_with_issues": 0,
            "rows_with_errors": 0,
            "truncated": truncated,
            "fields": [],
            "recommendations": ["文件没有可预览的数据行。"],
        }
    fields: list[dict[str, Any]] = []
    recommendations: list[str] = []
    for spec in LOCAL_MAPPING_QUALITY_FIELDS:
        field = str(spec["field"])
        present_count = sum(1 for quality in row_qualities if (quality.get("coverage") or {}).get(field))
        missing_count = row_count - present_count
        coverage = present_count / row_count
        fields.append(
            {
                "field": field,
                "label": str(spec["label"]),
                "present_count": present_count,
                "missing_count": missing_count,
                "coverage": round(coverage, 2),
                "severity": str(spec["severity"]),
                "message": str(spec["missing_message"]) if missing_count else "",
            }
        )
        if missing_count:
            recommendations.append(f"{missing_count}/{row_count} 行缺少 {spec['label']}。")
    score = sum(float(quality.get("score") or 0.0) for quality in row_qualities) / row_count
    rows_with_errors = sum(
        1
        for quality in row_qualities
        if any(issue.get("severity") == "error" for issue in quality.get("issues") or [])
    )
    rows_with_issues = sum(1 for quality in row_qualities if quality.get("issues"))
    if not recommendations:
        recommendations.append("关键字段覆盖良好，可以直接进入检索和导入验证。")
    return {
        "status": local_mapping_quality_status(score, rows_with_errors > 0),
        "score": round(score, 2),
        "row_count": row_count,
        "rows_with_issues": rows_with_issues,
        "rows_with_errors": rows_with_errors,
        "truncated": truncated,
        "fields": fields,
        "recommendations": recommendations[:4],
    }


def local_file_mapped_row(row: dict[str, Any], field_map: dict[str, Any] | None = None) -> dict[str, Any]:
    if not field_map:
        return row
    return http_json_mapped_row(row, {"field_map": field_map})


def local_file_mapping_sample(row: dict[str, Any], path: Path, row_number: int, field_map: dict[str, Any] | None = None) -> dict[str, Any]:
    mapped_row = local_file_mapped_row(row, field_map)
    fields = local_item_fields(mapped_row, path, row_number)
    identifiers = local_identifiers(mapped_row, fields)
    creators = local_creators(mapped_row)
    tags = local_tags(mapped_row)
    item = ImportedItem(
        item_type=local_item_type(mapped_row),
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source="Local CSV/JSONL",
    )
    source_preview = {
        str(key): local_value_to_text(value)[:300]
        for key, value in row.items()
        if clean_text(local_value_to_text(value))
    }
    return {
        "row": row_number,
        "source": source_preview,
        "item": item.as_dict(),
        "title": fields.get("title", ""),
        "identifiers": identifiers,
        "quality": local_row_mapping_quality(fields, identifiers, creators),
    }


def local_file_field_map_suggestion(
    columns: list[str],
    samples: list[dict[str, Any]],
    *,
    existing_field_map: dict[str, Any] | None = None,
    replace_existing: bool | None = None,
) -> dict[str, Any]:
    should_replace_existing = not bool(existing_field_map) if replace_existing is None else bool(replace_existing)
    suggestion = retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "localfile",
            "columns": columns,
            "samples": samples,
            "field_map": existing_field_map or {},
            "replace_existing": should_replace_existing,
        }
    )
    suggestion["sample_count"] = len(samples)
    suggestion["columns"] = columns
    suggestion["config_draft"] = {"field_map": suggestion.get("field_map") or {}}
    suggestion["draft_available"] = bool(suggestion.get("field_map"))
    suggestion["message"] = "Local CSV/JSONL field_map suggestion can be saved with the local source paths."
    return suggestion


def preview_local_file_mappings(
    values: list[str | Path] | None = None,
    *,
    sample_size: int = 2,
    max_rows_per_file: int = 1000,
    field_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = configured_local_file_paths(values)
    sample_limit = max(1, min(int(sample_size or 2), 5))
    max_rows = max(sample_limit, min(int(max_rows_per_file or 1000), 10000))
    previews: list[dict[str, Any]] = []
    for path in files:
        columns: list[str] = []
        seen_columns: set[str] = set()
        samples: list[dict[str, Any]] = []
        raw_samples: list[dict[str, Any]] = []
        row_qualities: list[dict[str, Any]] = []
        scanned_rows = 0
        truncated = False
        for row_number, row in iter_local_file_rows(path):
            scanned_rows += 1
            sample = local_file_mapping_sample(row, path, row_number, field_map=field_map)
            row_qualities.append(sample["quality"])
            for column in row:
                key = str(column)
                if key not in seen_columns:
                    seen_columns.add(key)
                    columns.append(key)
            if len(samples) < sample_limit:
                samples.append(sample)
                raw_samples.append(row)
            if scanned_rows >= max_rows:
                truncated = True
                break
        previews.append(
            {
                "path": str(path),
                "name": path.name,
                "format": path.suffix.lower().lstrip("."),
                "columns": columns,
                "mappings": local_column_mappings(columns, field_map=field_map),
                "field_map_suggestion": local_file_field_map_suggestion(columns, raw_samples, existing_field_map=field_map),
                "quality": local_file_mapping_quality_summary(row_qualities, truncated=truncated),
                "row_count": scanned_rows,
                "truncated": truncated,
                "samples": samples,
            }
        )
    return {
        "file_count": len(previews),
        "sample_size": sample_limit,
        "max_rows_per_file": max_rows,
        "files": previews,
    }


def suggest_local_file_field_map(
    values: list[str | Path] | None = None,
    *,
    sample_size: int = 3,
    field_map: dict[str, Any] | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    preview = preview_local_file_mappings(
        values,
        sample_size=sample_size,
        field_map=None if replace_existing else field_map,
    )
    combined_field_map: dict[str, Any] = {}
    combined_suggestions: list[dict[str, Any]] = []
    unmapped_source_paths: list[str] = []
    recommendations: list[str] = []
    file_summaries: list[dict[str, Any]] = []
    sample_count = 0
    all_columns: list[str] = []
    for file in preview.get("files") or []:
        if not isinstance(file, dict):
            continue
        suggestion = file.get("field_map_suggestion") if isinstance(file.get("field_map_suggestion"), dict) else {}
        file_field_map = suggestion.get("field_map") if isinstance(suggestion.get("field_map"), dict) else {}
        for target, source_path in file_field_map.items():
            if replace_existing or target not in combined_field_map:
                combined_field_map[str(target)] = source_path
        for item in suggestion.get("suggestions") or []:
            if isinstance(item, dict):
                enriched = dict(item)
                enriched["file"] = str(file.get("name") or file.get("path") or "")
                combined_suggestions.append(enriched)
        for path in suggestion.get("unmapped_source_paths") or []:
            text = clean_text(path)
            if text and text not in unmapped_source_paths:
                unmapped_source_paths.append(text)
        quality = suggestion.get("quality") if isinstance(suggestion.get("quality"), dict) else {}
        for message in quality.get("recommendations") or []:
            text = clean_text(message)
            if text and text not in recommendations:
                recommendations.append(text)
        sample_count += int(suggestion.get("sample_count") or 0)
        columns = [str(column) for column in (file.get("columns") or []) if str(column)]
        for column in columns:
            if column not in all_columns:
                all_columns.append(column)
        file_summaries.append(
            {
                "file": str(file.get("name") or file.get("path") or ""),
                "path": str(file.get("path") or ""),
                "columns": columns,
                "sample_count": int(suggestion.get("sample_count") or 0),
                "field_map": file_field_map,
                "suggested_field_count": len(file_field_map),
                "quality": quality,
            }
        )
    coverage: dict[str, Any] = {}
    score = 0.0
    for group in FIELD_MAP_REQUIRED_GROUPS:
        field = str(group["field"])
        present = any(target in combined_field_map for target in group["targets"])
        coverage[field] = present
        if present:
            score += float(group["weight"])
    status = local_mapping_quality_status(score, not coverage.get("title"))
    return {
        "source_type": "localfile",
        "field_map": combined_field_map,
        "config_draft": {"field_map": combined_field_map} if combined_field_map else {},
        "suggestions": combined_suggestions,
        "files": file_summaries,
        "file_count": len(file_summaries),
        "sample_count": sample_count,
        "columns": all_columns,
        "unmapped_source_paths": unmapped_source_paths,
        "quality": {
            "status": status,
            "score": round(score, 2),
            "coverage": coverage,
            "recommendations": recommendations or ["Key mappings are covered; run preview before importing."],
        },
        "supported_targets": retrieval_field_map_targets(),
    }


def iter_local_file_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader, start=2):
                yield index, dict(row)
        return
    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RetrievalError(f"Local JSONL 解析失败：{path.name}:{index}: {exc}") from exc
                if isinstance(payload, dict):
                    yield index, payload
        return
    raise RetrievalError(f"Local CSV/JSONL 不支持该文件类型：{path.name}")


def local_row_matches_query(row: dict[str, Any], query: str) -> bool:
    haystack = clean_text(" ".join(local_value_to_text(value) for value in row.values())).casefold()
    tokens = [token.casefold() for token in re.findall(r"[\w.-]+", query) if token.strip()]
    return bool(tokens) and all(token in haystack for token in tokens)


def local_file_candidate(
    row: dict[str, Any],
    path: Path,
    row_number: int,
    query: str,
    *,
    field_map: dict[str, Any] | None = None,
) -> RetrievedCandidate:
    mapped_row = local_file_mapped_row(row, field_map)
    fields = local_item_fields(mapped_row, path, row_number)
    identifiers = local_identifiers(mapped_row, fields)
    item_type = local_item_type(mapped_row)
    creators = local_creators(mapped_row)
    tags = local_tags(mapped_row)
    source_id = local_first_value(mapped_row, ["local_id", "source_id", "external_id", "id", "key", "uuid"])
    external_id = next(iter(identifiers.values()), "") or source_id or f"{path.name}:{row_number}"
    evidence = ["Local CSV/JSONL row"]
    for key, label in {
        "doi": "DOI",
        "arxiv": "arXiv ID",
        "pmid": "PMID",
        "pmcid": "PMCID",
        "ads_bibcode": "ADS Bibcode",
        "isbn": "ISBN",
    }.items():
        if identifiers.get(key):
            evidence.append(label)
    item = ImportedItem(
        item_type=item_type,
        fields={key: value for key, value in fields.items() if value},
        creators=creators,
        tags=tags,
        identifiers=identifiers,
        source="Local CSV/JSONL",
    )
    return RetrievedCandidate(
        source="localfile",
        external_id=external_id,
        item=item,
        raw={"file": str(path), "row": row_number, "data": row},
        confidence=local_confidence(row, fields, identifiers, query),
        evidence=evidence,
        landing_url=fields.get("url", ""),
        pdf_url=local_first_value(mapped_row, ["pdf_url", "pdf", "full_text_url", "attachment_url"]),
    )


def local_item_fields(row: dict[str, Any], path: Path, row_number: int) -> dict[str, str]:
    title = local_first_value(row, ["title", "name", "display_name", "paper_title", "article_title"])
    date = local_first_value(row, ["date", "year", "publication_year", "publicationYear", "issued"])
    abstract = local_first_value(row, ["abstractNote", "abstract", "summary", "description"])
    venue = local_first_value(row, ["publicationTitle", "journal", "container_title", "venue", "conference", "source_title"])
    source_id = local_first_value(row, ["local_id", "source_id", "external_id", "id", "key", "uuid"])
    extra_values = [
        local_first_value(row, ["extra", "note", "notes"]),
        f"Local Source File: {path.name}",
        f"Local Source Row: {row_number}",
        f"Local Source ID: {source_id}" if source_id else "",
    ]
    fields = {
        "title": title,
        "date": date,
        "DOI": normalize_doi(local_first_value(row, ["DOI", "doi"])),
        "url": local_first_value(row, ["url", "URL", "landing_url", "link"]),
        "abstractNote": abstract,
        "publicationTitle": venue,
        "publisher": local_first_value(row, ["publisher", "repository", "institution"]),
        "volume": local_first_value(row, ["volume"]),
        "issue": local_first_value(row, ["issue", "number"]),
        "pages": local_first_value(row, ["pages", "page"]),
        "extra": "\n".join(value for value in extra_values if value),
    }
    return {key: clean_text(value) for key, value in fields.items() if clean_text(value)}


def local_identifiers(row: dict[str, Any], fields: dict[str, str]) -> dict[str, str]:
    values = {
        "doi": normalize_doi(local_first_value(row, ["doi", "DOI"]) or fields.get("DOI", "")),
        "arxiv": normalize_arxiv_id(local_first_value(row, ["arxiv", "arxiv_id", "arXiv"])),
        "pmid": normalize_pmid(local_first_value(row, ["pmid", "PMID"])),
        "pmcid": normalize_pmcid(local_first_value(row, ["pmcid", "PMCID"])),
        "ads_bibcode": normalize_ads_bibcode(local_first_value(row, ["ads_bibcode", "bibcode"])),
        "isbn": normalize_isbn(local_first_value(row, ["isbn", "ISBN"])),
    }
    haystack = "\n".join(str(value or "") for value in [*row.values(), *fields.values()])
    if not values["doi"]:
        values["doi"] = normalize_doi(haystack)
    if not values["arxiv"]:
        values["arxiv"] = normalize_arxiv_id(haystack)
    return {key: value for key, value in values.items() if value}


def local_item_type(row: dict[str, Any]) -> str:
    raw = local_first_value(row, ["item_type", "itemType", "type", "zotero_type", "resource_type", "genre"])
    normalized = clean_text(raw).casefold().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "article": "journalArticle",
        "journalarticle": "journalArticle",
        "paper": "journalArticle",
        "conference": "conferencePaper",
        "conferencepaper": "conferencePaper",
        "proceedings": "conferencePaper",
        "preprint": "preprint",
        "dataset": "dataset",
        "data": "dataset",
        "software": "computerProgram",
        "computerprogram": "computerProgram",
        "code": "computerProgram",
        "report": "report",
        "technicalreport": "report",
        "book": "book",
        "chapter": "bookSection",
        "bookchapter": "bookSection",
        "booksection": "bookSection",
        "thesis": "thesis",
        "dissertation": "thesis",
        "webpage": "webpage",
        "website": "webpage",
    }
    return aliases.get(normalized, raw if raw in {"journalArticle", "conferencePaper", "bookSection", "computerProgram"} else "journalArticle")


def local_creators(row: dict[str, Any]) -> list[ImportedCreator]:
    family = local_first_value(row, ["familyName", "last_name", "lastName", "author_last"])
    given = local_first_value(row, ["givenName", "first_name", "firstName", "author_first"])
    if family or given:
        return [ImportedCreator(first_name=given, last_name=family)]
    raw = local_raw_value(row, ["authors", "author", "creators", "creator", "contributors"])
    if isinstance(raw, list):
        creators: list[ImportedCreator] = []
        for value in raw:
            if isinstance(value, dict):
                creator_family = clean_text(value.get("familyName") or value.get("last_name") or value.get("lastName") or "")
                creator_given = clean_text(value.get("givenName") or value.get("first_name") or value.get("firstName") or "")
                creator_name = clean_text(value.get("name") or value.get("display_name") or "")
                if creator_family or creator_given:
                    creators.append(ImportedCreator(first_name=creator_given, last_name=creator_family or creator_name))
                elif creator_name:
                    creators.append(name_parts(creator_name))
            else:
                creators.append(name_parts(local_value_to_text(value)))
        return [creator for creator in creators if creator.last_name]
    names = split_local_list(raw)
    return [creator for creator in (name_parts(name) for name in names) if creator.last_name]


def local_tags(row: dict[str, Any]) -> list[str]:
    raw = local_raw_value(row, ["tags", "keywords", "subjects", "subject"])
    tags: list[str] = []
    for tag in split_local_list(raw):
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:12]


def local_confidence(row: dict[str, Any], fields: dict[str, str], identifiers: dict[str, str], query: str) -> float:
    confidence = 0.68 if fields.get("title") else 0.54
    if identifiers:
        confidence += 0.13
    title = fields.get("title", "").casefold()
    if clean_text(query).casefold() in title:
        confidence += 0.07
    elif local_row_matches_query(row, query):
        confidence += 0.03
    return min(confidence, 0.9)


def local_first_value(row: dict[str, Any], keys: list[str]) -> str:
    raw = local_raw_value(row, keys)
    if raw is None:
        return ""
    text = local_value_to_text(raw)
    return clean_text(text)


def local_raw_value(row: dict[str, Any], keys: list[str]) -> Any:
    by_normalized = {normalize_local_column_key(key): value for key, value in row.items()}
    for key in keys:
        normalized = normalize_local_column_key(key)
        if normalized in by_normalized:
            raw = by_normalized[normalized]
            if clean_text(local_value_to_text(raw)):
                return raw
    return None


def local_value_to_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(local_value_to_text(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {local_value_to_text(raw)}" for key, raw in value.items())
    return clean_text(value)


def split_local_list(value: Any) -> list[str]:
    text = local_value_to_text(value)
    if not text:
        return []
    separator = ";" if ";" in text else "|" if "|" in text else ","
    return [clean_text(part) for part in text.split(separator) if clean_text(part)]


HTTP_JSON_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "display_name", "paper_title", "article_title"),
    "date": ("date", "year", "publication_year", "publicationYear", "issued"),
    "abstract": ("abstractNote", "abstract", "summary", "description"),
    "venue": (
        "publicationTitle",
        "publication_title",
        "journal",
        "journal_name",
        "container_title",
        "venue",
        "venue_name",
        "conference",
        "conference_name",
        "source_title",
    ),
    "doi": ("DOI", "doi"),
    "url": ("url", "URL", "landing_url", "link"),
    "publisher": ("publisher", "repository", "institution"),
    "volume": ("volume",),
    "issue": ("issue", "number"),
    "pages": ("pages", "page"),
    "item_type": ("item_type", "itemType", "type", "zotero_type", "resource_type", "genre"),
    "authors": (
        "authors",
        "author",
        "creators",
        "creator",
        "contributors",
        "familyName",
        "givenName",
        "last_name",
        "first_name",
    ),
    "tags": ("tags", "keywords", "subjects", "subject"),
    "arxiv": ("arxiv", "arxiv_id", "arXiv"),
    "pmid": ("pmid", "PMID"),
    "pmcid": ("pmcid", "PMCID"),
    "ads_bibcode": ("ads_bibcode", "bibcode"),
    "isbn": ("isbn", "ISBN"),
    "external_id": ("local_id", "source_id", "external_id", "id", "key", "uuid"),
    "pdf_url": ("pdf_url", "pdf", "full_text_url", "attachment_url"),
    "extra": ("extra", "note", "notes"),
}


HTTP_JSON_TEMPLATE_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "date": "year",
    "doi": "doi",
    "abstract": "abstract",
    "authors": "authors",
    "url": "url",
    "venue": "venue",
    "item_type": "item_type",
    "tags": "keywords",
    "external_id": "id",
    "pdf_url": "pdf_url",
}


FIELD_MAP_TARGET_LABELS: dict[str, str] = {
    "title": "Title",
    "identifier": "Strong identifier",
    "date": "Date",
    "abstract": "Abstract",
    "venue": "Venue",
    "doi": "DOI",
    "url": "URL",
    "publisher": "Publisher",
    "volume": "Volume",
    "issue": "Issue",
    "pages": "Pages",
    "item_type": "Item type",
    "authors": "Creators",
    "creators": "Creators",
    "tags": "Tags",
    "arxiv": "arXiv",
    "pmid": "PMID",
    "pmcid": "PMCID",
    "ads_bibcode": "ADS Bibcode",
    "isbn": "ISBN",
    "external_id": "Source ID",
    "pdf_url": "PDF URL",
    "extra": "Extra",
}
FIELD_MAP_IDENTIFIER_TARGETS = ("doi", "arxiv", "pmid", "pmcid", "ads_bibcode", "isbn")
FIELD_MAP_REQUIRED_GROUPS: tuple[dict[str, Any], ...] = (
    {"field": "title", "targets": ("title",), "weight": 0.35, "severity": "error"},
    {"field": "identifier", "targets": FIELD_MAP_IDENTIFIER_TARGETS, "weight": 0.3, "severity": "warning"},
    {"field": "date", "targets": ("date",), "weight": 0.15, "severity": "warning"},
    {"field": "creators", "targets": ("authors",), "weight": 0.2, "severity": "warning"},
)


def retrieval_field_map_targets() -> list[dict[str, Any]]:
    return [
        {
            "target": target,
            "label": FIELD_MAP_TARGET_LABELS.get(target, target),
            "aliases": list(aliases),
        }
        for target, aliases in HTTP_JSON_FIELD_ALIASES.items()
    ]


def field_map_quality(field_map: dict[str, Any]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    score = 0.0
    recommendations: list[str] = []
    for group in FIELD_MAP_REQUIRED_GROUPS:
        field = str(group["field"])
        present = any(target in field_map for target in group["targets"])
        coverage[field] = present
        if present:
            score += float(group["weight"])
        else:
            recommendations.append(f"Map {FIELD_MAP_TARGET_LABELS.get(field, field)} before relying on batch import.")
    return {
        "status": local_mapping_quality_status(score, not coverage.get("title")),
        "score": round(score, 2),
        "coverage": coverage,
        "recommendations": recommendations or ["Key mappings are covered; run preview before importing."],
    }


def normalize_field_map_path(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def field_map_path_parts(path: str) -> list[str]:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(path or ""))
    return [part for part in re.split(r"[^A-Za-z0-9]+", words.casefold()) if part]


def field_map_value_hint(target: str, value: Any, path: str) -> tuple[float, str]:
    text = clean_text(local_value_to_text(value))
    lower_path = str(path or "").casefold()
    if not text:
        return 0.0, ""
    if target == "doi" and normalize_doi(text):
        return 0.86, "sample value looks like a DOI"
    if target == "arxiv" and normalize_arxiv_id(text):
        return 0.82, "sample value looks like an arXiv ID"
    if target == "pmid" and normalize_pmid(text):
        return 0.8, "sample value looks like a PMID"
    if target == "pmcid" and normalize_pmcid(text):
        return 0.8, "sample value looks like a PMCID"
    if target == "ads_bibcode" and normalize_ads_bibcode(text):
        return 0.8, "sample value looks like an ADS Bibcode"
    if target == "isbn" and normalize_isbn(text):
        return 0.78, "sample value looks like an ISBN"
    if target == "pdf_url" and ("pdf" in lower_path or text.lower().endswith(".pdf")) and text.lower().startswith(("http://", "https://")):
        return 0.84, "sample value looks like a PDF URL"
    if target == "url" and text.lower().startswith(("http://", "https://")):
        return 0.72, "sample value looks like a URL"
    if target == "date" and re.search(r"\b(18|19|20)\d{2}\b", text):
        return 0.66, "sample value contains a year"
    return 0.0, ""


def field_map_match_score(target: str, path: str, value: Any) -> tuple[float, str]:
    path_text = clean_text(path)
    if not path_text:
        return 0.0, ""
    path_norm = normalize_field_map_path(path_text)
    path_parts = field_map_path_parts(path_text)
    leaf = path_parts[-1] if path_parts else path_norm
    aliases = HTTP_JSON_FIELD_ALIASES.get(target, ())
    alias_norms = {normalize_field_map_path(alias) for alias in aliases}
    alias_parts = {part for alias in aliases for part in field_map_path_parts(alias)}
    if path_norm in alias_norms or leaf in alias_norms:
        return 0.98, "source path matches a known alias"
    if any(path_norm.endswith(alias) for alias in alias_norms if alias):
        return 0.9, "source path ends with a known alias"
    if alias_parts and leaf in alias_parts:
        return 0.78, "source path leaf matches a known alias token"
    overlap = len(set(path_parts) & alias_parts)
    if overlap:
        return min(0.72, 0.5 + overlap * 0.08), "source path shares alias tokens"
    return field_map_value_hint(target, value, path_text)


def add_field_map_sample_path(paths: dict[str, Any], path: str, value: Any) -> None:
    text = clean_text(local_value_to_text(value))
    if path and text and path not in paths:
        paths[path] = value


def collect_field_map_sample_paths(value: Any, *, prefix: str = "", paths: dict[str, Any] | None = None, depth: int = 0) -> dict[str, Any]:
    collected = paths if paths is not None else {}
    if prefix:
        add_field_map_sample_path(collected, prefix, value)
    if depth >= 4:
        return collected
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = clean_text(key)
            if not key_text:
                continue
            child_path = f"{prefix}.{key_text}" if prefix else key_text
            collect_field_map_sample_paths(item, prefix=child_path, paths=collected, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:3]:
            if isinstance(item, dict):
                collect_field_map_sample_paths(item, prefix=prefix, paths=collected, depth=depth + 1)
    return collected


def field_map_paths_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for key in ("paths", "columns"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                path = clean_text(item)
                if path:
                    paths.setdefault(path, "")
    sample_values = payload.get("samples")
    if sample_values is None and "sample" in payload:
        sample_values = [payload.get("sample")]
    if isinstance(sample_values, dict):
        sample_values = [sample_values]
    if isinstance(sample_values, list):
        for sample in sample_values[:10]:
            if isinstance(sample, dict):
                collect_field_map_sample_paths(sample, paths=paths)
    return paths


def normalize_existing_field_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): raw for key, raw in value.items() if str(key) in HTTP_JSON_FIELD_ALIASES and raw}


def flatten_field_map_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    return [text] if text else []


def field_map_config_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("config") if "config" in payload else payload.get("config_text")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def normalize_field_map_source_type(value: Any) -> str:
    text = re.sub(r"[\s-]+", "_", clean_text(value).casefold())
    aliases = {
        "": "generic",
        "local": "localfile",
        "local_file": "localfile",
        "local_csv": "localfile",
        "csv": "localfile",
        "jsonl": "localfile",
        "http": "httpjson",
        "http_json": "httpjson",
        "rest": "httpjson",
        "sqlite3": "sqlite",
        "object_manifest": "manifest",
        "objectmanifest": "manifest",
    }
    return aliases.get(text, text or "generic")


def field_map_payload_columns(payload: dict[str, Any], paths: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    raw_columns = payload.get("columns")
    if isinstance(raw_columns, list):
        for item in raw_columns:
            column = clean_text(item)
            if column and column not in columns:
                columns.append(column)
    if columns:
        return columns
    for path in paths:
        if "." not in path and path not in columns:
            columns.append(path)
    return columns


def starter_field_map_config_draft(
    source_type: str,
    field_map: dict[str, Any],
    paths: dict[str, Any],
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    if config:
        return {**config, "field_map": field_map}
    if not field_map:
        return {}
    if source_type == "localfile":
        return {"field_map": field_map}
    if source_type == "httpjson":
        return {
            "label": "Draft HTTP JSON",
            "url_template": "https://example.test/search?q={query}&limit={limit}",
            "items_path": clean_text(payload.get("items_path")) or "results",
            "field_map": field_map,
        }
    if source_type == "sqlite":
        columns = field_map_payload_columns(payload, paths)
        select_columns = ", ".join(columns[:12]) or "*"
        return {
            "label": "Draft SQLite",
            "path": "C:/data/retrieval.sqlite",
            "query": f"SELECT {select_columns} FROM items LIMIT :limit",
            "field_map": field_map,
        }
    if source_type == "manifest":
        return {
            "label": "Draft Object Manifest",
            "manifest_path": "C:/data/object-manifest.json",
            "items_path": clean_text(payload.get("items_path")) or "items",
            "field_map": field_map,
        }
    return {}


def field_map_ai_requested(payload: dict[str, Any]) -> bool:
    if "use_ai" in payload:
        return truthy_config_value(payload.get("use_ai"))
    if "ai" in payload:
        return truthy_config_value(payload.get("ai"))
    return truthy_config_value(os.environ.get(FIELD_MAP_AI_ENABLED_ENV))


def compact_json_for_model(value: Any, *, max_chars: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "...[truncated]"


def field_map_ai_messages(
    source_type: str,
    field_map: dict[str, Any],
    suggestions: list[dict[str, Any]],
    paths: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    sample_values = payload.get("samples")
    if sample_values is None and "sample" in payload:
        sample_values = [payload.get("sample")]
    source_paths = [
        {
            "path": path,
            "sample_value": clean_text(local_value_to_text(value))[:160],
        }
        for path, value in list(paths.items())[:120]
    ]
    task = {
        "source_type": source_type,
        "allowed_targets": [target["target"] for target in retrieval_field_map_targets()],
        "source_paths": source_paths,
        "rule_field_map": field_map,
        "rule_suggestions": suggestions[:20],
        "samples": sample_values if isinstance(sample_values, list) else [],
        "response_schema": {
            "field_map": {"target": "one source path from source_paths"},
            "notes": ["short reason"],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You map heterogeneous bibliographic metadata into a Zotero-like field_map. "
                "Return only a JSON object. Use only allowed target names and only source paths "
                "that appear in source_paths. Do not invent paths, URLs, keys, or credentials."
            ),
        },
        {"role": "user", "content": compact_json_for_model(task)},
    ]


def validated_ai_field_map(raw: Any, paths: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if not isinstance(raw, dict):
        return {}, [{"target": "", "source_path": "", "reason": "model field_map is not an object"}]
    available_paths = set(paths)
    validated: dict[str, Any] = {}
    rejected: list[dict[str, str]] = []
    for target, raw_paths in raw.items():
        clean_target = clean_text(target)
        if clean_target not in HTTP_JSON_FIELD_ALIASES:
            rejected.append({"target": clean_target, "source_path": clean_text(raw_paths), "reason": "unsupported target"})
            continue
        candidates = flatten_field_map_values(raw_paths)
        accepted = [path for path in candidates if path in available_paths]
        if not accepted:
            rejected.append({"target": clean_target, "source_path": clean_text(raw_paths), "reason": "source path not found in samples"})
            continue
        validated[clean_target] = accepted[0] if len(accepted) == 1 else accepted
    return validated, rejected


def ai_field_map_suggestion_rows(field_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target, source_path in field_map.items():
        rows.append(
            {
                "target": target,
                "label": FIELD_MAP_TARGET_LABELS.get(target, target),
                "source_path": source_path,
                "confidence": 0.76,
                "reason": "AI Pixel model suggestion validated against sample paths",
                "sample_value": "",
                "existing": False,
                "ai": True,
            }
        )
    return rows


def apply_field_map_ai_enhancement(
    source_type: str,
    field_map: dict[str, Any],
    suggestions: list[dict[str, Any]],
    paths: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    status = retrieval_model_status()
    enhancement: dict[str, Any] = {
        "requested": field_map_ai_requested(payload),
        "configured": bool(status.get("configured")),
        "provider": status.get("provider"),
        "base_url": status.get("base_url"),
        "model": status.get("model"),
        "status": "skipped",
        "message": "",
        "field_map": {},
        "rejected": [],
        "applied_field_count": 0,
    }
    if not enhancement["requested"]:
        enhancement["message"] = f"Set use_ai=true or {FIELD_MAP_AI_ENABLED_ENV}=1 to request AI field-map enhancement."
        return field_map, suggestions, enhancement
    if not paths:
        enhancement["status"] = "empty"
        enhancement["message"] = "AI enhancement skipped because no source paths were provided."
        return field_map, suggestions, enhancement
    if not enhancement["configured"]:
        enhancement["status"] = "not_configured"
        enhancement["message"] = f"Set {AI_PIXEL_API_KEY_ENV} before using AI Pixel suggestions."
        return field_map, suggestions, enhancement

    post_json = payload.get("_ai_post_json") if callable(payload.get("_ai_post_json")) else _http_post_json
    try:
        model_response = ai_pixel_chat_json(
            field_map_ai_messages(source_type, field_map, suggestions, paths, payload),
            post_json=post_json,
        )
    except Exception as exc:  # noqa: BLE001 - model help must not break deterministic suggestions
        enhancement["status"] = "error"
        enhancement["message"] = clean_text(str(exc) or exc.__class__.__name__)
        return field_map, suggestions, enhancement

    raw_field_map = model_response.get("field_map") if isinstance(model_response, dict) else {}
    ai_field_map, rejected = validated_ai_field_map(raw_field_map, paths)
    enhancement["field_map"] = ai_field_map
    enhancement["rejected"] = rejected
    notes = model_response.get("notes") if isinstance(model_response, dict) else []
    if isinstance(notes, list):
        enhancement["notes"] = [clean_text(note) for note in notes[:5] if clean_text(note)]
    elif clean_text(notes):
        enhancement["notes"] = [clean_text(notes)]
    if not ai_field_map:
        enhancement["status"] = "empty"
        enhancement["message"] = "AI Pixel returned no valid field_map entries."
        return field_map, suggestions, enhancement

    merged = dict(field_map)
    applied: dict[str, Any] = {}
    replace_existing = truthy_config_value(payload.get("ai_replace_existing"))
    for target, source_path in ai_field_map.items():
        if replace_existing or target not in merged:
            merged[target] = source_path
            applied[target] = source_path
    enhancement["applied_field_count"] = len(applied)
    enhancement["status"] = "applied" if applied else "valid_no_changes"
    enhancement["message"] = (
        f"AI Pixel applied {len(applied)} field_map entries."
        if applied
        else "AI Pixel suggestions were valid, but deterministic mappings already covered those targets."
    )
    return merged, suggestions + ai_field_map_suggestion_rows(applied), enhancement


def retrieval_field_map_suggestion_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RetrievalError("field map suggestion payload must be a JSON object.")
    source_type = normalize_field_map_source_type(payload.get("source_type") or payload.get("source"))
    config = field_map_config_from_payload(payload)
    payload_field_map = payload.get("field_map")
    existing_source = config.get("field_map") if isinstance(config.get("field_map"), dict) else payload_field_map
    existing_field_map = normalize_existing_field_map(existing_source)
    replace_existing = str(payload.get("replace_existing") or "").strip().casefold() in {"1", "true", "yes"}
    paths = field_map_paths_from_payload(payload)
    field_map: dict[str, Any] = {}
    suggestions: list[dict[str, Any]] = []
    used_paths: set[str] = set()
    for target in HTTP_JSON_FIELD_ALIASES:
        if target in existing_field_map and not replace_existing:
            field_map[target] = existing_field_map[target]
            used_paths.update(flatten_field_map_values(existing_field_map[target]))
            suggestions.append(
                {
                    "target": target,
                    "label": FIELD_MAP_TARGET_LABELS.get(target, target),
                    "source_path": existing_field_map[target],
                    "confidence": 1.0,
                    "reason": "existing field_map entry",
                    "existing": True,
                }
            )
            continue
        best: tuple[float, str, str, Any] = (0.0, "", "", "")
        for path, value in paths.items():
            score, reason = field_map_match_score(target, path, value)
            if score > best[0]:
                best = (score, reason, path, value)
        score, reason, path, value = best
        if score < 0.55 or not path:
            continue
        field_map[target] = path
        used_paths.add(path)
        suggestions.append(
            {
                "target": target,
                "label": FIELD_MAP_TARGET_LABELS.get(target, target),
                "source_path": path,
                "confidence": round(score, 2),
                "reason": reason,
                "sample_value": clean_text(local_value_to_text(value))[:160],
                "existing": False,
            }
        )
    field_map, suggestions, ai_enhancement = apply_field_map_ai_enhancement(
        source_type,
        field_map,
        suggestions,
        paths,
        payload,
    )
    quality = field_map_quality(field_map)
    used_paths = {path for raw in field_map.values() for path in flatten_field_map_values(raw)}
    config_draft = starter_field_map_config_draft(source_type, field_map, paths, payload, config)
    return {
        "source_type": source_type,
        "field_map": field_map,
        "config_draft": config_draft,
        "suggestions": suggestions,
        "unmapped_source_paths": [path for path in paths if path not in used_paths],
        "quality": quality,
        "ai_enhancement": ai_enhancement,
        "supported_targets": retrieval_field_map_targets(),
    }


def http_json_config_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "basic-rest",
            "label": "Basic REST",
            "description": "Keyword search endpoint with a results array and no authentication.",
            "config": {
                "label": "Internal REST API",
                "url_template": "https://example.test/search?q={query}&limit={limit}",
                "items_path": "results",
                "field_map": HTTP_JSON_TEMPLATE_FIELD_MAP,
            },
        },
        {
            "id": "bearer-page",
            "label": "Bearer + page",
            "description": "Paged endpoint using Authorization: Bearer from an environment variable.",
            "config": {
                "label": "Internal Bearer API",
                "url_template": "https://example.test/search?q={query}&limit={limit}&page={page}",
                "items_path": "results",
                "max_pages": 3,
                "auth": {"type": "bearer_env", "env": "INTERNAL_API_TOKEN"},
                "field_map": HTTP_JSON_TEMPLATE_FIELD_MAP,
            },
        },
        {
            "id": "api-key-cursor",
            "label": "API key + cursor",
            "description": "Cursor or next-link endpoint using an API key header from an environment variable.",
            "config": {
                "label": "Internal Cursor API",
                "url_template": "https://example.test/search?q={query}&limit={limit}",
                "items_path": "data.items",
                "next_url_path": "links.next",
                "max_pages": 3,
                "auth": {"type": "header_env", "env": "INTERNAL_API_KEY", "header": "X-API-Key"},
                "field_map": {
                    **HTTP_JSON_TEMPLATE_FIELD_MAP,
                    "title": "metadata.title",
                    "date": "metadata.year",
                    "doi": "identifiers.doi",
                    "authors": "metadata.authors",
                    "tags": "metadata.keywords",
                    "url": "links.landing",
                    "pdf_url": "links.pdf",
                },
            },
        },
    ]


def http_json_config(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    raw: Any = value
    if raw is None:
        raw = os.environ.get(HTTP_JSON_CONFIG_ENV, "").strip()
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetrievalError("HTTP JSON 配置必须是 JSON 对象。") from exc
    if not isinstance(raw, dict):
        raise RetrievalError("HTTP JSON 配置必须是 JSON 对象。")
    config = dict(raw)
    field_map = config.get("field_map") or {}
    headers = config.get("headers") or {}
    auth = config.get("auth") or {}
    if not isinstance(field_map, dict):
        raise RetrievalError("HTTP JSON field_map 必须是对象。")
    if not isinstance(headers, dict):
        raise RetrievalError("HTTP JSON headers 必须是对象。")
    if not isinstance(auth, dict):
        raise RetrievalError("HTTP JSON auth 必须是对象。")
    if config.get("url_template") is None and config.get("url") is not None:
        config["url_template"] = config.get("url")
    config["url_template"] = clean_text(config.get("url_template"))
    config["items_path"] = clean_text(config.get("items_path"))
    config["next_url_path"] = clean_text(config.get("next_url_path") or config.get("next_path"))
    config["label"] = clean_text(config.get("label")) or "HTTP JSON"
    config["max_pages"] = http_json_int(config.get("max_pages"), 1, minimum=1, maximum=MAX_HTTP_JSON_PAGES)
    config["page_start"] = http_json_int(config.get("page_start"), 1, minimum=0, maximum=100000)
    config["field_map"] = field_map
    config["headers"] = headers
    config["auth"] = auth
    return config


def http_json_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def http_json_max_pages(config: dict[str, Any]) -> int:
    return http_json_int(config.get("max_pages"), 1, minimum=1, maximum=MAX_HTTP_JSON_PAGES)


def http_json_page_start(config: dict[str, Any]) -> int:
    return http_json_int(config.get("page_start"), 1, minimum=0, maximum=100000)


def http_json_env_value(name: Any) -> str:
    env_name = clean_text(name)
    if not env_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise RetrievalError("HTTP JSON auth/env 配置了无效环境变量名。")
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise RetrievalError(f"HTTP JSON 需要配置环境变量 {env_name}。")
    return value


def http_json_expand_env_refs(value: Any) -> str:
    text = str(value or "")
    return HTTP_JSON_ENV_REF_RE.sub(lambda match: http_json_env_value(match.group(1)), text)


def http_json_auth_headers(config: dict[str, Any]) -> dict[str, str]:
    auth = config.get("auth") or {}
    auth_type = clean_text(auth.get("type")).casefold()
    if not auth_type:
        return {}
    env_name = auth.get("env") or auth.get("token_env") or auth.get("api_key_env")
    token = http_json_env_value(env_name)
    if auth_type in {"bearer", "bearer_env"}:
        return {"Authorization": f"Bearer {token}"}
    if auth_type in {"header", "header_env", "api_key", "api_key_env"}:
        header = clean_text(auth.get("header") or "X-API-Key")
        if not header:
            raise RetrievalError("HTTP JSON auth.header 不能为空。")
        prefix = str(auth.get("prefix") or "")
        return {header: f"{prefix}{token}"}
    raise RetrievalError("HTTP JSON auth.type 仅支持 bearer_env 或 header_env。")


def http_json_headers(config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in (config.get("headers") or {}).items():
        header = clean_text(key)
        expanded = clean_text(http_json_expand_env_refs(value))
        if header and expanded:
            headers[header] = expanded
    headers.update(http_json_auth_headers(config))
    return headers


def http_json_config_summary(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    config = http_json_config(value)
    field_map = config.get("field_map") or {}
    auth = config.get("auth") or {}
    env_headers = [
        str(key)
        for key, raw in (config.get("headers") or {}).items()
        if HTTP_JSON_ENV_REF_RE.search(str(raw or ""))
    ]
    return {
        "configured": bool(config.get("url_template")),
        "label": config.get("label") or "HTTP JSON",
        "url_template": config.get("url_template") or "",
        "items_path": config.get("items_path") or "",
        "next_url_path": config.get("next_url_path") or "",
        "max_pages": http_json_max_pages(config),
        "page_start": http_json_page_start(config),
        "field_map": field_map,
        "headers": sorted(str(key) for key in (config.get("headers") or {}).keys()),
        "has_headers": bool(config.get("headers")),
        "env_headers": sorted(env_headers),
        "auth_type": clean_text(auth.get("type")),
        "auth_env": clean_text(auth.get("env") or auth.get("token_env") or auth.get("api_key_env")),
        "auth_header": clean_text(auth.get("header")),
    }


def http_json_search_url(template: str, query: str, limit: int, *, page: int = 1, offset: int = 0) -> str:
    values = {
        "query": urllib.parse.quote_plus(query),
        "raw_query": query,
        "limit": str(limit),
        "page": str(page),
        "offset": str(offset),
    }
    try:
        return template.format(**values)
    except KeyError as exc:
        name = clean_text(exc.args[0]) if exc.args else ""
        raise RetrievalError(f"HTTP JSON url_template 不支持占位符：{name}") from exc


def http_json_template_supports_pagination(template: str) -> bool:
    return any(token in str(template or "") for token in ("{page}", "{offset}"))


def http_json_path_value(value: Any, path: Any) -> Any:
    text = clean_text(path)
    if not text:
        return None
    current = value
    for part in text.replace("[", ".").replace("]", "").split("."):
        key = clean_text(part)
        if not key:
            continue
        if isinstance(current, dict):
            if key in current:
                current = current[key]
                continue
            normalized = normalize_local_column_key(key)
            match = next((raw_key for raw_key in current if normalize_local_column_key(raw_key) == normalized), None)
            if match is None:
                return None
            current = current[match]
            continue
        if isinstance(current, list) and key.isdigit():
            index = int(key)
            if index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def http_json_result_items(payload: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    path = clean_text(config.get("items_path"))
    raw = http_json_path_value(payload, path) if path else None
    if raw is None:
        if isinstance(payload, list):
            raw = payload
        elif isinstance(payload, dict):
            for candidate_path in ("items", "results", "data", "docs", "records", "data.records", "response.docs"):
                raw = http_json_path_value(payload, candidate_path)
                if isinstance(raw, list):
                    break
    if not isinstance(raw, list):
        raise RetrievalError("HTTP JSON 响应中没有数组结果；请配置 items_path。")
    return [item for item in raw if isinstance(item, dict)]


def http_json_url_text(value: Any) -> str:
    raw = value
    if isinstance(raw, dict):
        raw = raw.get("href") or raw.get("url") or raw.get("next")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return clean_text(raw)


def http_json_next_url(payload: Any, config: dict[str, Any], *, base_url: str) -> str:
    paths: list[str] = []
    configured_path = clean_text(config.get("next_url_path"))
    if configured_path:
        paths.append(configured_path)
    paths.extend(["next", "next_url", "links.next", "pagination.next", "meta.next"])
    for path in paths:
        value = http_json_path_value(payload, path)
        text = http_json_url_text(value)
        if text:
            return urllib.parse.urljoin(base_url, text)
    return ""


def inferred_items_path(payload: Any, configured_path: str, candidates: tuple[str, ...]) -> str:
    path = clean_text(configured_path)
    if path and isinstance(http_json_path_value(payload, path), list):
        return path
    if isinstance(payload, list):
        return ""
    if isinstance(payload, dict):
        for candidate_path in candidates:
            if isinstance(http_json_path_value(payload, candidate_path), list):
                return candidate_path
    return path


def http_json_sample_items(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 3,
    get_json: JsonFetcher | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = http_json_config(config_value)
    template = clean_text(config.get("url_template"))
    if not template:
        raise RetrievalError(f"HTTP JSON 需要配置 {HTTP_JSON_CONFIG_ENV} 或文库偏好后使用。")
    clean_query = clean_text(query) or HEALTH_CHECK_QUERY
    sample_limit = max(1, min(int(sample_size or 3), 10))
    url = http_json_search_url(template, clean_query, sample_limit, page=http_json_page_start(config), offset=0)
    if get_json is None:
        provider = HttpJsonProvider(config=config)
        payload = _http_get_json(
            url,
            timeout=provider_timeout_seconds(provider),
            headers=http_json_headers(config),
        )
    else:
        payload = get_json(url)
    items_path = inferred_items_path(
        payload,
        clean_text(config.get("items_path")),
        ("items", "results", "data", "docs", "records", "data.records", "response.docs"),
    )
    draft_config = {**config}
    if items_path:
        draft_config["items_path"] = items_path
    items = http_json_result_items(payload, draft_config)
    return draft_config, items[:sample_limit]


def suggest_http_json_field_map(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 3,
    replace_existing: bool = True,
    get_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    config, items = http_json_sample_items(
        config_value,
        query=query,
        sample_size=sample_size,
        get_json=get_json,
    )
    suggestion = retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "httpjson",
            "config": config,
            "samples": items,
            "replace_existing": replace_existing,
        }
    )
    suggestion["query"] = clean_text(query) or HEALTH_CHECK_QUERY
    suggestion["sample_count"] = len(items)
    return suggestion


def http_json_mapped_row(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(row)
    field_map = config.get("field_map") or {}
    for target, aliases in HTTP_JSON_FIELD_ALIASES.items():
        paths: list[Any] = []
        if target in field_map:
            configured = field_map[target]
            paths.extend(configured if isinstance(configured, list) else [configured])
        paths.extend(aliases)
        for path in paths:
            raw = http_json_path_value(row, path)
            if raw is not None and clean_text(local_value_to_text(raw)):
                mapped[target] = raw
                break
    return mapped


def http_json_item_fields(row: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, str]:
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    label = clean_text(config.get("label")) or "HTTP JSON"
    extra_values = [
        local_first_value(row, ["extra", "note", "notes"]),
        f"HTTP JSON Source: {label}",
        f"HTTP JSON Result: {index}",
        f"HTTP JSON Source ID: {source_id}" if source_id else "",
    ]
    fields = {
        "title": local_first_value(row, ["title", "name", "display_name", "paper_title", "article_title"]),
        "date": local_first_value(row, ["date", "year", "publication_year", "publicationYear", "issued"]),
        "DOI": normalize_doi(local_first_value(row, ["DOI", "doi"])),
        "url": local_first_value(row, ["url", "URL", "landing_url", "link"]),
        "abstractNote": local_first_value(row, ["abstractNote", "abstract", "summary", "description"]),
        "publicationTitle": local_first_value(
            row,
            ["publicationTitle", "publication_title", "journal", "journal_name", "container_title", "venue", "venue_name", "conference", "conference_name", "source_title"],
        ),
        "publisher": local_first_value(row, ["publisher", "repository", "institution"]),
        "volume": local_first_value(row, ["volume"]),
        "issue": local_first_value(row, ["issue", "number"]),
        "pages": local_first_value(row, ["pages", "page"]),
        "extra": "\n".join(value for value in extra_values if value),
    }
    return {key: clean_text(value) for key, value in fields.items() if clean_text(value)}


def http_json_confidence(row: dict[str, Any], fields: dict[str, str], identifiers: dict[str, str], query: str) -> float:
    confidence = 0.68 if fields.get("title") else 0.54
    if identifiers:
        confidence += 0.14
    title = fields.get("title", "").casefold()
    if clean_text(query).casefold() in title:
        confidence += 0.06
    elif local_row_matches_query(row, query):
        confidence += 0.03
    return min(confidence, 0.9)


def http_json_candidate(
    raw_row: dict[str, Any],
    config: dict[str, Any],
    index: int,
    query: str,
) -> RetrievedCandidate | None:
    row = http_json_mapped_row(raw_row, config)
    fields = http_json_item_fields(row, config, index)
    identifiers = local_identifiers(row, fields)
    if not fields and not identifiers:
        return None
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    external_id = next(iter(identifiers.values()), "") or source_id or fields.get("url", "") or f"httpjson:{index}"
    evidence = ["HTTP JSON metadata"]
    for key, label in {
        "doi": "DOI",
        "arxiv": "arXiv ID",
        "pmid": "PMID",
        "pmcid": "PMCID",
        "ads_bibcode": "ADS Bibcode",
        "isbn": "ISBN",
    }.items():
        if identifiers.get(key):
            evidence.append(label)
    label = clean_text(config.get("label")) or "HTTP JSON"
    item = ImportedItem(
        item_type=local_item_type(row),
        fields={key: value for key, value in fields.items() if value},
        creators=local_creators(row),
        tags=local_tags(row),
        identifiers=identifiers,
        source=label,
    )
    return RetrievedCandidate(
        source="httpjson",
        external_id=external_id,
        item=item,
        raw={"source": label, "result": raw_row},
        confidence=http_json_confidence(row, fields, identifiers, query),
        evidence=evidence,
        landing_url=fields.get("url", ""),
        pdf_url=local_first_value(row, ["pdf_url", "pdf", "full_text_url", "attachment_url"]),
    )


def http_json_mapping_sample(candidate: RetrievedCandidate, row_number: int) -> dict[str, Any]:
    item = candidate.item
    raw = candidate.raw.get("result") if isinstance(candidate.raw, dict) else {}
    source_preview = {}
    if isinstance(raw, dict):
        source_preview = {
            str(key): local_value_to_text(value)[:300]
            for key, value in raw.items()
            if clean_text(local_value_to_text(value))
        }
    return {
        "row": row_number,
        "source": source_preview,
        "item": item.as_dict(),
        "title": item.fields.get("title", ""),
        "identifiers": item.identifiers,
        "quality": local_row_mapping_quality(item.fields, item.identifiers, item.creators),
        "evidence": candidate.evidence,
        "landing_url": candidate.landing_url,
        "pdf_url": candidate.pdf_url,
    }


def preview_http_json_mappings(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 2,
    get_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    config = http_json_config(config_value)
    if not config.get("url_template"):
        raise RetrievalError(f"HTTP JSON 需要配置 {HTTP_JSON_CONFIG_ENV} 或文库偏好后使用。")
    clean_query = clean_text(query) or HEALTH_CHECK_QUERY
    sample_limit = max(1, min(int(sample_size or 2), 5))
    provider = HttpJsonProvider(config=config, get_json=get_json)
    candidates = provider.search(clean_query, limit=sample_limit)
    samples = [http_json_mapping_sample(candidate, index) for index, candidate in enumerate(candidates, start=1)]
    qualities = [sample["quality"] for sample in samples]
    return {
        "configured": True,
        "label": config.get("label") or "HTTP JSON",
        "query": clean_query,
        "sample_size": sample_limit,
        "summary": http_json_config_summary(config),
        "quality": local_file_mapping_quality_summary(qualities, truncated=False),
        "samples": samples,
    }


def sqlite_config(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    raw: Any = value
    if raw is None:
        raw = os.environ.get(SQLITE_CONFIG_ENV, "").strip()
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetrievalError("SQLite 配置必须是 JSON 对象。") from exc
    if not isinstance(raw, dict):
        raise RetrievalError("SQLite 配置必须是 JSON 对象。")
    config = dict(raw)
    field_map = config.get("field_map") or {}
    if not isinstance(field_map, dict):
        raise RetrievalError("SQLite field_map 必须是对象。")
    config["label"] = clean_text(config.get("label")) or "SQLite"
    config["path"] = clean_text(config.get("path"))
    config["query"] = str(config.get("query") or "").strip()
    config["field_map"] = field_map
    return config


def sqlite_config_path(config: dict[str, Any]) -> Path:
    raw_path = clean_text(config.get("path"))
    if not raw_path:
        raise RetrievalError(f"SQLite 需要配置 {SQLITE_CONFIG_ENV} 或文库偏好后使用。")
    path = Path(raw_path).expanduser()
    if not path.exists() or not path.is_file():
        raise RetrievalError(f"SQLite 需要配置有效数据库文件：{path}")
    return path


def sqlite_query(config: dict[str, Any]) -> str:
    sql = str(config.get("query") or "").strip()
    if not sql:
        raise RetrievalError("SQLite 需要配置 SELECT 查询。")
    lowered = re.sub(r"\s+", " ", sql).strip().lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise RetrievalError("SQLite 查询只允许 SELECT 或 WITH。")
    if ";" in sql.rstrip(";"):
        raise RetrievalError("SQLite 查询只允许单条 SELECT。")
    return sql.rstrip(";")


def sqlite_query_params(query: str, limit: int) -> dict[str, Any]:
    return {
        "query": query,
        "like_query": f"%{query}%",
        "limit": max(1, min(int(limit or 10), 50)),
    }


def sqlite_config_summary(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    config = sqlite_config(value)
    return {
        "configured": bool(config.get("path") and config.get("query")),
        "label": config.get("label") or "SQLite",
        "path": config.get("path") or "",
        "query": config.get("query") or "",
        "field_map": config.get("field_map") or {},
    }


def sqlite_config_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "basic-like",
            "label": "Basic LIKE",
            "description": "SQLite table with common metadata columns and LIKE search over title/abstract.",
            "config": {
                "label": "Internal SQLite",
                "path": "C:/data/retrieval.sqlite",
                "query": (
                    "SELECT id, title, year, doi, authors, abstract, keywords, url, venue, item_type "
                    "FROM items WHERE title LIKE :like_query OR abstract LIKE :like_query LIMIT :limit"
                ),
                "field_map": HTTP_JSON_TEMPLATE_FIELD_MAP,
            },
        }
    ]


def sqlite_mapped_row(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return http_json_mapped_row(row, config)


def sqlite_item_fields(row: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, str]:
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    label = clean_text(config.get("label")) or "SQLite"
    extra_values = [
        local_first_value(row, ["extra", "note", "notes"]),
        f"SQLite Source: {label}",
        f"SQLite Result: {index}",
        f"SQLite Source ID: {source_id}" if source_id else "",
    ]
    fields = {
        "title": local_first_value(row, ["title", "name", "display_name", "paper_title", "article_title"]),
        "date": local_first_value(row, ["date", "year", "publication_year", "publicationYear", "issued"]),
        "DOI": normalize_doi(local_first_value(row, ["DOI", "doi"])),
        "url": local_first_value(row, ["url", "URL", "landing_url", "link"]),
        "abstractNote": local_first_value(row, ["abstractNote", "abstract", "summary", "description"]),
        "publicationTitle": local_first_value(
            row,
            ["publicationTitle", "publication_title", "journal", "journal_name", "container_title", "venue", "venue_name", "conference", "conference_name", "source_title"],
        ),
        "publisher": local_first_value(row, ["publisher", "repository", "institution"]),
        "volume": local_first_value(row, ["volume"]),
        "issue": local_first_value(row, ["issue", "number"]),
        "pages": local_first_value(row, ["pages", "page"]),
        "extra": "\n".join(value for value in extra_values if value),
    }
    return {key: clean_text(value) for key, value in fields.items() if clean_text(value)}


def sqlite_candidate(raw_row: dict[str, Any], config: dict[str, Any], index: int, query: str) -> RetrievedCandidate | None:
    row = sqlite_mapped_row(raw_row, config)
    fields = sqlite_item_fields(row, config, index)
    identifiers = local_identifiers(row, fields)
    if not fields and not identifiers:
        return None
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    external_id = next(iter(identifiers.values()), "") or source_id or fields.get("url", "") or f"sqlite:{index}"
    evidence = ["SQLite row"]
    for key, label in {"doi": "DOI", "arxiv": "arXiv ID", "pmid": "PMID", "pmcid": "PMCID", "ads_bibcode": "ADS Bibcode", "isbn": "ISBN"}.items():
        if identifiers.get(key):
            evidence.append(label)
    item = ImportedItem(
        item_type=local_item_type(row),
        fields={key: value for key, value in fields.items() if value},
        creators=local_creators(row),
        tags=local_tags(row),
        identifiers=identifiers,
        source=clean_text(config.get("label")) or "SQLite",
    )
    return RetrievedCandidate(
        source="sqlite",
        external_id=external_id,
        item=item,
        raw={"source": clean_text(config.get("label")) or "SQLite", "result": raw_row},
        confidence=http_json_confidence(row, fields, identifiers, query),
        evidence=evidence,
        landing_url=fields.get("url", ""),
        pdf_url=local_first_value(row, ["pdf_url", "pdf", "full_text_url", "attachment_url"]),
    )


def preview_sqlite_mappings(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 2,
) -> dict[str, Any]:
    config = sqlite_config(config_value)
    clean_query = clean_text(query) or HEALTH_CHECK_QUERY
    sample_limit = max(1, min(int(sample_size or 2), 5))
    candidates = SQLiteProvider(config=config).search(clean_query, limit=sample_limit)
    samples = [http_json_mapping_sample(candidate, index) for index, candidate in enumerate(candidates, start=1)]
    qualities = [sample["quality"] for sample in samples]
    return {
        "configured": True,
        "label": config.get("label") or "SQLite",
        "query": clean_query,
        "sample_size": sample_limit,
        "summary": sqlite_config_summary(config),
        "quality": local_file_mapping_quality_summary(qualities, truncated=False),
        "samples": samples,
    }


def sqlite_sample_rows(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 3,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    config = sqlite_config(config_value)
    clean_query = clean_text(query) or HEALTH_CHECK_QUERY
    sample_limit = max(1, min(int(sample_size or 3), 10))
    path = sqlite_config_path(config)
    sql = sqlite_query(config)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=provider_timeout_seconds(SQLiteProvider(config=config))) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, sqlite_query_params(clean_query, sample_limit))
        rows = [dict(row) for row in cursor.fetchmany(sample_limit)]
        columns = [str(item[0]) for item in (cursor.description or []) if item and item[0]]
    return config, columns, rows


def suggest_sqlite_field_map(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 3,
    replace_existing: bool = True,
) -> dict[str, Any]:
    config, columns, rows = sqlite_sample_rows(config_value, query=query, sample_size=sample_size)
    suggestion = retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "sqlite",
            "config": config,
            "columns": columns,
            "samples": rows,
            "replace_existing": replace_existing,
        }
    )
    suggestion["query"] = clean_text(query) or HEALTH_CHECK_QUERY
    suggestion["sample_count"] = len(rows)
    suggestion["columns"] = columns
    return suggestion


def manifest_config(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    raw: Any = value
    if raw is None:
        raw = os.environ.get(MANIFEST_CONFIG_ENV, "").strip()
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetrievalError("Object Manifest 配置必须是 JSON 对象。") from exc
    if not isinstance(raw, dict):
        raise RetrievalError("Object Manifest 配置必须是 JSON 对象。")
    config = dict(raw)
    field_map = config.get("field_map") or {}
    headers = config.get("headers") or {}
    auth = config.get("auth") or {}
    if not isinstance(field_map, dict):
        raise RetrievalError("Object Manifest field_map 必须是对象。")
    if not isinstance(headers, dict):
        raise RetrievalError("Object Manifest headers 必须是对象。")
    if not isinstance(auth, dict):
        raise RetrievalError("Object Manifest auth 必须是对象。")
    manifest_value = clean_text(config.get("manifest") or config.get("manifest_url") or config.get("url"))
    config["manifest_url"] = manifest_value if manifest_value.lower().startswith(("http://", "https://")) else clean_text(config.get("manifest_url") or config.get("url"))
    config["manifest_path"] = clean_text(config.get("manifest_path") or config.get("path") or (manifest_value if manifest_value and not config["manifest_url"] else ""))
    config["items_path"] = clean_text(config.get("items_path"))
    config["label"] = clean_text(config.get("label")) or "Object Manifest"
    config["field_map"] = field_map
    config["headers"] = headers
    config["auth"] = auth
    return config


def manifest_source(config: dict[str, Any]) -> tuple[str, str]:
    url = clean_text(config.get("manifest_url"))
    if url:
        if not url.lower().startswith(("http://", "https://")):
            raise RetrievalError("Object Manifest manifest_url 必须是 HTTP/HTTPS URL。")
        return "url", url
    raw_path = clean_text(config.get("manifest_path"))
    if not raw_path:
        raise RetrievalError(f"Object Manifest 需要配置 {MANIFEST_CONFIG_ENV} 或文库偏好后使用。")
    path = Path(raw_path).expanduser()
    if not path.exists() or not path.is_file():
        raise RetrievalError(f"Object Manifest 需要配置有效 JSON 清单文件：{path}")
    return "path", str(path)


def manifest_payload(config: dict[str, Any], get_json: JsonFetcher | None = None) -> Any:
    source_kind, value = manifest_source(config)
    if source_kind == "url":
        if get_json is not None:
            return get_json(value)
        return _http_get_json(value, headers=http_json_headers(config))
    path = Path(value)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RetrievalError(f"Object Manifest JSON 解析失败：{path.name}: {exc}") from exc


def manifest_items(config: dict[str, Any], get_json: JsonFetcher | None = None) -> list[dict[str, Any]]:
    payload = manifest_payload(config, get_json=get_json)
    items_path = clean_text(config.get("items_path"))
    if not items_path and isinstance(payload, dict):
        for candidate_path in ("items", "objects", "results", "data.items", "data.objects", "data.records"):
            if isinstance(http_json_path_value(payload, candidate_path), list):
                config = {**config, "items_path": candidate_path}
                break
    return http_json_result_items(payload, config)


def manifest_sample_items(
    config_value: dict[str, Any] | str | None = None,
    *,
    sample_size: int = 3,
    get_json: JsonFetcher | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = manifest_config(config_value)
    sample_limit = max(1, min(int(sample_size or 3), 10))
    payload = manifest_payload(config, get_json=get_json)
    items_path = inferred_items_path(
        payload,
        clean_text(config.get("items_path")),
        ("items", "objects", "results", "data.items", "data.objects", "data.records", "data", "records"),
    )
    draft_config = {**config}
    if items_path:
        draft_config["items_path"] = items_path
    items = http_json_result_items(payload, draft_config)
    return draft_config, items[:sample_limit]


def suggest_manifest_field_map(
    config_value: dict[str, Any] | str | None = None,
    *,
    sample_size: int = 3,
    replace_existing: bool = True,
    get_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    config, items = manifest_sample_items(config_value, sample_size=sample_size, get_json=get_json)
    suggestion = retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "manifest",
            "config": config,
            "samples": items,
            "replace_existing": replace_existing,
        }
    )
    suggestion["sample_count"] = len(items)
    return suggestion


def manifest_config_summary(value: dict[str, Any] | str | None = None) -> dict[str, Any]:
    config = manifest_config(value)
    return {
        "configured": bool(config.get("manifest_path") or config.get("manifest_url")),
        "label": config.get("label") or "Object Manifest",
        "manifest_path": config.get("manifest_path") or "",
        "manifest_url": config.get("manifest_url") or "",
        "items_path": config.get("items_path") or "",
        "field_map": config.get("field_map") or {},
        "headers": sorted(str(key) for key in (config.get("headers") or {}).keys()),
        "has_headers": bool(config.get("headers")),
    }


def manifest_config_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "local-json",
            "label": "Local JSON manifest",
            "description": "Local object manifest JSON file with an items or objects array.",
            "config": {
                "label": "Object Manifest",
                "manifest_path": "C:/data/object-manifest.json",
                "items_path": "items",
                "field_map": {
                    **HTTP_JSON_TEMPLATE_FIELD_MAP,
                    "url": "object_url",
                    "pdf_url": "pdf_url",
                },
            },
        },
        {
            "id": "remote-json",
            "label": "Remote JSON manifest",
            "description": "Remote object manifest JSON URL, optionally using env-based auth headers.",
            "config": {
                "label": "Remote Object Manifest",
                "manifest_url": "https://example.test/object-manifest.json",
                "items_path": "objects",
                "auth": {"type": "bearer_env", "env": "MANIFEST_TOKEN"},
                "field_map": {
                    **HTTP_JSON_TEMPLATE_FIELD_MAP,
                    "url": "object_url",
                    "pdf_url": "pdf_url",
                },
            },
        },
    ]


def manifest_mapped_row(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return http_json_mapped_row(row, config)


def manifest_item_fields(row: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, str]:
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    label = clean_text(config.get("label")) or "Object Manifest"
    extra_values = [
        local_first_value(row, ["extra", "note", "notes"]),
        f"Object Manifest Source: {label}",
        f"Object Manifest Result: {index}",
        f"Object Manifest Source ID: {source_id}" if source_id else "",
    ]
    fields = {
        "title": local_first_value(row, ["title", "name", "display_name", "paper_title", "article_title"]),
        "date": local_first_value(row, ["date", "year", "publication_year", "publicationYear", "issued"]),
        "DOI": normalize_doi(local_first_value(row, ["DOI", "doi"])),
        "url": local_first_value(row, ["url", "URL", "landing_url", "link", "object_url"]),
        "abstractNote": local_first_value(row, ["abstractNote", "abstract", "summary", "description"]),
        "publicationTitle": local_first_value(
            row,
            ["publicationTitle", "publication_title", "journal", "journal_name", "container_title", "venue", "venue_name", "conference", "conference_name", "source_title"],
        ),
        "publisher": local_first_value(row, ["publisher", "repository", "institution", "bucket"]),
        "volume": local_first_value(row, ["volume"]),
        "issue": local_first_value(row, ["issue", "number"]),
        "pages": local_first_value(row, ["pages", "page"]),
        "extra": "\n".join(value for value in extra_values if value),
    }
    return {key: clean_text(value) for key, value in fields.items() if clean_text(value)}


def manifest_candidate(raw_row: dict[str, Any], config: dict[str, Any], index: int, query: str) -> RetrievedCandidate | None:
    row = manifest_mapped_row(raw_row, config)
    fields = manifest_item_fields(row, config, index)
    identifiers = local_identifiers(row, fields)
    if not fields and not identifiers:
        return None
    source_id = local_first_value(row, ["external_id", "source_id", "id", "key", "uuid"])
    external_id = next(iter(identifiers.values()), "") or source_id or fields.get("url", "") or f"manifest:{index}"
    evidence = ["Object manifest record"]
    for key, label in {"doi": "DOI", "arxiv": "arXiv ID", "pmid": "PMID", "pmcid": "PMCID", "ads_bibcode": "ADS Bibcode", "isbn": "ISBN"}.items():
        if identifiers.get(key):
            evidence.append(label)
    label = clean_text(config.get("label")) or "Object Manifest"
    item = ImportedItem(
        item_type=local_item_type(row),
        fields={key: value for key, value in fields.items() if value},
        creators=local_creators(row),
        tags=local_tags(row),
        identifiers=identifiers,
        source=label,
    )
    return RetrievedCandidate(
        source="manifest",
        external_id=external_id,
        item=item,
        raw={"source": label, "result": raw_row},
        confidence=http_json_confidence(row, fields, identifiers, query),
        evidence=evidence,
        landing_url=fields.get("url", ""),
        pdf_url=local_first_value(row, ["pdf_url", "pdf", "full_text_url", "attachment_url"]),
    )


def preview_manifest_mappings(
    config_value: dict[str, Any] | str | None = None,
    *,
    query: str = HEALTH_CHECK_QUERY,
    sample_size: int = 2,
    get_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    config = manifest_config(config_value)
    clean_query = clean_text(query) or HEALTH_CHECK_QUERY
    sample_limit = max(1, min(int(sample_size or 2), 5))
    candidates = ManifestProvider(config=config, get_json=get_json).search(clean_query, limit=sample_limit)
    samples = [http_json_mapping_sample(candidate, index) for index, candidate in enumerate(candidates, start=1)]
    qualities = [sample["quality"] for sample in samples]
    return {
        "configured": True,
        "label": config.get("label") or "Object Manifest",
        "query": clean_query,
        "sample_size": sample_limit,
        "summary": manifest_config_summary(config),
        "quality": local_file_mapping_quality_summary(qualities, truncated=False),
        "samples": samples,
    }


def default_provider_registry(
    local_file_paths: list[str | Path] | None = None,
    local_file_field_map: dict[str, Any] | None = None,
    http_json_config_value: dict[str, Any] | str | None = None,
    sqlite_config_value: dict[str, Any] | str | None = None,
    manifest_config_value: dict[str, Any] | str | None = None,
    github_token: str = "",
    huggingface_token: str = "",
    zenodo_token: str = "",
) -> dict[str, MetadataProvider]:
    return {
        "crossref": CrossrefProvider(),
        "arxiv": ArxivProvider(),
        "pubmed": PubMedProvider(),
        "biorxiv": BioRxivProvider(),
        "medrxiv": MedRxivProvider(),
        "openalex": OpenAlexProvider(),
        "semanticscholar": SemanticScholarProvider(),
        "datacite": DataCiteProvider(),
        "github": GitHubProvider(api_key=github_token),
        "huggingface": HuggingFaceProvider(api_key=huggingface_token),
        "zenodo": ZenodoProvider(api_key=zenodo_token),
        "openlibrary": OpenLibraryProvider(),
        "ads": ADSProvider(),
        "localfile": LocalFileProvider(paths=local_file_paths, field_map=local_file_field_map),
        "httpjson": HttpJsonProvider(config=http_json_config_value),
        "sqlite": SQLiteProvider(config=sqlite_config_value),
        "manifest": ManifestProvider(config=manifest_config_value),
    }


def source_static_status(name: str, provider: MetadataProvider, label: str) -> dict[str, Any]:
    config_key = str(getattr(provider, "api_key_env", "") or "")
    optional_config = bool(getattr(provider, "optional_api_key", False))
    requires_config = bool(config_key and not optional_config)
    custom_config_error = getattr(provider, "configuration_error", None)
    configuration_error = clean_text(custom_config_error()) if callable(custom_config_error) else ""
    custom_configured = getattr(provider, "is_configured", None)
    configured = bool(custom_configured()) if callable(custom_configured) else bool(config_key and os.environ.get(config_key, "").strip())
    if configuration_error:
        configured = False
    available = not requires_config or configured
    message = "可用" if available else configuration_error or f"需要配置 {config_key}"
    if optional_config and not configured:
        message = f"可用；可配置 {config_key} 提升限额"
    return {
        "name": name,
        "label": label,
        "available": available,
        "requires_config": requires_config,
        "config_key": config_key,
        "optional_config": optional_config,
        "configured": configured,
        "timeout_seconds": provider_timeout_seconds(provider),
        "rate_limit_seconds": source_rate_limit_seconds(name, provider),
        "rate_limit_note": str(getattr(provider, "rate_limit_note", "") or ""),
        "message": message,
        "setup": source_setup_guide(
            name,
            provider,
            config_key=config_key,
            requires_config=requires_config,
            optional_config=optional_config,
        ),
    }


def source_health_checks(
    registry: dict[str, MetadataProvider],
    statuses: list[dict[str, Any]],
    *,
    query: str = HEALTH_CHECK_QUERY,
) -> dict[str, dict[str, Any]]:
    by_name = {status["name"]: status for status in statuses}
    checks: dict[str, dict[str, Any]] = {}
    available_sources = [name for name, status in by_name.items() if status.get("available")]
    if available_sources:
        with ThreadPoolExecutor(max_workers=max(1, len(available_sources))) as executor:
            futures = {
                executor.submit(run_provider_search, source, registry[source], query, 1): source
                for source in available_sources
            }
            for future in as_completed(futures):
                source = futures[future]
                checks[source] = future.result().stats_dict()
    for source, status in by_name.items():
        if source in checks:
            continue
        checks[source] = {
            "ok": False,
            "count": 0,
            "error": status.get("message", "不可用"),
            "error_kind": "configuration",
            "action": "补齐配置后再检查该源。",
            "elapsed_ms": 0,
            "skipped": True,
        }
    return checks


def retrieval_source_statuses(
    registry: dict[str, MetadataProvider] | None = None,
    *,
    include_health: bool = False,
    health_query: str = HEALTH_CHECK_QUERY,
) -> list[dict[str, Any]]:
    provider_registry = registry or default_provider_registry()
    labels = {
        "crossref": "Crossref",
        "arxiv": "arXiv",
        "pubmed": "PubMed",
        "biorxiv": "bioRxiv",
        "medrxiv": "medRxiv",
        "openalex": "OpenAlex",
        "semanticscholar": "Semantic Scholar",
        "datacite": "DataCite",
        "github": "GitHub",
        "huggingface": "HuggingFace",
        "zenodo": "Zenodo",
        "openlibrary": "OpenLibrary",
        "ads": "NASA ADS",
        "localfile": "Local CSV/JSONL",
        "httpjson": "HTTP JSON",
        "sqlite": "SQLite",
        "manifest": "Object Manifest",
    }
    statuses = [source_static_status(name, provider, labels.get(name, name)) for name, provider in provider_registry.items()]
    if include_health:
        checks = source_health_checks(provider_registry, statuses, query=health_query)
        for status in statuses:
            health = checks.get(status["name"], {})
            status["health"] = health
            if health.get("ok"):
                status["message"] = f"可用；健康检查 {health.get('elapsed_ms', 0)}ms"
            elif health.get("skipped"):
                status["message"] = str(status.get("message") or health.get("error") or "不可用")
            else:
                status["message"] = str(health.get("action") or health.get("error") or "健康检查失败")
    return statuses


def normalize_sources(sources: Any, registry: dict[str, MetadataProvider]) -> list[str]:
    if sources is None or sources == []:
        return list(registry)
    if not isinstance(sources, list):
        raise RetrievalError("sources 必须是数组。")
    normalized = [str(source or "").strip().lower() for source in sources if str(source or "").strip()]
    unknown = [source for source in normalized if source not in registry]
    if unknown:
        raise RetrievalError(f"未知数据源：{', '.join(unknown)}")
    return normalized or list(registry)


def search_retrieval(
    query: str,
    *,
    sources: Any = None,
    limit: int = 10,
    source_limits: dict[str, Any] | None = None,
    registry: dict[str, MetadataProvider] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    clean_query = clean_text(query)
    if not clean_query:
        raise RetrievalError("检索词不能为空。")
    provider_registry = registry or default_provider_registry()
    source_names = normalize_sources(sources, provider_registry)
    per_source_limit = max(1, min(int(limit or 10), 50))

    def limit_for_source(source: str) -> int:
        if not isinstance(source_limits, dict):
            return per_source_limit
        try:
            raw_limit = source_limits.get(source, per_source_limit)
            return max(1, min(int(raw_limit or per_source_limit), 50))
        except (TypeError, ValueError):
            return per_source_limit

    resolved_limits = {source: limit_for_source(source) for source in source_names}
    cache_key = retrieval_search_cache_key(clean_query, source_names, resolved_limits, include_raw, provider_registry)
    cached_result = get_retrieval_search_cache(cache_key)
    if cached_result is not None:
        return cached_result

    results: dict[str, SourceSearchResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(source_names))) as executor:
        futures = {
            executor.submit(run_provider_search, source, provider_registry[source], clean_query, resolved_limits[source]): source
            for source in source_names
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                results[source] = future.result()
            except Exception as exc:  # noqa: BLE001 - source adapters must not break the whole search
                details = retrieval_error_details(exc)
                results[source] = SourceSearchResult(source=source, ok=False, **details)
    ordered_results = [results[source] for source in source_names]
    candidates = merge_candidates([candidate for result in ordered_results for candidate in result.candidates])
    candidate_payloads = []
    for index, candidate in enumerate(candidates, start=1):
        payload = candidate.as_dict(include_raw=include_raw)
        payload["rank"] = index
        candidate_payloads.append(payload)
    payload = {
        "query": clean_query,
        "sources": source_names,
        "candidates": candidate_payloads,
        "source_stats": {result.source: result.stats_dict() for result in ordered_results},
    }
    set_retrieval_search_cache(cache_key, payload)
    return payload
