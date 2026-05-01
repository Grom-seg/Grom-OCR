import os
import sys
import time
import subprocess
from typing import Optional

import pytest
import requests

API_BASE = "http://127.0.0.1:5000"
HEALTH_URL = f"{API_BASE}/health"
ROOT_URL = f"{API_BASE}/"
START_SCRIPT = os.path.join("tools", "start_ocr_api.py")

STARTUP_TIMEOUT_S = 120
POLL_INTERVAL_S = 1.5


def _netstat_listening_pids(port: int) -> list[int]:
    out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    pids: list[int] = []
    for line in out.splitlines():
        if f":{port} " not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        pid_token = parts[-1]
        if pid_token.isdigit():
            pids.append(int(pid_token))
    return sorted(set(pids))


def _taskkill_pids(pids: list[int]) -> None:
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _try_health_json() -> Optional[dict]:
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200:
            return None
        if "application/json" in ct or ct.endswith("+json"):
            return r.json()
        # fallback: some servers might still send JSON-ish
        if r.text and r.text.strip().startswith(("{", "[")):
            return r.json()
        return None
    except Exception:
        return None


def _try_root_json_service() -> Optional[dict]:
    try:
        r = requests.get(ROOT_URL, timeout=5)
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200:
            return None
        if "application/json" not in ct and not ct.endswith("+json"):
            return None
        data = r.json()
        if isinstance(data, dict) and data.get("service") == "grom_ocr_api":
            return data
        return None
    except Exception:
        return None


def _start_api_process() -> subprocess.Popen:
    env = os.environ.copy()
    cmd = [sys.executable, START_SCRIPT]

    os.makedirs("logs", exist_ok=True)
    stdout_path = os.path.join("logs", "test_api_stdout.log")
    stderr_path = os.path.join("logs", "test_api_stderr.log")
    stdout_f = open(stdout_path, "a", encoding="utf-8")
    stderr_f = open(stderr_path, "a", encoding="utf-8")

    proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f, env=env)
    return proc


@pytest.fixture(scope="session")
def ensure_ocr_api() -> None:
    # Se já está saudável, não faz nada.
    if _try_health_json() is not None:
        return
    if _try_root_json_service() is not None:
        return

    # Mata qualquer coisa que esteja na porta 5000 (dashboard/stale/...)
    pids = _netstat_listening_pids(5000)
    if pids:
        _taskkill_pids(pids)
        time.sleep(1)

    # Sobe a API correta
    proc = _start_api_process()

    # Aguarda ficar saudável
    start = time.time()
    last_body = ""
    while time.time() - start < STARTUP_TIMEOUT_S:
        payload = _try_health_json()
        if payload is not None:
            return
        root_payload = _try_root_json_service()
        if root_payload is not None:
            return

        try:
            r = requests.get(HEALTH_URL, timeout=3)
            last_body = (r.text or "")[:500]
        except Exception:
            last_body = ""

        time.sleep(POLL_INTERVAL_S)

    try:
        proc.terminate()
    except Exception:
        pass

    raise AssertionError(
        f"API não ficou saudável em {HEALTH_URL} (timeout {STARTUP_TIMEOUT_S}s). "
        f"Último body (prefix): {last_body}"
    )
