#!/usr/bin/env python3
"""
Precomputa embeddings OpenCLIP para todos os modelos de veículos brasileiros.

Execução offline (uma vez):
  python tools/build_openclip_embeddings.py

Saída:
  data/models/openclip_embeddings/brcars_embeddings.npy
  data/models/openclip_embeddings/build_report.json

Requisitos:
  pip install open-clip-torch

Sem open_clip: script falha com mensagem clara (não afeta runtime do FastAPI).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "data" / "models" / "openclip_embeddings"
BRCARS_META = PROJECT_ROOT / "data" / "datasets" / "brcars" / "metadata.json"
BRAZIL_REF = PROJECT_ROOT / "data" / "datasets" / "brazilian-cars-ref" / "models.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_unique_models() -> list[dict]:
    """
    Coleta modelos únicos (marca, modelo) de fontes disponíveis.
    Prioridade: BRCars metadata > Brazilian Cars Reference.
    """
    unique: dict[tuple, dict] = {}

    # --- Fonte 1: BRCars metadata ---
    if BRCARS_META.exists():
        logger.info("Carregando modelos de BRCars metadata…")
        with open(BRCARS_META, encoding="utf-8") as fh:
            items = json.load(fh)
        for item in items:
            key = (item.get("marca", "").lower(), item.get("modelo", "").lower())
            if key not in unique:
                unique[key] = {
                    "make": item.get("marca", ""),
                    "model": item.get("modelo", ""),
                    "source": "brcars",
                }
        logger.info("BRCars: %d pares únicos (marca, modelo).", len(unique))

    # --- Fonte 2: Brazilian Cars Reference ---
    if BRAZIL_REF.exists():
        logger.info("Carregando modelos de Brazilian Cars Reference…")
        with open(BRAZIL_REF, encoding="utf-8") as fh:
            payload = json.load(fh)
        models_map = payload.get("models", {})
        for make, rows in models_map.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                nome = row.get("nome", "") if isinstance(row, dict) else ""
                if not nome:
                    continue
                key = (make.lower(), nome.lower())
                if key not in unique:
                    unique[key] = {
                        "make": make,
                        "model": nome,
                        "source": "brazilian_cars_ref",
                    }
        logger.info(
            "Total após Brazilian Cars Reference: %d pares únicos.", len(unique)
        )

    if not unique:
        logger.warning(
            "Nenhum dado de veículos encontrado. "
            "Verifique data/datasets/ — execute prepare_brazilian_cars_ref.py primeiro."
        )

    return list(unique.values())


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_embeddings(model_name: str = "ViT-B-32", pretrained: str = "openai") -> int:
    """
    Gera embeddings CLIP para todos os modelos únicos e salva em disco.
    Retorna número de embeddings gerados.
    """
    # --- Verifica dependências ---
    try:
        import open_clip  # type: ignore
        import torch  # type: ignore
    except ImportError as exc:
        logger.error(
            "Dependência não encontrada: %s. "
            "Instale com: pip install open-clip-torch",
            exc,
        )
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Dispositivo: %s", device)

    # --- Carrega modelo ---
    logger.info("Carregando OpenCLIP %s / %s…", model_name, pretrained)
    model, _, _ = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
    model = model.to(device)
    model.eval()
    tokenizer = open_clip.get_tokenizer(model_name)
    logger.info("Modelo carregado.")

    # --- Coleta modelos únicos ---
    unique_models = load_unique_models()
    if not unique_models:
        logger.error("Nenhum modelo para processar. Abortando.")
        return 0

    logger.info("Gerando embeddings para %d pares (marca, modelo)…", len(unique_models))

    # --- Gera embeddings em lotes ---
    BATCH_SIZE = 64
    embeddings: dict = {}
    start_time = time.time()

    for batch_start in range(0, len(unique_models), BATCH_SIZE):
        batch = unique_models[batch_start : batch_start + BATCH_SIZE]
        texts = [f"{item['make']} {item['model']} veículo Brasil" for item in batch]

        with torch.no_grad():
            tokens = tokenizer(texts).to(device)
            features = model.encode_text(tokens)
            features = features / (features.norm(dim=-1, keepdim=True) + 1e-8)
            vecs = features.cpu().numpy().astype(np.float32)

        for i, item in enumerate(batch):
            key = (item["make"].lower(), item["model"].lower())
            embeddings[key] = vecs[i].tolist()

        done = min(batch_start + BATCH_SIZE, len(unique_models))
        elapsed = time.time() - start_time
        logger.info(
            "  %d/%d embeddings (%.1fs)", done, len(unique_models), elapsed
        )

    # --- Salva ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "brcars_embeddings.npy"
    np.save(str(out_file), embeddings)
    logger.info("✓ Embeddings salvos: %s (%d vetores)", out_file, len(embeddings))

    # Relatório
    report = {
        "total_embeddings": len(embeddings),
        "model_name": model_name,
        "pretrained": pretrained,
        "device": device,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "output_file": str(out_file),
    }
    report_path = OUT_DIR / "build_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ Relatório: %s", report_path)

    return len(embeddings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Precomputa embeddings OpenCLIP para veículos brasileiros."
    )
    parser.add_argument("--model", default="ViT-B-32", help="Nome do modelo CLIP.")
    parser.add_argument("--pretrained", default="openai", help="Pesos pré-treinados.")
    args = parser.parse_args()

    count = build_embeddings(model_name=args.model, pretrained=args.pretrained)
    sys.exit(0 if count > 0 else 1)
