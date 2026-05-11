#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

try:
    import gdown
    _GDOWN_OK = True
except Exception:
    _GDOWN_OK = False


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOWNLOAD_URL = "https://b.link/brcars"
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "downloads" / "brcars"
DEFAULT_EXTRACT_DIR = PROJECT_ROOT / "data" / "datasets" / "brcars"
DEFAULT_SUMMARY_FILE = PROJECT_ROOT / "data" / "datasets" / "brcars" / "brcars_summary.json"

CSV_NAMES = {"brcars196.csv", "brcars427.csv"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Automatiza download do BRCars, extração do ZIP e validação de leitura "
            "dos CSVs brcars196/brcars427."
        )
    )
    parser.add_argument("--download-url", default=DEFAULT_DOWNLOAD_URL, help="URL para download do ZIP")
    parser.add_argument(
        "--download-dir",
        default=str(DEFAULT_DOWNLOAD_DIR),
        help="Pasta para armazenar o arquivo ZIP",
    )
    parser.add_argument(
        "--extract-dir",
        default=str(DEFAULT_EXTRACT_DIR),
        help="Pasta de extração do dataset",
    )
    parser.add_argument(
        "--zip-path",
        default="",
        help="Caminho de um ZIP local já baixado (opcional)",
    )
    parser.add_argument(
        "--summary-file",
        default=str(DEFAULT_SUMMARY_FILE),
        help="Arquivo JSON de saída com sumário do dataset",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Pula etapa de download e usa --zip-path ou ZIP já existente em download-dir",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Pula extração do ZIP e tenta apenas leitura dos CSVs já presentes",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout do download em segundos",
    )
    return parser.parse_args()


def resolve_zip_path(args: argparse.Namespace, download_dir: Path) -> Path:
    if args.zip_path:
        zip_path = Path(args.zip_path).resolve()
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP informado em --zip-path não existe: {zip_path}")
        return zip_path

    zips = sorted(download_dir.glob("*.zip"))
    if zips:
        return zips[-1]

    return download_dir / "brcars_dataset.zip"


def download_file(url: str, target_file: Path, timeout: int) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", "0") or 0)
        downloaded = 0

        with target_file.open("wb") as fp:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fp.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = (downloaded / total) * 100
                    print(f"[INFO] Download: {pct:6.2f}% ({downloaded}/{total} bytes)", end="\r")

    print(" " * 80, end="\r")
    print(f"[OK] Download concluído: {target_file}")


def _extract_drive_folder_url_from_redirect(final_url: str) -> str:
    parsed = urlparse(final_url)
    if "drive.google.com/drive/folders/" in final_url:
        return final_url

    query = parse_qs(parsed.query)
    continue_url = query.get("continue", [""])[0]
    continue_url = unquote(continue_url)
    if "drive.google.com/drive/folders/" in continue_url:
        return continue_url
    return ""


def _download_from_google_drive_folder(folder_url: str, download_dir: Path) -> Path | None:
    if not _GDOWN_OK:
        raise RuntimeError(
            "gdown não está instalado para download de pasta do Google Drive. "
            "Instale com: python -m pip install gdown"
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Tentando download via Google Drive folder: {folder_url}")

    files = gdown.download_folder(
        url=folder_url,
        output=str(download_dir),
        quiet=False,
    )

    if not files:
        return None

    zip_files = [Path(p) for p in files if str(p).lower().endswith('.zip')]
    if zip_files:
        zip_files.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
        return zip_files[0]

    existing_zips = sorted(download_dir.rglob("*.zip"), key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    if existing_zips:
        return existing_zips[0]

    return None


def download_with_fallback(url: str, target_file: Path, download_dir: Path, timeout: int) -> Path | None:
    try:
        download_file(url, target_file, timeout=timeout)
        if zipfile.is_zipfile(target_file):
            return target_file
        print(
            "[WARN] O arquivo baixado não é um ZIP válido (possível página de login/HTML). "
            "Tentando fallback Google Drive."
        )
    except Exception as direct_exc:
        print(f"[WARN] Download direto falhou: {direct_exc}")

    # Tenta descobrir redirecionamento para Google Drive.
    try:
        response = requests.get(url, stream=False, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        final_url = str(response.url or "")
    except Exception as redirect_exc:
        raise RuntimeError(f"Falha ao resolver redirecionamento do link: {redirect_exc}")

    folder_url = _extract_drive_folder_url_from_redirect(final_url)
    if not folder_url:
        raise RuntimeError(
            "O link não aponta para download direto e não foi possível inferir pasta pública do Google Drive."
        )

    return _download_from_google_drive_folder(folder_url, download_dir)


def extract_zip(zip_path: Path, extract_dir: Path) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP não encontrado: {zip_path}")

    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    print(f"[OK] Extração concluída em: {extract_dir}")


def find_csv_files(search_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in search_root.rglob("*.csv"):
        if path.name.lower() in CSV_NAMES:
            found[path.name.lower()] = path
    return found


def detect_repo_snapshot_only(search_root: Path) -> bool:
    """
    Detecta quando o usuário forneceu apenas o snapshot do repositório GitHub
    (README + resources) sem os arquivos reais do dataset (CSV/imagens).
    """
    if not search_root.exists():
        return False

    # Caso comum: pasta raiz já contém README.md e resources/
    if (search_root / "README.md").exists() and (search_root / "resources").exists():
        return True

    # Caso comum: conteúdo aninhado em brcars-dataset-main/
    nested = search_root / "brcars-dataset-main"
    if nested.exists() and (nested / "README.md").exists() and (nested / "resources").exists():
        return True

    return False


def analyze_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        fields = reader.fieldnames or []

        row_count = 0
        split_counts: dict[str, int] = {}
        model_ids: set[str] = set()
        make_labels: set[str] = set()
        years: set[str] = set()

        for row in reader:
            row_count += 1

            split = str(row.get("split", "")).strip()
            if split:
                split_counts[split] = split_counts.get(split, 0) + 1

            model_id = str(row.get("model_id", "")).strip()
            if model_id:
                model_ids.add(model_id)

            make = str(row.get("make_label", "")).strip()
            if make:
                make_labels.add(make)

            year = str(row.get("year", "")).strip()
            if year:
                years.add(year)

    return {
        "path": str(path),
        "columns": fields,
        "rows": row_count,
        "distinct_model_ids": len(model_ids),
        "distinct_makes": len(make_labels),
        "years_min": min(years) if years else None,
        "years_max": max(years) if years else None,
        "split_counts": split_counts,
    }


def detect_image_layout(extract_dir: Path) -> dict[str, Any]:
    split_dirs = [p for p in extract_dir.rglob("*") if p.is_dir() and p.name in {"0", "1", "2"}]
    split_roots = sorted({str(p.parent) for p in split_dirs})
    jpg_count = sum(1 for _ in extract_dir.rglob("*.jpg"))

    return {
        "split_dirs_detected": len(split_dirs),
        "split_roots": split_roots,
        "jpg_files_detected": jpg_count,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    download_dir = Path(args.download_dir).resolve()
    extract_dir = Path(args.extract_dir).resolve()
    summary_file = Path(args.summary_file).resolve()

    if not args.skip_download:
        zip_path = resolve_zip_path(args, download_dir)
        zip_path = download_with_fallback(
            args.download_url,
            zip_path,
            download_dir=download_dir,
            timeout=args.timeout,
        ) or zip_path
    else:
        zip_path = resolve_zip_path(args, download_dir)
        if not zip_path.exists() and not args.no_extract:
            raise FileNotFoundError(
                "--skip-download foi informado, mas nenhum ZIP foi encontrado. "
                "Informe --zip-path ou mantenha o download habilitado."
            )

    extracted = False
    if not args.no_extract:
        if extract_dir.exists():
            # Mantemos idempotência: não limpa automaticamente para evitar perda acidental.
            print(f"[INFO] Pasta de extração já existe e será reutilizada: {extract_dir}")
        if zip_path.exists() and zipfile.is_zipfile(zip_path):
            extract_zip(zip_path, extract_dir)
            extracted = True
        else:
            print(
                "[WARN] ZIP ausente ou inválido após download. "
                "Seguindo com busca de CSVs em pastas já disponíveis."
            )

    csv_files = find_csv_files(extract_dir)
    if not csv_files:
        csv_files = find_csv_files(download_dir)
    if not csv_files:
        if detect_repo_snapshot_only(extract_dir):
            raise FileNotFoundError(
                "A origem fornecida contém apenas o snapshot do repositório brcars-dataset "
                "(README/resources), sem os dados do dataset. "
                "Baixe o pacote real de dados (imagens/CSV) indicado no README e execute novamente com --zip-path."
            )
        raise FileNotFoundError(
            f"Nenhum CSV esperado foi encontrado em {extract_dir} nem em {download_dir}. "
            "Esperado: brcars196.csv e/ou brcars427.csv."
        )

    csv_summary: dict[str, Any] = {}
    for csv_name in sorted(csv_files):
        csv_summary[csv_name] = analyze_csv(csv_files[csv_name])
        print(f"[OK] CSV lido: {csv_name} ({csv_summary[csv_name]['rows']} linhas)")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "download": {
            "url": args.download_url,
            "zip_path": str(zip_path),
            "skip_download": args.skip_download,
        },
        "paths": {
            "download_dir": str(download_dir),
            "extract_dir": str(extract_dir),
            "extracted": extracted,
        },
        "csv_summary": csv_summary,
        "image_layout": detect_image_layout(extract_dir),
    }

    write_json(summary_file, payload)
    print(f"[OK] Sumário salvo em: {summary_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(f"[ERRO] Falha HTTP no download (status {status}): {exc}", file=sys.stderr)
        raise SystemExit(1)
    except requests.RequestException as exc:
        print(f"[ERRO] Falha de rede no download: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except zipfile.BadZipFile:
        print("[ERRO] Arquivo baixado não é um ZIP válido.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        raise SystemExit(1)
