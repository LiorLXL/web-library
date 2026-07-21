from __future__ import annotations

import json
from pathlib import Path

import pytest

from zotero_web_library import rag_eval_cli
from zotero_web_library.rag.evaluation import (
    EVAL_REPORT_SCHEMA,
    build_synthetic_library,
    load_json,
    render_markdown_report,
    run_evaluation_suite,
    validate_corpus,
    validate_suite,
    write_evaluation_report,
)


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "evals" / "agentic_rag" / "smoke-v1.json"
CORPUS_PATH = ROOT / "evals" / "agentic_rag" / "synthetic-corpus-v1.json"


def test_phase_zero_smoke_contract_has_twenty_valid_cases() -> None:
    suite = load_json(SUITE_PATH)
    corpus = load_json(CORPUS_PATH)

    suite_result = validate_suite(suite)
    corpus_result = validate_corpus(corpus)

    assert suite_result["case_count"] == 20
    assert corpus_result["paper_count"] == 8
    assert len({case["case_id"] for case in suite["cases"]}) == 20


def test_phase_zero_smoke_suite_runs_without_external_services(tmp_path: Path) -> None:
    library = build_synthetic_library(load_json(CORPUS_PATH), tmp_path / "synthetic-library")

    report = run_evaluation_suite(library, load_json(SUITE_PATH), target="retrieve")

    assert report["schema_version"] == EVAL_REPORT_SCHEMA
    assert report["summary"]["total_cases"] == 20
    assert report["summary"]["passed_cases"] == 20
    assert report["summary"]["failed_cases"] == 0
    assert report["summary"]["error_cases"] == 0
    assert all(case["actual"]["tool_trace"] for case in report["cases"])
    assert all("latency_ms" in case for case in report["cases"])


def test_evaluation_report_writes_json_and_markdown(tmp_path: Path) -> None:
    report = {
        "schema_version": EVAL_REPORT_SCHEMA,
        "run_id": "eval-test",
        "suite_id": "suite-test",
        "target": "retrieve",
        "started_at": "2026-07-14T00:00:00+00:00",
        "summary": {
            "duration_ms": 1.0,
            "passed_cases": 1,
            "total_cases": 1,
            "pass_rate": 1.0,
            "p95_case_latency_ms": 1.0,
        },
        "cases": [
            {
                "case_id": "case-1",
                "task_type": "factual",
                "mode": "keyword",
                "status": "passed",
                "latency_ms": 1.0,
                "actual": {"sources": [{"item_key": "PAPER1"}]},
                "checks": [],
            }
        ],
    }

    paths = write_evaluation_report(report, tmp_path, stem="baseline")

    json_payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert json_payload["run_id"] == "eval-test"
    assert "通过率：1/1 (100.0%)" in markdown
    assert "`case-1`" in render_markdown_report(report)


def test_suite_validation_rejects_duplicate_case_ids() -> None:
    suite = load_json(SUITE_PATH)
    suite["cases"][1]["case_id"] = suite["cases"][0]["case_id"]

    with pytest.raises(ValueError, match="case_id 重复"):
        validate_suite(suite)


def test_rag_eval_cli_validates_default_assets(capsys) -> None:
    exit_code = rag_eval_cli.run(
        [
            "validate",
            "--suite",
            str(SUITE_PATH),
            "--corpus",
            str(CORPUS_PATH),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["suite"]["case_count"] == 20
