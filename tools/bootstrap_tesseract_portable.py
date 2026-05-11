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


def _collect_zip_sources(config: dict) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []

    env_url = os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_URL', '').strip()
    if env_url:
        sources.append({'kind': 'url', 'value': env_url, 'source': 'env_url'})

    env_path = os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_PATH', '').strip()
    if env_path:
        path = Path(env_path)
        if path.exists() and path.is_file():
            sources.append({'kind': 'path', 'value': path, 'source': 'env_path'})

    cfg_url = str(config.get('artifact_url', '') or '').strip()
    if cfg_url:
        sources.append({'kind': 'url', 'value': cfg_url, 'source': 'config_url'})

    cfg_path = str(config.get('artifact_path', '') or '').strip()
    if cfg_path:
        path = Path(cfg_path)
        if path.exists() and path.is_file():
            sources.append({'kind': 'path', 'value': path, 'source': 'config_path'})

    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in sources:
        key = (str(item['kind']), str(item['value']))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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
    sources = _collect_zip_sources(config)
    expected_sha256 = (
        os.environ.get('GROM_OCR_TESSERACT_ARTIFACT_SHA256', '').strip()
        or str(config.get('artifact_sha256', '') or '').strip()
    )

    if not sources:
        _print(
            '[TESSERACT_BOOTSTRAP] artefato nao configurado. Defina GROM_OCR_TESSERACT_ARTIFACT_URL '
            'ou GROM_OCR_TESSERACT_ARTIFACT_PATH (ou config/tesseract_artifact.json).',
            quiet,
        )
        _print(f'[TESSERACT_BOOTSTRAP] motivo atual: {reason}', quiet)
        return 2

    failures: list[str] = []
    for source in sources:
        try:
            if source['kind'] == 'path':
                zip_path = Path(str(source['value']))
                _print(f'[TESSERACT_BOOTSTRAP] usando artefato local ({source["source"]}): {zip_path}', quiet)
            else:
                zip_path = ARTIFACT_CACHE_FILE
                _download_zip(str(source['value']), zip_path, quiet=quiet)

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

            _print(f'[TESSERACT_BOOTSTRAP] runtime pronto e validado via {source["source"]}.', quiet)
            return 0
        except Exception as exc:
            failures.append(f'{source["source"]}: {exc}')
            _print(f'[TESSERACT_BOOTSTRAP] fonte {source["source"]} falhou: {exc}', quiet)

    _print('[TESSERACT_BOOTSTRAP] todas as fontes falharam.', quiet)
    for item in failures:
        _print(f'[TESSERACT_BOOTSTRAP] detalhe: {item}', quiet)
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
