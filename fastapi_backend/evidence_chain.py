from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHAIN_LOG = PROJECT_ROOT / 'data' / 'evidence_chain.jsonl'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()


def sha256_file(path: str) -> str:
    if not path or not os.path.exists(path):
        return ''
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(8192), b''):
            digest.update(chunk)
    return digest.hexdigest()


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    return sha256_text(_canonical_json(payload if isinstance(payload, dict) else {}))


def _read_last_chain_hash(chain_log_path: Path) -> str:
    if not chain_log_path.exists():
        return ''

    try:
        last_line = ''
        with chain_log_path.open('r', encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    last_line = line.strip()
        if not last_line:
            return ''
        payload = json.loads(last_line)
        if not isinstance(payload, dict):
            return ''
        return str(payload.get('entry_hash', '') or '')
    except Exception:
        return ''


def _sign_material(material: str, secret: str) -> str:
    if not secret:
        return sha256_text(material)
    return hmac.new(secret.encode('utf-8'), material.encode('utf-8'), hashlib.sha256).hexdigest()


def register_evidence_chain_entry(
    analysis_id: str,
    source_type: str,
    evidence_hashes: Dict[str, str],
    payload_hash: str,
    chain_log_path: str | None = None,
) -> Dict[str, Any]:
    chain_path = Path(chain_log_path).resolve() if chain_log_path else DEFAULT_CHAIN_LOG
    chain_path.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = _read_last_chain_hash(chain_path)
    secret = str(os.environ.get('GROM_OCR_CHAIN_SECRET', '') or '')

    entry_base = {
        'analysis_id': str(analysis_id or ''),
        'source_type': str(source_type or 'image'),
        'generated_at_utc': _utc_now_iso(),
        'prev_entry_hash': prev_hash,
        'evidence_hashes': evidence_hashes if isinstance(evidence_hashes, dict) else {},
        'payload_hash': str(payload_hash or ''),
    }

    material = _canonical_json(entry_base)
    signature = _sign_material(material, secret)
    entry_hash = sha256_text(f'{material}|{signature}|{prev_hash}')

    entry = dict(entry_base)
    entry['signature'] = signature
    entry['entry_hash'] = entry_hash

    with chain_path.open('a', encoding='utf-8') as stream:
        stream.write(_canonical_json(entry) + '\n')

    return {
        'chain_log': str(chain_path),
        'entry_hash': entry_hash,
        'prev_entry_hash': prev_hash,
        'signature': signature,
        'payload_hash': entry['payload_hash'],
        'evidence_hashes': entry['evidence_hashes'],
        'immutable': True,
    }
