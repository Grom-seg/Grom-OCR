#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = PROJECT_ROOT / 'tools' / 'tesseract-portable'
ARTIFACT_CACHE_DIR = PROJECT_ROOT / 'storage' / 'artifacts'
ARTIFACT_CACHE_FILE = ARTIFACT_CACHE_DIR / 'tesseract-portable.zip'
CONFIG_FILE = PROJECT_ROOT / 'config' / 'tesseract_artifact.json'


def _print(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _validate_runtime(target_dir: Path) -> tuple[bool, str]:
    exe = target_dir / 'tesseract.exe'
    tessdata = target_dir / 'tessdata'
    if not exe.exists():
        return False, f'executavel ausente: {exe}'
    if not tessdata.exists():
        return False, f'tessdata ausente: {tessdata}'
    for required in ('eng.traineddata', 'osd.traineddata'):
        if not (tessdata / required).exists():
            return False, f'arquivo essencial ausente em tessdata: {required}'
    try:
        proc = subprocess.run(
            [str(exe), '--version'],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if proc.returncode != 0:
            return False, f'tesseract --version retornou codigo {proc.returncode}'
    except Exception as exc:
        return False, f'falha ao validar executavel: {exc}'
    return True, 'ok'


def _discover_zip_source(config: dict) -> tuple[Path | None, str | None, str | None]:
    env_path = os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_PATH', '').strip()
    if env_path:
        path = Path(env_path)
        if path.exists() and path.is_file():
            return path, None, 'env_path'

    env_url = os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_URL', '').strip()
    if env_url:
        return None, env_url, 'env_url'

    cfg_path = str(config.get('artifact_path', '') or '').strip()
    if cfg_path:
        path = Path(cfg_path)
        if path.exists() and path.is_file():
            return path, None, 'config_path'

    cfg_url = str(config.get('artifact_url', '') or '').strip()
    if cfg_url:
        return None, cfg_url, 'config_url'

    return None, None, 'none'


def _download_zip(url: str, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _print(f'[TESSERACT_BOOTSTRAP] download artefato: {url}', quiet)
    with urllib.request.urlopen(url, timeout=90) as response, output_path.open('wb') as out:
        shutil.copyfileobj(response, out)


def _extract_zip(zip_path: Path, target_dir: Path, quiet: bool = False) -> None:
    _print(f'[TESSERACT_BOOTSTRAP] extraindo artefato em: {target_dir}', quiet)
    with tempfile.TemporaryDirectory(prefix='grom_tesseract_') as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmp_dir)

        candidate_roots = [tmp_dir] + [p for p in tmp_dir.iterdir() if p.is_dir()]
        portable_root = None
        for root in candidate_roots:
            if (root / 'tesseract.exe').exists():
                portable_root = root
                break
            nested = list(root.rglob('tesseract.exe'))
            if nested:
                portable_root = nested[0].parent
                break

        if portable_root is None:
            raise RuntimeError('zip nao contem tesseract.exe em estrutura reconhecida')

        backup_dir = target_dir.with_name(target_dir.name + '.bak')
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        if target_dir.exists():
            target_dir.rename(backup_dir)

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(portable_root, target_dir)
        shutil.rmtree(backup_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Bootstrap do Tesseract portatil via artefato externo.')
    parser.add_argument('--force', action='store_true', help='Forca reinstall mesmo quando o runtime ja esta valido.')
    parser.add_argument('--quiet', action='store_true', help='Reduz logs do bootstrap.')
    args = parser.parse_args()

    quiet = bool(args.quiet)

    is_valid, reason = _validate_runtime(TARGET_DIR)
    if is_valid and not args.force:
        _print('[TESSERACT_BOOTSTRAP] runtime local valido; bootstrap nao necessario.', quiet)
        return 0

    config = _read_config()
    source_path, source_url, source_kind = _discover_zip_source(config)
    expected_sha256 = (
        os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_SHA256', '').strip()
        or str(config.get('artifact_sha256', '') or '').strip()
    )

    if source_path is None and source_url is None:
        _print(
            '[TESSERACT_BOOTSTRAP] artefato nao configurado. Defina GROM_OCR_TESSERACT_ARTIFACT_URL '
            'ou GROM_OCR_TESSERACT_ARTIFACT_PATH (ou config/tesseract_artifact.json).',
            quiet,
        )
        _print(f'[TESSERACT_BOOTSTRAP] motivo atual: {reason}', quiet)
        return 2

    try:
        if source_path:
            zip_path = source_path
            _print(f'[TESSERACT_BOOTSTRAP] usando artefato local ({source_kind}): {zip_path}', quiet)
        else:
            zip_path = ARTIFACT_CACHE_FILE
            _download_zip(source_url or '', zip_path, quiet=quiet)

        if expected_sha256:
            digest = _sha256_file(zip_path)
            if digest.lower() != expected_sha256.lower():
                raise RuntimeError(
                    f'hash sha256 divergente; esperado={expected_sha256.lower()} obtido={digest.lower()}'
                )

        _extract_zip(zip_path, TARGET_DIR, quiet=quiet)
        ok, validate_reason = _validate_runtime(TARGET_DIR)
        if not ok:
            raise RuntimeError(f'validacao pos-extracao falhou: {validate_reason}')

        _print('[TESSERACT_BOOTSTRAP] runtime pronto e validado.', quiet)
        return 0
    except Exception as exc:
        _print(f'[TESSERACT_BOOTSTRAP] falha: {exc}', quiet)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
