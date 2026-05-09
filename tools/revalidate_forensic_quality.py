#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
DEFAULT_POLICY = DATA_DIR / 'phase1_quality_gate_policy.json'
DEFAULT_OUTPUT_JSON = DATA_DIR / 'test_results' / 'forensic_revalidation_latest.json'
DEFAULT_OUTPUT_MD = DATA_DIR / 'test_results' / 'forensic_revalidation_latest.md'


def _run_command(cmd: list[str]) -> dict:
    started = datetime.now(timezone.utc)
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    finished = datetime.now(timezone.utc)
    return {
        'command': cmd,
        'started_at_utc': started.isoformat().replace('+00:00', 'Z'),
        'finished_at_utc': finished.isoformat().replace('+00:00', 'Z'),
        'duration_sec': round((finished - started).total_seconds(), 3),
        'returncode': int(proc.returncode),
        'stdout': proc.stdout or '',
        'stderr': proc.stderr or '',
        'ok': proc.returncode == 0,
    }


def _parse_gate_from_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    gate = payload.get('gate')
    if isinstance(gate, dict):
        return gate

    summary_gate = payload.get('summary', {}).get('gate') if isinstance(payload.get('summary'), dict) else None
    if isinstance(summary_gate, dict):
        return summary_gate

    return {}


def _write_markdown(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append('# Revalidacao Forense - Resumo')
    lines.append('')
    lines.append(f"- Gerado em UTC: {report.get('generated_at_utc', '-')}")
    lines.append(f"- Status geral: {'APROVADO' if report.get('passed') else 'REPROVADO'}")
    lines.append('')

    for run in report.get('runs', []):
        name = str(run.get('name', 'execucao'))
        lines.append(f"## {name}")
        lines.append('')
        lines.append(f"- Exit code: {run.get('returncode', '-')}")
        lines.append(f"- Duracao (s): {run.get('duration_sec', '-')}")
        lines.append(f"- OK: {'sim' if run.get('ok') else 'nao'}")

        gate = run.get('gate', {})
        if isinstance(gate, dict) and gate:
            lines.append(f"- Gate aprovado: {'sim' if gate.get('passed', True) else 'nao'}")
            checks = gate.get('checks', [])
            if isinstance(checks, list) and checks:
                lines.append('- Checks:')
                for check in checks[:20]:
                    if not isinstance(check, dict):
                        continue
                    name_check = str(check.get('name') or check.get('scope') or 'check')
                    lines.append(f"  - {name_check}: {'ok' if check.get('passed') else 'falhou'}")
        lines.append('')

    lines.append('## Proximos passos')
    lines.append('')
    lines.append('- Se aprovado: promover deploy e registrar baseline novo.')
    lines.append('- Se reprovado: nao promover, revisar logs e recalibrar antes de novo run.')
    lines.append('')

    path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Executa revalidacao forense completa com gates.')
    parser.add_argument('--policy-file', type=Path, default=DEFAULT_POLICY)
    parser.add_argument('--output-json', type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument('--output-md', type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument('--skip-refresh-manifests', action='store_true')
    args = parser.parse_args()

    policy = args.policy_file.resolve()
    py = sys.executable

    battery_cmd = [
        py,
        'tools/run_image_calibration_battery.py',
        '--policy-file',
        str(policy),
    ]
    suite_cmd = [
        py,
        'tools/run_benchmark_suite.py',
        '--mode',
        'hard',
        '--policy-file',
        str(policy),
    ]
    if args.skip_refresh_manifests:
        suite_cmd.append('--skip-refresh-manifests')

    battery_run = _run_command(battery_cmd)
    battery_gate = _parse_gate_from_json(DATA_DIR / 'test_results' / 'image_calibration_battery_current.json')
    battery_run['name'] = 'image_calibration_battery'
    battery_run['gate'] = battery_gate

    suite_run = _run_command(suite_cmd)
    suite_gate = _parse_gate_from_json(DATA_DIR / 'benchmark_suite_latest.json')
    suite_run['name'] = 'benchmark_suite_hard'
    suite_run['gate'] = suite_gate

    passed = bool(battery_run.get('ok')) and bool(suite_run.get('ok'))
    if isinstance(battery_gate, dict) and battery_gate:
        passed = passed and bool(battery_gate.get('passed', True))
    if isinstance(suite_gate, dict) and suite_gate:
        passed = passed and bool(suite_gate.get('passed', True))

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'policy_file': str(policy),
        'passed': passed,
        'runs': [battery_run, suite_run],
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _write_markdown(args.output_md, report)

    print(json.dumps({'passed': passed, 'output_json': str(args.output_json), 'output_md': str(args.output_md)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
