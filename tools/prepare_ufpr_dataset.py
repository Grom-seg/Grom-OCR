#!/usr/bin/env python3
"""
Prepara o dataset UFPR-VeSV para fine-tuning YOLOv8.

UFPR-VeSV (Vehicle Segmentation and Viewpoint):
  - Imagens de veículos com anotações de segmentação/bounding box
  - Categorias: car, motorcycle, bus, truck
  - Formato original: Pascal VOC XML → convertido para YOLO txt

Uso:
  python tools/prepare_ufpr_dataset.py [--source DIR_OU_ZIP] [--check-only]

Sem --source: tenta baixar via URL pública conhecida (fallback: instrução manual).

Saída:
  data/datasets/ufpr-vesv/
    images/train/   images/val/   images/test/
    labels/train/   labels/val/   labels/test/
    dataset.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "datasets" / "ufpr-vesv"

# Categorias UFPR-VeSV mapeadas para índices YOLO
CATEGORY_MAP: Dict[str, int] = {
    "car": 0,
    "carro": 0,
    "motorcycle": 1,
    "moto": 1,
    "bus": 2,
    "onibus": 2,
    "truck": 3,
    "caminhao": 3,
    "van": 4,
    "pickup": 5,
    "vehicle": 0,  # fallback genérico → car
    "veiculo": 0,
}

YAML_TEMPLATE = """\
# UFPR-VeSV — Dataset de veículos brasileiros para YOLOv8
# Gerado por tools/prepare_ufpr_dataset.py
path: {path}
train: images/train
val: images/val
test: images/test

nc: {nc}
names:
{names_yaml}
"""


# ---------------------------------------------------------------------------
# Conversão Pascal VOC → YOLO
# ---------------------------------------------------------------------------

def voc_to_yolo(xml_path: Path, img_w: int, img_h: int) -> List[str]:
    """
    Converte anotação Pascal VOC XML para linhas YOLO txt.
    Formato YOLO: class_id cx cy w h  (normalizado 0-1)
    """
    lines: List[str] = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        size = root.find("size")
        if size is not None:
            img_w = int(size.findtext("width") or img_w)
            img_h = int(size.findtext("height") or img_h)

        for obj in root.findall("object"):
            name = (obj.findtext("name") or "").lower().strip()
            class_id = CATEGORY_MAP.get(name)
            if class_id is None:
                # Tenta match parcial
                for key, cid in CATEGORY_MAP.items():
                    if key in name or name in key:
                        class_id = cid
                        break
            if class_id is None:
                logger.debug("Categoria desconhecida: %s — ignorando.", name)
                continue

            bndbox = obj.find("bndbox")
            if bndbox is None:
                continue

            xmin = float(bndbox.findtext("xmin") or 0)
            ymin = float(bndbox.findtext("ymin") or 0)
            xmax = float(bndbox.findtext("xmax") or img_w)
            ymax = float(bndbox.findtext("ymax") or img_h)

            cx = ((xmin + xmax) / 2) / img_w
            cy = ((ymin + ymax) / 2) / img_h
            bw = (xmax - xmin) / img_w
            bh = (ymax - ymin) / img_h

            # Clamp para [0, 1]
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))
            bw = max(0.0, min(1.0, bw))
            bh = max(0.0, min(1.0, bh))

            lines.append(f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    except Exception as exc:
        logger.warning("Erro ao converter %s: %s", xml_path, exc)
    return lines


# ---------------------------------------------------------------------------
# Extração de ZIP
# ---------------------------------------------------------------------------

def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extrai ZIP e retorna diretório raiz dos conteúdos."""
    logger.info("Extraindo %s → %s …", zip_path.name, dest)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    # Detecta subdiretório raiz
    children = [c for c in dest.iterdir() if c.is_dir()]
    if len(children) == 1:
        return children[0]
    return dest


# ---------------------------------------------------------------------------
# Estrutura UFPR-VeSV
# ---------------------------------------------------------------------------

def find_image_annotation_pairs(source_dir: Path) -> List[Tuple[Path, Optional[Path]]]:
    """
    Varre source_dir recursivamente buscando pares (imagem, xml).
    """
    pairs: List[Tuple[Path, Optional[Path]]] = []
    image_exts = {".jpg", ".jpeg", ".png", ".bmp"}

    for img_path in sorted(source_dir.rglob("*")):
        if img_path.suffix.lower() not in image_exts:
            continue
        # Tenta encontrar XML com mesmo stem na mesma pasta ou em "Annotations/"
        xml_candidates = [
            img_path.with_suffix(".xml"),
            img_path.parent.parent / "Annotations" / img_path.with_suffix(".xml").name,
            img_path.parent / "annotations" / img_path.with_suffix(".xml").name,
        ]
        xml_path = next((p for p in xml_candidates if p.exists()), None)
        pairs.append((img_path, xml_path))

    return pairs


def organize_dataset(source_dir: Path, out_dir: Path, val_ratio: float = 0.15, test_ratio: float = 0.10) -> dict:
    """
    Organiza pares (imagem, xml) em splits train/val/test no formato YOLO.
    Retorna estatísticas.
    """
    pairs = find_image_annotation_pairs(source_dir)
    if not pairs:
        logger.error("Nenhuma imagem encontrada em %s", source_dir)
        return {"total": 0, "train": 0, "val": 0, "test": 0, "errors": 0}

    logger.info("Encontrados %d pares (imagem, anotação).", len(pairs))

    total = len(pairs)
    n_test = max(1, int(total * test_ratio))
    n_val = max(1, int(total * val_ratio))
    n_train = total - n_test - n_val

    splits = (
        [("train", pairs[:n_train])]
        + [("val", pairs[n_train: n_train + n_val])]
        + [("test", pairs[n_train + n_val:])]
    )

    stats = {"total": total, "train": 0, "val": 0, "test": 0, "errors": 0}

    for split_name, split_pairs in splits:
        img_dir = out_dir / "images" / split_name
        lbl_dir = out_dir / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        for img_path, xml_path in split_pairs:
            # Copia imagem
            dest_img = img_dir / img_path.name
            shutil.copy2(img_path, dest_img)

            # Converte anotação
            dest_lbl = lbl_dir / (img_path.stem + ".txt")
            if xml_path and xml_path.exists():
                lines = voc_to_yolo(xml_path, img_w=1280, img_h=720)
                dest_lbl.write_text("\n".join(lines), encoding="utf-8")
            else:
                dest_lbl.write_text("", encoding="utf-8")

            stats[split_name] += 1  # type: ignore

    return stats


def create_dataset_yaml(out_dir: Path, stats: dict) -> Path:
    """Gera dataset.yaml para YOLOv8."""
    categories = sorted(set(CATEGORY_MAP.values()))
    id_to_name = {v: k for k, v in CATEGORY_MAP.items() if v in categories}
    # Usa nomes mais limpos (inglês)
    clean_names = {0: "car", 1: "motorcycle", 2: "bus", 3: "truck", 4: "van", 5: "pickup"}

    names_yaml = "\n".join(
        f"  {i}: {clean_names.get(i, f'class_{i}')}"
        for i in sorted(set(CATEGORY_MAP.values()))
    )

    yaml_content = YAML_TEMPLATE.format(
        path=out_dir.as_posix(),
        nc=len(set(CATEGORY_MAP.values())),
        names_yaml=names_yaml,
    )

    yaml_path = out_dir / "dataset.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    logger.info("✓ dataset.yaml criado: %s", yaml_path)
    return yaml_path


# ---------------------------------------------------------------------------
# Download (tentativa com URL conhecida)
# ---------------------------------------------------------------------------

def try_download_ufpr(dest: Path) -> Optional[Path]:
    """
    Tenta baixar UFPR-VeSV de fontes conhecidas.
    O dataset é de acesso controlado — instrução manual fornecida se falhar.
    """
    # URLs a tentar (substituir por link oficial quando disponível)
    CANDIDATE_URLS = [
        # "https://web.inf.ufpr.br/vri/databases/ufpr-vesv/ufpr-vesv.zip",  # URL oficial (acesso controlado)
    ]

    try:
        import urllib.request
        for url in CANDIDATE_URLS:
            zip_path = dest / "ufpr-vesv.zip"
            logger.info("Tentando download: %s", url)
            try:
                urllib.request.urlretrieve(url, zip_path)
                if zip_path.exists() and zip_path.stat().st_size > 10_000:
                    return zip_path
            except Exception as exc:
                logger.debug("Falha em %s: %s", url, exc)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepara UFPR-VeSV para fine-tuning YOLOv8."
    )
    parser.add_argument(
        "--source",
        help="Caminho para ZIP ou diretório já extraído do UFPR-VeSV.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verifica se dataset já está preparado (não faz nada).",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Fração para validação (padrão: 0.15).",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.10,
        help="Fração para teste (padrão: 0.10).",
    )
    args = parser.parse_args()

    yaml_path = OUT_DIR / "dataset.yaml"

    # ── Check only ──────────────────────────────────────────────────────
    if args.check_only:
        if yaml_path.exists():
            logger.info("✓ UFPR-VeSV preparado: %s", yaml_path)
            # Conta imagens
            n_train = len(list((OUT_DIR / "images" / "train").glob("*"))) if (OUT_DIR / "images" / "train").exists() else 0
            n_val = len(list((OUT_DIR / "images" / "val").glob("*"))) if (OUT_DIR / "images" / "val").exists() else 0
            logger.info("  train: %d  val: %d", n_train, n_val)
            return 0
        else:
            logger.warning("UFPR-VeSV NÃO preparado. Execute sem --check-only.")
            return 1

    # ── Resolve source ───────────────────────────────────────────────────
    source_path = Path(args.source) if args.source else None

    if source_path is None:
        # Tenta download automático
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = try_download_ufpr(OUT_DIR)
        if downloaded:
            source_path = downloaded
        else:
            logger.warning(
                "Download automático não disponível (dataset de acesso controlado).\n"
                "\n"
                "Para obter o UFPR-VeSV:\n"
                "  1. Acesse: https://web.inf.ufpr.br/vri/databases/ufpr-vesv/\n"
                "  2. Preencha o formulário de acesso\n"
                "  3. Faça download do ZIP\n"
                "  4. Execute:\n"
                "     python tools/prepare_ufpr_dataset.py --source CAMINHO_DO_ZIP\n"
                "\n"
                "Alternativamente, use o dataset stub para testar o pipeline:\n"
                "     python tools/finetune_yolo.py --stub\n"
            )
            return 1

    # ── Extrai se ZIP ─────────────────────────────────────────────────────
    extract_dir = OUT_DIR / "_raw"
    if source_path.suffix.lower() == ".zip":
        extract_dir.mkdir(parents=True, exist_ok=True)
        source_dir = extract_zip(source_path, extract_dir)
    elif source_path.is_dir():
        source_dir = source_path
    else:
        logger.error("--source deve ser um arquivo ZIP ou diretório: %s", source_path)
        return 1

    # ── Organiza dataset ──────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = organize_dataset(source_dir, OUT_DIR, args.val_ratio, args.test_ratio)

    if stats["total"] == 0:
        logger.error("Nenhuma imagem processada. Verifique a estrutura do diretório fonte.")
        return 1

    # ── dataset.yaml ──────────────────────────────────────────────────────
    create_dataset_yaml(OUT_DIR, stats)

    # ── Relatório ─────────────────────────────────────────────────────────
    report_path = OUT_DIR / "prepare_report.json"
    report_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "✓ UFPR-VeSV preparado: %d imagens (train=%d, val=%d, test=%d, erros=%d)",
        stats["total"],
        stats["train"],
        stats["val"],
        stats["test"],
        stats["errors"],
    )
    logger.info("  Próximo passo: python tools/finetune_yolo.py --dataset ufpr-vesv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
