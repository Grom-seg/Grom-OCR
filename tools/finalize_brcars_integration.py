#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PREPARE_SCRIPT = PROJECT_ROOT / "tools" / "prepare_brcars_dataset.py"
SUMMARY_PATH = PROJECT_ROOT / "data" / "datasets" / "brcars" / "brcars_summary.json"
REPORT_PATH = PROJECT_ROOT / "data" / "datasets" / "brcars" / "brcars_finalize_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Finaliza integração BRCars em execução única: prepara dataset, "
            "executa testes de integração OSINT e gera relatório final."
        )
    )
    parser.add_argument(
        "--zip-path",
        required=True,
        help="Caminho do ZIP real do dataset BRCars (não snapshot do repositório).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Pula testes de validação após ingestão.",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def write_report(payload: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    python_exe = PYTHON_EXE if PYTHON_EXE.exists() else Path(sys.executable)
    zip_path = Path(args.zip_path).resolve()

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "zip_path": str(zip_path),
        "steps": [],
        "status": "failed",
    }

    if not zip_path.exists():
        report["steps"].append({
            "step": "validate_zip_path",
            "ok": False,
            "error": f"ZIP não encontrado: {zip_path}",
        })
        write_report(report)
        print(f"[ERRO] ZIP não encontrado: {zip_path}")
        print(f"[INFO] Relatório: {REPORT_PATH}")
        return 1

    # 1) Preparar BRCars
    cmd_prepare = [
        str(python_exe),
        str(PREPARE_SCRIPT),
        "--skip-download",
        "--zip-path",
        str(zip_path),
    ]
    prep = run(cmd_prepare)
    prep_ok = prep.returncode == 0
    report["steps"].append({
        "step": "prepare_brcars_dataset",
        "ok": prep_ok,
        "returncode": prep.returncode,
        "stdout_tail": prep.stdout.splitlines()[-25:],
        "stderr_tail": prep.stderr.splitlines()[-25:],
    })

    if not prep_ok:
        write_report(report)
        print("[ERRO] Falha na preparação do BRCars.")
        print(f"[INFO] Relatório: {REPORT_PATH}")
        return 1

    summary_exists = SUMMARY_PATH.exists()
    report["steps"].append({
        "step": "validate_summary",
        "ok": summary_exists,
        "path": str(SUMMARY_PATH),
    })

    if not summary_exists:
        write_report(report)
        print("[ERRO] Preparação executou, mas sumário não foi encontrado.")
        print(f"[INFO] Relatório: {REPORT_PATH}")
        return 1

    # 2) Testes de integração
    if not args.skip_tests:
        cmd_test = [
            str(python_exe),
            "-m",
            "pytest",
            "-q",
            "test_osint_datasets_integration.py",
        ]
        test = run(cmd_test)
        test_ok = test.returncode == 0
        report["steps"].append({
            "step": "run_tests",
            "ok": test_ok,
            "returncode": test.returncode,
            "stdout_tail": test.stdout.splitlines()[-25:],
            "stderr_tail": test.stderr.splitlines()[-25:],
        })
        if not test_ok:
            write_report(report)
            print("[ERRO] Preparação concluída, mas testes falharam.")
            print(f"[INFO] Relatório: {REPORT_PATH}")
            return 1

    report["status"] = "ok"
    write_report(report)

    print("[OK] Integração BRCars finalizada com sucesso.")
    print(f"[OK] Sumário: {SUMMARY_PATH}")
    print(f"[OK] Relatório: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
