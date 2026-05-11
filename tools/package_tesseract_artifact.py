#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / 'tools' / 'tesseract-portable'
DIST_DIR = PROJECT_ROOT / 'dist'
DEFAULT_ZIP = DIST_DIR / 'tesseract-portable-win64.zip'
DEFAULT_MANIFEST = DIST_DIR / 'tesseract-portable-manifest.json'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_dir(source_dir: Path) -> None:
    exe = source_dir / 'tesseract.exe'
    tessdata = source_dir / 'tessdata'
    if not exe.exists():
        raise FileNotFoundError(f'tesseract.exe nao encontrado em {exe}')
    if not tessdata.exists():
        raise FileNotFoundError(f'tessdata nao encontrado em {tessdata}')
    for required in ('eng.traineddata', 'osd.traineddata'):
        if not (tessdata / required).exists():
            raise FileNotFoundError(f'arquivo obrigatorio ausente: {required}')


def build_zip(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(source_dir.rglob('*')):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description='Empacota o Tesseract portatil local para distribuicao externa.')
    parser.add_argument('--source-dir', default=str(SOURCE_DIR))
    parser.add_argument('--zip-path', default=str(DEFAULT_ZIP))
    parser.add_argument('--manifest-path', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--release-tag', default='v2.1.0')
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    zip_path = Path(args.zip_path).resolve()
    manifest_path = Path(args.manifest_path).resolve()

    validate_source_dir(source_dir)
    build_zip(source_dir, zip_path)
    digest = sha256_file(zip_path)
    size_bytes = zip_path.stat().st_size

    manifest = {
        'release_tag': args.release_tag,
        'artifact_name': zip_path.name,
        'artifact_path': str(zip_path),
        'artifact_sha256': digest,
        'size_bytes': size_bytes,
        'source_dir': str(source_dir),
        'bootstrap_env': {
            'GROM_OCR_TESSERACT_ARTIFACT_PATH': str(zip_path),
            'GROM_OCR_TESSERACT_ARTIFACT_SHA256': digest,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f'ZIP={zip_path}')
    print(f'SHA256={digest}')
    print(f'MANIFEST={manifest_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
