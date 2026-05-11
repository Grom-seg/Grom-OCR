#!/usr/bin/env python3
"""
Fine-tune YOLOv8 com datasets brasileiros de veículos.

Suporte a:
  - UFPR-VeSV (estrutura YOLO nativa)
  - BRCars (quando disponível e convertido)
  - Placeholder stub para execução sem dataset (valida o pipeline)

Uso:
  python tools/finetune_yolo.py [--dataset NOME] [--epochs N] [--device CPU|0]
  python tools/finetune_yolo.py --check-only   # valida ambiente sem treinar

Saída:
  runs/detect/yolo_brcars_v1/weights/best.pt
  data/models/yolo_brcars_v1.pt   (cópia do melhor checkpoint)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATASETS_DIR = DATA_DIR / "datasets"
MODELS_DIR = DATA_DIR / "models"
RUNS_DIR = PROJECT_ROOT / "runs" / "detect"

DEFAULT_BASE_MODEL = str(PROJECT_ROOT / "yolov8n.pt")

PROFILE_DEFAULTS = {
    "cpu": {"epochs": 20, "imgsz": 512, "batch": 4, "patience": 5, "device": "cpu"},
    "gpu": {"epochs": 50, "imgsz": 640, "batch": 16, "patience": 10, "device": "0"},
}


# ---------------------------------------------------------------------------
# Verificação de ambiente
# ---------------------------------------------------------------------------

def check_environment() -> dict:
    """Verifica dependências e disponibilidade de datasets."""
    report: dict = {
        "ultralytics": False,
        "torch": False,
        "gpu_available": False,
        "base_model": False,
        "ufpr_vesv": False,
        "brcars": False,
        "ready_to_train": False,
        "messages": [],
    }

    # ultralytics
    try:
        from ultralytics import YOLO  # type: ignore
        report["ultralytics"] = True
    except ImportError:
        report["messages"].append("ultralytics não instalado — execute: pip install ultralytics")

    # torch
    try:
        import torch  # type: ignore
        report["torch"] = True
        report["gpu_available"] = torch.cuda.is_available()
        if report["gpu_available"]:
            report["messages"].append(f"GPU disponível: {torch.cuda.get_device_name(0)}")
        else:
            report["messages"].append("GPU não disponível — treinamento em CPU (lento).")
    except ImportError:
        report["messages"].append("torch não instalado.")

    # base model
    base = Path(DEFAULT_BASE_MODEL)
    if base.exists():
        report["base_model"] = True
    else:
        report["messages"].append(f"Modelo base não encontrado: {base}")

    # UFPR-VeSV
    ufpr_yaml = DATASETS_DIR / "ufpr-vesv" / "dataset.yaml"
    if ufpr_yaml.exists():
        report["ufpr_vesv"] = True
    else:
        report["messages"].append(
            f"UFPR-VeSV não encontrado em {ufpr_yaml}. "
            "Use tools/prepare_ufpr_dataset.py para baixar e preparar."
        )

    # BRCars
    brcars_yaml = DATASETS_DIR / "brcars" / "dataset.yaml"
    brcars_meta = DATASETS_DIR / "brcars" / "metadata.json"
    if brcars_yaml.exists() and brcars_meta.exists():
        report["brcars"] = True
    else:
        report["messages"].append(
            "BRCars dataset.yaml não encontrado. "
            "Aguardando ZIP autorizado → use tools/finalize_brcars_integration.py."
        )

    report["ready_to_train"] = (
        report["ultralytics"]
        and report["torch"]
        and report["base_model"]
        and (report["ufpr_vesv"] or report["brcars"])
    )

    return report


# ---------------------------------------------------------------------------
# Geração de dataset.yaml stub (para testes de pipeline)
# ---------------------------------------------------------------------------

def create_stub_dataset(out_dir: Path) -> Path:
    """
    Cria dataset stub mínimo para validar o pipeline de treinamento sem dados reais.
    Usa imagens de teste já presentes no projeto.
    """
    stub_dir = out_dir / "stub_dataset"
    for split in ("images/train", "images/val", "labels/train", "labels/val"):
        (stub_dir / split).mkdir(parents=True, exist_ok=True)

    # Copia imagens de teste disponíveis no projeto
    test_assets = PROJECT_ROOT / "test-assets"
    images_found = []
    if test_assets.exists():
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            images_found.extend(list(test_assets.rglob(ext))[:5])

    for i, img_path in enumerate(images_found[:4]):
        # Garante ao menos 1 imagem em val mesmo com poucas imagens
        total = min(len(images_found), 4)
        dest_split = "val" if i == total - 1 else "train"
        shutil.copy(img_path, stub_dir / f"images/{dest_split}/{img_path.name}")
        # Label vazio (sem objetos — só para validar o loop)
        lbl = stub_dir / f"labels/{dest_split}/{img_path.stem}.txt"
        lbl.write_text("")

    # dataset.yaml
    yaml_path = stub_dir / "dataset.yaml"
    yaml_path.write_text(
        f"""# STUB: dataset mínimo para validar pipeline de fine-tuning
path: {stub_dir.as_posix()}
train: images/train
val: images/val

nc: 1
names:
  - veiculo
""",
        encoding="utf-8",
    )

    logger.info("Stub dataset criado em %s (%d imagens).", stub_dir, len(images_found))
    return yaml_path


# ---------------------------------------------------------------------------
# Fine-tuning
# ---------------------------------------------------------------------------

def run_finetune(
    dataset_yaml: Path,
    base_model: str = DEFAULT_BASE_MODEL,
    epochs: int = 50,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "0",
    run_name: str = "yolo_brcars_v1",
    patience: int = 10,
) -> Optional[Path]:
    """
    Executa fine-tuning YOLOv8.
    Retorna caminho do melhor checkpoint ou None em caso de falha.
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        logger.error("ultralytics não instalado. Execute: pip install ultralytics")
        return None

    logger.info("=== Fine-tuning YOLOv8 ===")
    logger.info("  Base model  : %s", base_model)
    logger.info("  Dataset     : %s", dataset_yaml)
    logger.info("  Epochs      : %d", epochs)
    logger.info("  Image size  : %d", imgsz)
    logger.info("  Batch       : %d", batch)
    logger.info("  Device      : %s", device)

    model = YOLO(base_model)
    results = model.train(
        data=str(dataset_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        patience=patience,
        save=True,
        project=str(RUNS_DIR),
        name=run_name,
        exist_ok=True,
    )

    # Localiza best.pt
    best_pt = RUNS_DIR / run_name / "weights" / "best.pt"
    if not best_pt.exists():
        logger.warning("best.pt não encontrado em %s", best_pt)
        return None

    # Copia para data/models/
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / f"{run_name}.pt"
    shutil.copy(best_pt, dest)
    logger.info("✓ Modelo salvo em: %s", dest)

    # Salva relatório de treinamento
    report = {
        "run_name": run_name,
        "base_model": base_model,
        "dataset": str(dataset_yaml),
        "epochs_requested": epochs,
        "output_model": str(dest),
    }
    report_path = MODELS_DIR / f"{run_name}_training_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ Relatório: %s", report_path)

    return dest


def resolve_training_params(args: argparse.Namespace, env_report: dict) -> dict:
    """Resolve parâmetros finais de treino combinando perfil e overrides do CLI."""
    profile = args.profile
    if profile == "auto":
        profile = "gpu" if env_report.get("gpu_available") else "cpu"

    defaults = PROFILE_DEFAULTS[profile].copy()
    return {
        "epochs": args.epochs if args.epochs is not None else defaults["epochs"],
        "imgsz": args.imgsz if args.imgsz is not None else defaults["imgsz"],
        "batch": args.batch if args.batch is not None else defaults["batch"],
        "patience": args.patience if args.patience is not None else defaults["patience"],
        "device": args.device if args.device is not None else defaults["device"],
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv8 com datasets brasileiros de veículos."
    )
    parser.add_argument(
        "--dataset",
        choices=["ufpr-vesv", "brcars", "stub"],
        default="ufpr-vesv",
        help="Dataset para usar no fine-tuning (padrão: ufpr-vesv).",
    )
    parser.add_argument(
        "--profile",
        choices=["auto", "cpu", "gpu"],
        default="auto",
        help="Preset de treino. 'auto' escolhe gpu se disponível, senão cpu.",
    )
    parser.add_argument("--epochs", type=int, default=None, help="Override de epochs do perfil.")
    parser.add_argument("--imgsz", type=int, default=None, help="Override de tamanho de imagem do perfil.")
    parser.add_argument("--batch", type=int, default=None, help="Override de batch do perfil.")
    parser.add_argument("--patience", type=int, default=None, help="Override de patience do perfil.")
    parser.add_argument("--device", default=None, help="Override de device ('cpu' ou índice da GPU, ex: 0).")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Apenas verifica o ambiente sem treinar.",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Usa dataset stub mínimo (para testar pipeline sem dados reais).",
    )

    args = parser.parse_args()

    # ── Verificação de ambiente ──────────────────────────────────────────
    report = check_environment()
    print("\n=== Verificação de ambiente ===")
    print(f"  ultralytics     : {'OK' if report['ultralytics'] else 'FALTA'}")
    print(f"  torch           : {'OK' if report['torch'] else 'FALTA'}")
    print(f"  GPU disponível  : {'Sim' if report['gpu_available'] else 'Não (CPU)'}")
    print(f"  Modelo base     : {'OK' if report['base_model'] else 'FALTA'}")
    print(f"  UFPR-VeSV       : {'OK' if report['ufpr_vesv'] else 'não encontrado'}")
    print(f"  BRCars dataset  : {'OK' if report['brcars'] else 'aguardando'}")
    print(f"  Pronto p/ treino: {'SIM' if report['ready_to_train'] else 'NÃO'}")
    for msg in report["messages"]:
        print(f"    • {msg}")
    print()

    if args.check_only:
        return 0 if report["ready_to_train"] else 1

    # ── Determina dataset.yaml ───────────────────────────────────────────
    if args.stub or args.dataset == "stub":
        dataset_yaml = create_stub_dataset(DATA_DIR / "datasets")
    elif args.dataset == "ufpr-vesv":
        dataset_yaml = DATASETS_DIR / "ufpr-vesv" / "dataset.yaml"
        if not dataset_yaml.exists():
            logger.error(
                "UFPR-VeSV não encontrado. Use --stub para testar o pipeline, "
                "ou prepare o dataset com tools/prepare_ufpr_dataset.py."
            )
            return 1
    elif args.dataset == "brcars":
        dataset_yaml = DATASETS_DIR / "brcars" / "dataset.yaml"
        if not dataset_yaml.exists():
            logger.error(
                "BRCars dataset.yaml não encontrado. "
                "Aguardando ZIP → use tools/finalize_brcars_integration.py."
            )
            return 1
    else:
        logger.error("Dataset desconhecido: %s", args.dataset)
        return 1

    # ── Treinamento ──────────────────────────────────────────────────────
    resolved = resolve_training_params(args, report)
    logger.info(
        "Perfil aplicado: %s (epochs=%s imgsz=%s batch=%s patience=%s device=%s)",
        resolved["profile"],
        resolved["epochs"],
        resolved["imgsz"],
        resolved["batch"],
        resolved["patience"],
        resolved["device"],
    )

    result = run_finetune(
        dataset_yaml=dataset_yaml,
        epochs=resolved["epochs"],
        imgsz=resolved["imgsz"],
        batch=resolved["batch"],
        patience=resolved["patience"],
        device=resolved["device"],
        run_name="yolo_brcars_v1",
    )

    if result:
        logger.info("✓ Fine-tuning concluído: %s", result)
        return 0
    else:
        logger.error("Fine-tuning falhou.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
