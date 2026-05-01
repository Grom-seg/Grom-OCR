#!/usr/bin/env python
"""Supervisor para executar `run_benchmark_suite.py` com timeout e fallback.

- Inicia a suite (modo especificado).
- Aguarda criação do diretório de run e do primeiro artefato de job.
- Se ultrapassar `--first-output-timeout-mins`, mata o processo e (opcional)
  dispara a execução do modo `hard` para diagnóstico/execução separada.
"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def find_new_run_dir(output_root: Path, since_ts: float, timeout: float) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not output_root.exists():
            time.sleep(0.5)
            continue
        # look for directories with ISO-like run_id name
        for p in sorted(output_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                if not p.is_dir():
                    continue
                mtime = p.stat().st_mtime
                if mtime >= since_ts:
                    return p
            except Exception:
                continue
        time.sleep(0.5)
    return None


def has_first_job_output(run_dir: Path) -> bool:
    # Consider any job output JSON (excluding the overall summary) or any stdout.log
    for f in run_dir.rglob("*"):
        if f.is_file():
            nm = f.name.lower()
            if nm == 'benchmark_suite_summary.json':
                continue
            if nm.endswith('.json') or nm.endswith('.log'):
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description='Supervisor para run_benchmark_suite.py')
    parser.add_argument('--mode', choices=['standard', 'hard', 'all'], default='standard')
    parser.add_argument('--output-dir', type=Path, default=Path('data/benchmark_runs'))
    parser.add_argument('--first-output-timeout-mins', type=float, default=48.0,
                        help='Minutes to wait for first job output before killing the run')
    parser.add_argument('--poll-interval-secs', type=float, default=10.0)
    parser.add_argument('--fallback-hard', action='store_true', help='If timeout, run hard jobs separately')
    parser.add_argument('--py-launcher', type=str, default='py -3', help='Python launcher to use (default: py -3)')
    parser.add_argument('--extra-args', nargs=argparse.REMAINDER, help='Extra args forwarded to run_benchmark_suite')
    parser.add_argument('--notify', action='store_true', help='Send email notifications on events')
    parser.add_argument('--notify-to', type=str, default=os.environ.get('NOTIFY_TO', ''), help='Comma-separated recipient emails (or use NOTIFY_TO env)')
    parser.add_argument('--notify-from', type=str, default=os.environ.get('NOTIFY_FROM', ''), help='From email address (or use NOTIFY_FROM env)')
    parser.add_argument('--smtp-host', type=str, default=os.environ.get('SMTP_HOST', ''), help='SMTP server host (or use SMTP_HOST env)')
    parser.add_argument('--smtp-port', type=int, default=int(os.environ.get('SMTP_PORT', '0') or 0), help='SMTP server port (or use SMTP_PORT env)')
    parser.add_argument('--smtp-user', type=str, default=os.environ.get('SMTP_USER', ''), help='SMTP username (or use SMTP_USER env)')
    parser.add_argument('--smtp-pass', type=str, default=os.environ.get('SMTP_PASS', ''), help='SMTP password (or use SMTP_PASS env)')
    parser.add_argument('--smtp-use-tls', action='store_true', help='Use STARTTLS for SMTP')
    args = parser.parse_args()

    output_root = args.output_dir.resolve()
    start_monotonic = time.monotonic()
    start_ts = time.time()

    # setup logging
    log_dir = Path('logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_dir / 'supervisor.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ],
    )

    def send_email(subject: str, body: str) -> None:
        if not args.notify:
            return
        smtp_host = args.smtp_host
        smtp_port = args.smtp_port or (587 if args.smtp_use_tls else 25)
        smtp_user = args.smtp_user
        smtp_pass = args.smtp_pass
        from_addr = args.notify_from
        to_addrs = [a.strip() for a in (args.notify_to or '').split(',') if a.strip()]
        if not smtp_host or not from_addr or not to_addrs:
            logging.warning('Not sending email: SMTP_HOST/notify_from/notify_to not configured')
            return
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = ', '.join(to_addrs)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            logging.info('Sending notification email to: %s', msg['To'])
            s = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            if args.smtp_use_tls:
                s.starttls()
            if smtp_user:
                s.login(smtp_user, smtp_pass)
            s.sendmail(from_addr, to_addrs, msg.as_string())
            s.quit()
        except Exception as exc:
            logging.exception('Falha ao enviar email: %s', exc)

    cmd = f"{args.py_launcher} tools/run_benchmark_suite.py --mode {args.mode} --output-dir {str(output_root)}"
    if args.extra_args:
        cmd += ' ' + ' '.join(args.extra_args)

    logging.info("Launching: %s", cmd)
    proc = subprocess.Popen(cmd, shell=True)

    try:
        # find run dir created after we started
        run_dir = find_new_run_dir(output_root, start_ts, timeout=30.0)
        if not run_dir:
            logging.info("Nenhum run directory detectado logo após a execucao; aguardando com timeout...")
            run_dir = find_new_run_dir(output_root, start_ts, timeout=args.first_output_timeout_mins * 60)

        if not run_dir:
            logging.error("Timeout: nenhum run directory criado. Matando processo.")
            send_email('Benchmark supervisor: run nao iniciado', f'Nenhum run directory foi criado para o comando: {cmd}')
            proc.kill()
            proc.wait()
            if args.fallback_hard:
                logging.info('Iniciando fallback: modo hard')
                subprocess.run(f"{args.py_launcher} tools/run_benchmark_suite.py --mode hard --output-dir {str(output_root / 'fallback_hard')}", shell=True)
            sys.exit(1)

        logging.info("Run dir detected: %s", run_dir)
        send_email('Benchmark supervisor: run iniciado', f'Run detectado: {run_dir}\nComando: {cmd}')

        first_output_deadline = time.monotonic() + args.first_output_timeout_mins * 60
        while proc.poll() is None:
            if has_first_job_output(run_dir):
                logging.info('Primeiro artefato detectado — monitoramento concluido com sucesso.')
                send_email('Benchmark supervisor: primeiro artefato detectado', f'Primeiro artefato detectado em: {run_dir}')
                break
            if time.monotonic() >= first_output_deadline:
                logging.error('Timeout de %s minutos atingido sem primeiro output. Matando processo.', args.first_output_timeout_mins)
                send_email('Benchmark supervisor: timeout sem output', f'O run em {run_dir} nao produziu artefatos em {args.first_output_timeout_mins} minutos; matando processo.')
                proc.kill()
                proc.wait()
                if args.fallback_hard:
                    logging.info('Iniciando fallback: modo hard')
                    subprocess.run(f"{args.py_launcher} tools/run_benchmark_suite.py --mode hard --output-dir {str(output_root / 'fallback_hard')}", shell=True)
                sys.exit(1)
            time.sleep(args.poll_interval_secs)

        # wait for process to finish normally and return its code
        rc = proc.wait()
        logging.info('Process finished with return code: %s', rc)
        send_email('Benchmark supervisor: run finalizado', f'Run em {run_dir} finalizou com codigo {rc}')
        sys.exit(rc)

    except KeyboardInterrupt:
        print('Interrompido pelo usuario — matando processo filho')
        proc.kill()
        proc.wait()
        raise


if __name__ == '__main__':
    main()
