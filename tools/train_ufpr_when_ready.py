#!/usr/bin/env python3
"""
Dispara treino UFPR automaticamente quando dataset.yaml estiver disponível.

Uso:
  python tools/train_ufpr_when_ready.py [--profile auto|cpu|gpu] [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UFPR_YAML = PROJECT_ROOT / "data" / "datasets" / "ufpr-vesv" / "dataset.yaml"
FINETUNE_SCRIPT = PROJECT_ROOT / "tools" / "finetune_yolo.py"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def build_cmd(profile: str) -> list[str]:
    python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    return [
        python_bin,
        str(FINETUNE_SCRIPT),
        "--dataset",
        "ufpr-vesv",
        "--profile",
        profile,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa treino UFPR quando dataset estiver pronto.")
    parser.add_argument("--profile", choices=["auto", "cpu", "gpu"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra o comando final.")
    args = parser.parse_args()

    if not UFPR_YAML.exists():
        print("[NOT READY] UFPR-VeSV ainda não preparado.")
        print(f"Esperado: {UFPR_YAML}")
        print("Quando o ZIP chegar, execute:")
        python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        print(f"  {python_bin} {PROJECT_ROOT / 'tools' / 'prepare_ufpr_dataset.py'} --source CAMINHO_DO_ZIP")
        return 1

    cmd = build_cmd(args.profile)
    print("[READY] UFPR-VeSV detectado.")
    print("Comando:", " ".join(cmd))

    if args.dry_run:
        return 0

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return int(result.returncode)


if __name__ == "__main__":
    sys.exit(main())
