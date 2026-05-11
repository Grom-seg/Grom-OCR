#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = PROJECT_ROOT / 'tools' / 'package_tesseract_artifact.py'
DEFAULT_MANIFEST = PROJECT_ROOT / 'dist' / 'tesseract-portable-manifest.json'


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
        if not body:
            return ''
        return body.decode('utf-8', errors='replace')
    except Exception:
        return ''


def validate_token(token: str) -> None:
    normalized = (token or '').strip()
    if not normalized:
        raise RuntimeError('defina GITHUB_TOKEN ou GH_TOKEN para publicar a release')

    placeholder_values = {
        'SEU_TOKEN',
        'YOUR_TOKEN',
        'TOKEN_AQUI',
        'GH_TOKEN',
        'GITHUB_TOKEN',
    }
    if normalized.upper() in placeholder_values:
        raise RuntimeError(
            'token placeholder detectado. Substitua o valor por um token GitHub real '
            'com permissao de releases/conteudo no repositorio.'
        )


def api_request(url: str, method: str, token: str, payload: dict | None = None, content_type: str = 'application/json') -> dict:
    data = None
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'grom-ocr-release-automation',
    }
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = content_type

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as response:
        body = response.read()
        if not body:
            return {}
        return json.loads(body.decode('utf-8'))


def upload_asset(upload_url_template: str, asset_path: Path, token: str) -> dict:
    upload_url = upload_url_template.split('{', 1)[0]
    upload_url = f'{upload_url}?name={urllib.parse.quote(asset_path.name)}'
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'grom-ocr-release-automation',
        'Content-Type': 'application/zip',
    }
    req = urllib.request.Request(upload_url, data=asset_path.read_bytes(), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=300) as response:
        body = response.read()
        return json.loads(body.decode('utf-8')) if body else {}


def get_release_by_tag(repo: str, tag: str, token: str) -> dict | None:
    url = f'https://api.github.com/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}'
    try:
        return api_request(url, 'GET', token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def describe_http_error(exc: urllib.error.HTTPError) -> RuntimeError:
    body = _read_http_error_body(exc)
    if exc.code == 401:
        return RuntimeError(
            'GitHub respondeu 401 Unauthorized. Verifique se GITHUB_TOKEN/GH_TOKEN '
            'esta correto, nao expirou e nao e um valor placeholder. '
            f'Detalhe da API: {body or "sem corpo de resposta"}'
        )
    if exc.code == 403:
        return RuntimeError(
            'GitHub respondeu 403 Forbidden. O token provavelmente nao tem permissao '
            'para releases ou o limite da API foi atingido. '
            f'Detalhe da API: {body or "sem corpo de resposta"}'
        )
    return RuntimeError(
        f'GitHub API retornou HTTP {exc.code}. '
        f'Detalhe da API: {body or "sem corpo de resposta"}'
    )


def delete_existing_asset(repo: str, release: dict, asset_name: str, token: str) -> None:
    for asset in release.get('assets', []):
        if str(asset.get('name', '')) == asset_name:
            asset_id = asset.get('id')
            if asset_id:
                api_request(f'https://api.github.com/repos/{repo}/releases/assets/{asset_id}', 'DELETE', token)


def create_release(repo: str, tag: str, title: str, notes: str, token: str, target_commitish: str = 'main') -> dict:
    url = f'https://api.github.com/repos/{repo}/releases'
    payload = {
        'tag_name': tag,
        'target_commitish': target_commitish,
        'name': title,
        'body': notes,
        'draft': False,
        'prerelease': False,
    }
    return api_request(url, 'POST', token, payload=payload)


def update_release(repo: str, release_id: int, title: str, notes: str, token: str) -> dict:
    url = f'https://api.github.com/repos/{repo}/releases/{release_id}'
    payload = {
        'name': title,
        'body': notes,
        'draft': False,
        'prerelease': False,
    }
    return api_request(url, 'PATCH', token, payload=payload)


def run_packager(release_tag: str) -> Path:
    subprocess.run(
        [sys.executable, str(PACKAGE_SCRIPT), '--release-tag', release_tag],
        cwd=str(PROJECT_ROOT),
        check=True,
    )
    if not DEFAULT_MANIFEST.exists():
        raise FileNotFoundError(f'manifesto nao encontrado em {DEFAULT_MANIFEST}')
    return DEFAULT_MANIFEST


def build_release_notes(tag: str, manifest: dict) -> str:
    sha256 = str(manifest.get('artifact_sha256', ''))
    size_bytes = int(manifest.get('size_bytes', 0) or 0)
    asset_name = str(manifest.get('artifact_name', 'tesseract-portable-win64.zip'))
    return (
        f'Artefato do Tesseract portatil para GROM OCR {tag}.\n\n'
        f'- Asset: {asset_name}\n'
        f'- SHA256: {sha256}\n'
        f'- Size: {size_bytes} bytes\n\n'
        'Uso esperado no bootstrap:\n'
        f'- GROM_OCR_TESSERACT_ARTIFACT_URL=https://github.com/Grom-seg/Grom-OCR/releases/download/tesseract-portable/{asset_name}\n'
        f'- GROM_OCR_TESSERACT_ARTIFACT_SHA256={sha256}\n'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Publica automaticamente o artefato do Tesseract em release do GitHub.')
    parser.add_argument('--repo', default='Grom-seg/Grom-OCR')
    parser.add_argument('--tag', default='tesseract-portable')
    parser.add_argument('--release-tag', default='v2.1.0')
    parser.add_argument('--title', default='Tesseract Portable Artifact')
    parser.add_argument('--notes-file', default='')
    parser.add_argument('--target-commitish', default='main')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    manifest_path = run_packager(args.release_tag)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    asset_path = Path(str(manifest.get('artifact_path', '')))
    if not asset_path.exists():
        raise FileNotFoundError(f'asset nao encontrado: {asset_path}')

    notes = build_release_notes(args.release_tag, manifest)
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding='utf-8')

    if args.dry_run:
        print(f'DRY_RUN_REPO={args.repo}')
        print(f'DRY_RUN_TAG={args.tag}')
        print(f'DRY_RUN_ASSET={asset_path}')
        print(f'DRY_RUN_SHA256={manifest.get("artifact_sha256", "")}')
        return 0

    token = os.environ.get('GITHUB_TOKEN', '').strip() or os.environ.get('GH_TOKEN', '').strip()
    validate_token(token)

    try:
        release = get_release_by_tag(args.repo, args.tag, token)
        if release is None:
            release = create_release(args.repo, args.tag, args.title, notes, token, target_commitish=args.target_commitish)
        else:
            release = update_release(args.repo, int(release['id']), args.title, notes, token)

        delete_existing_asset(args.repo, release, asset_path.name, token)
        asset = upload_asset(str(release['upload_url']), asset_path, token)
    except urllib.error.HTTPError as exc:
        raise describe_http_error(exc) from exc

    print(f'RELEASE_URL={release.get("html_url", "")}')
    print(f'ASSET_URL={asset.get("browser_download_url", "")}')
    print(f'SHA256={manifest.get("artifact_sha256", "")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
