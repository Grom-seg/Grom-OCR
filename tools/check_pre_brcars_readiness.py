#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "datasets" / "brcars" / "pre_brcars_readiness_report.json"
DEFAULT_TEST_FILES = [
    "test_osint_datasets_integration.py",
    "test_datasets_status_endpoint.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Checklist operacional antes do ZIP real da BRCars. "
            "Valida referência brasileira, dependências e testes de integração."
        )
    )
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help="Arquivo JSON de saída com relatório de prontidão.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Pula execução dos testes de integração.",
    )
    return parser.parse_args()


def _safe_import_datasets_status() -> tuple[dict[str, Any], str]:
    try:
        project_root_str = str(PROJECT_ROOT)
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)

        from fastapi_backend.datasets_loader import datasets_status  # pylint: disable=import-outside-toplevel

        status = datasets_status()
        if not isinstance(status, dict):
            return {}, "datasets_status_invalid"
        return status, "ok"
    except Exception as exc:
        return {}, f"import_error: {exc}"


def _check_dependencies() -> dict[str, bool]:
    deps = {}
    for mod in ("fastapi", "pytest"):
        try:
            __import__(mod)
            deps[mod] = True
        except Exception:
            deps[mod] = False
    return deps


def _run_tests(python_exe: Path, test_files: list[str]) -> dict[str, Any]:
    cmd = [str(python_exe), "-m", "pytest", "-q", *test_files]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": cmd,
        "stdout_tail": result.stdout.splitlines()[-40:],
        "stderr_tail": result.stderr.splitlines()[-40:],
    }


def _classify_readiness(
    datasets: dict[str, Any],
    deps: dict[str, bool],
    tests: dict[str, Any] | None,
) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    pending: list[str] = []

    if not bool(datasets.get("brazilian_cars_ref", {}).get("available", False)):
        blockers.append("brazilian_cars_ref_missing")

    if not bool(deps.get("fastapi", False)):
        blockers.append("fastapi_not_installed")
    if not bool(deps.get("pytest", False)):
        blockers.append("pytest_not_installed")

    if tests is not None and not bool(tests.get("ok", False)):
        blockers.append("integration_tests_failed")

    if not bool(datasets.get("brcars_summary", {}).get("available", False)):
        pending.append("brcars_summary_missing_expected_until_authorized_zip")

    if blockers:
        return "blocked", blockers, pending
    if pending:
        return "ready_waiting_brcars", blockers, pending
    return "fully_ready", blockers, pending


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path).resolve()
    python_exe = Path(sys.executable).resolve()

    datasets, datasets_note = _safe_import_datasets_status()
    dependencies = _check_dependencies()

    tests_result = None
    if not args.skip_tests:
        tests_result = _run_tests(python_exe, DEFAULT_TEST_FILES)

    readiness, blockers, pending = _classify_readiness(datasets, dependencies, tests_result)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_executable": str(python_exe),
        "datasets_status_import": datasets_note,
        "datasets": datasets,
        "dependencies": dependencies,
        "tests": tests_result,
        "readiness": readiness,
        "blockers": blockers,
        "pending": pending,
        "next_command_when_zip_arrives": (
            "c:/Grom_OCR/.venv/Scripts/python.exe "
            "c:/Grom_OCR/tools/finalize_brcars_integration.py --zip-path \"CAMINHO_DO_ZIP_REAL\""
        ),
    }

    _write_json(report_path, report)

    print(f"[INFO] Relatório salvo em: {report_path}")
    print(f"[INFO] Readiness: {readiness}")
    if blockers:
        print(f"[WARN] Blockers: {', '.join(blockers)}")
    if pending:
        print(f"[INFO] Pendências esperadas: {', '.join(pending)}")

    return 0 if readiness in {"ready_waiting_brcars", "fully_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
