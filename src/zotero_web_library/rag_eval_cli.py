from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import app_store
from .rag.evaluation import (
    build_synthetic_library,
    load_json,
    run_evaluation_suite,
    validate_corpus,
    validate_suite,
    write_evaluation_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic RAG 离线评测工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="校验评测集和可选合成语料")
    validate.add_argument("--suite", required=True)
    validate.add_argument("--corpus", default="")
    validate.set_defaults(func=command_validate)

    run_parser = subparsers.add_parser("run", help="运行离线评测并生成 JSON/Markdown 报告")
    run_parser.add_argument("--suite", required=True)
    source = run_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic-corpus", default="")
    source.add_argument("--library-id", default="")
    run_parser.add_argument("--target", choices=["retrieve", "agent"], default="retrieve")
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--report-stem", default="")
    run_parser.add_argument("--model", default="")
    run_parser.add_argument("--base-url", default="")
    run_parser.add_argument("--api-key", default="")
    run_parser.add_argument("--allow-failures", action="store_true")
    run_parser.set_defaults(func=command_run)
    return parser


def command_validate(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    suite_result = validate_suite(load_json(args.suite))
    payload: dict[str, Any] = {"ok": True, "suite": suite_result}
    if args.corpus:
        payload["corpus"] = validate_corpus(load_json(args.corpus))
    return 0, payload


def command_run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    suite = load_json(args.suite)
    validate_suite(suite)
    model_config = None
    if args.target == "agent":
        model_config = {
            "model": str(args.model or os.environ.get("RAG_EVAL_MODEL") or "").strip(),
            "base_url": str(args.base_url or os.environ.get("RAG_EVAL_BASE_URL") or "").strip(),
            "api_key": str(args.api_key or os.environ.get("RAG_EVAL_API_KEY") or "").strip(),
        }
        missing = [key for key in ("model", "api_key") if not model_config[key]]
        if missing:
            raise ValueError(f"Agent 评测缺少配置：{', '.join(missing)}")

    if args.synthetic_corpus:
        corpus = load_json(args.synthetic_corpus)
        validate_corpus(corpus)
        with tempfile.TemporaryDirectory(prefix="agentic-rag-eval-", ignore_cleanup_errors=True) as temp_dir:
            library = build_synthetic_library(corpus, temp_dir)
            report = run_evaluation_suite(library, suite, target=args.target, model_config=model_config)
            # sqlite3 context managers commit/rollback but do not close the
            # connection object themselves. Force finalizers before Windows
            # attempts to remove the temporary rag.sqlite file.
            gc.collect()
    else:
        app_store.ensure_app_store()
        library = app_store.get_library(str(args.library_id or "").strip())
        if not library:
            raise ValueError("文库不存在。")
        report = run_evaluation_suite(library, suite, target=args.target, model_config=model_config)

    paths = write_evaluation_report(report, args.output_dir, stem=str(args.report_stem or ""))
    summary = report["summary"]
    ok = not summary["failed_cases"] and not summary["error_cases"]
    code = 0 if ok or args.allow_failures else 2
    return code, {"ok": ok, "report": paths, "summary": summary, "run_id": report["run_id"]}


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code, payload = args.func(args)
    except Exception as exc:  # noqa: BLE001
        code, payload = 1, {"ok": False, "error": str(exc), "command": args.command}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
