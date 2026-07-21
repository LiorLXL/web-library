from __future__ import annotations

import re
from typing import Any


DEFAULT_CLIENT_TIMEOUT_SECONDS = 60


def normalize_openai_base_url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if re.search(r"/chat/completions/?$", text):
        return re.sub(r"/chat/completions/?$", "", text).rstrip("/")
    if re.search(r"/v\d+/?$", text):
        return text
    return f"{text}/v1"


def missing_model_config_fields(model_config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(model_config.get("model") or "").strip():
        missing.append("model")
    if not str(model_config.get("api_key") or "").strip():
        missing.append("api_key")
    return missing


def build_client(model_config: dict[str, Any], *, timeout: int = DEFAULT_CLIENT_TIMEOUT_SECONDS) -> Any:
    missing = missing_model_config_fields(model_config)
    if missing:
        raise ValueError(f"模型 API 配置不完整，请先配置：{', '.join(missing)}。")

    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": str(model_config.get("api_key") or "").strip(),
        "timeout": timeout,
    }
    base_url = normalize_openai_base_url(model_config.get("base_url"))
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)
