#!/usr/bin/env python
"""
Executor Autônomo de Orquestração Forense (GROM OCR)

Coordena execução de todo sistema de análise forense:
- Revalidação de gates de qualidade
- Execução de bateria de calibração
- Testes de integração ponta a ponta
- Geração de relatórios consolidados para instituições

Uso:
    python tools/orchestrator_executor.py --mode full
    python tools/orchestrator_executor.py --mode gates-only
    python tools/orchestrator_executor.py --mode calibration
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
LOGS_DIR = PROJECT_ROOT / 'logs'
TOOLS_DIR = PROJECT_ROOT / 'tools'

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'orchestrator_executor.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


class OrchestratorExecutor:
    """Executor autônomo de tarefas forenses com hierarquia de dependências."""

    def __init__(self):
        self.execution_plan: List[Dict[str, Any]] = []
        self.execution_results: Dict[str, Any] = {}
        self.started_at_utc = datetime.now(timezone.utc)

    def plan_full_revalidation(self) -> List[Dict[str, Any]]:
        """Planeja revalidação forense completa."""
        plan = [
            {
                'task_id': 'revalidate_gates',
                'name': 'Revalidação de Gates Forenses',
                'description': 'Executa bateria de calibração e suite de benchmark com gates',
                'command': [
                    sys.executable,
                    str(TOOLS_DIR / 'revalidate_forensic_quality.py'),
                    '--policy-file', str(DATA_DIR / 'phase1_quality_gate_policy.json'),
                    '--skip-refresh-manifests',
                ],
                'dependencies': [],
                'critical': True,
                'timeout_sec': 300,
            },
            {
                'task_id': 'validate_integrations',
                'name': 'Validação de Integrações Ponta a Ponta',
                'description': 'Executa testes de integração do pipeline completo',
                'command': [
                    sys.executable,
                    '-m', 'pytest',
                    str(PROJECT_ROOT / 'test_simple.py'),
                    str(PROJECT_ROOT / 'test_process.py'),
                    str(PROJECT_ROOT / 'test_regions.py'),
                    '-v', '--tb=short',
                ],
                'dependencies': ['revalidate_gates'],
                'critical': False,
                'timeout_sec': 180,
            },
            {
                'task_id': 'generate_institutional_report',
                'name': 'Gerar Relatório Institucional',
                'description': 'Consolida resultados em formato institucional',
                'command': [
                    sys.executable,
                    str(TOOLS_DIR / 'generate_institutional_report.py'),
                ],
                'dependencies': ['revalidate_gates', 'validate_integrations'],
                'critical': False,
                'timeout_sec': 60,
            },
        ]

        self.execution_plan = plan
        return plan

    def plan_gates_only(self) -> List[Dict[str, Any]]:
        """Planeja apenas revalidação de gates."""
        plan = [
            {
                'task_id': 'revalidate_gates',
                'name': 'Revalidação de Gates Forenses',
                'description': 'Executa bateria de calibração e suite de benchmark com gates',
                'command': [
                    sys.executable,
                    str(TOOLS_DIR / 'revalidate_forensic_quality.py'),
                    '--policy-file', str(DATA_DIR / 'phase1_quality_gate_policy.json'),
                    '--skip-refresh-manifests',
                ],
                'dependencies': [],
                'critical': True,
                'timeout_sec': 300,
            },
        ]

        self.execution_plan = plan
        return plan

    def plan_calibration_only(self) -> List[Dict[str, Any]]:
        """Planeja apenas execução de bateria de calibração."""
        plan = [
            {
                'task_id': 'calibration_battery',
                'name': 'Execução de Bateria de Calibração',
                'description': 'Roda bateria canônica de calibração com policy',
                'command': [
                    sys.executable,
                    str(TOOLS_DIR / 'run_image_calibration_battery.py'),
                    '--policy-file', str(DATA_DIR / 'phase1_quality_gate_policy.json'),
                ],
                'dependencies': [],
                'critical': True,
                'timeout_sec': 300,
            },
        ]

        self.execution_plan = plan
        return plan

    def execute_plan(self, dry_run: bool = False) -> Dict[str, Any]:
        """Executa plano com respeito a dependências."""
        if not self.execution_plan:
            raise ValueError("Nenhum plano foi definido")

        executed_tasks = set()
        failed_tasks = set()
        results = []

        # Usar ordenação topológica simples
        remaining = list(self.execution_plan)

        while remaining:
            # Encontrar tarefa sem dependências não executadas
            available = None
            for task in remaining:
                deps = set(task.get('dependencies', []))
                if deps.issubset(executed_tasks):
                    available = task
                    break

            if available is None:
                # Ciclo detectado
                logger.error(f"Ciclo detectado entre: {[t['task_id'] for t in remaining]}")
                break

            task_result = self._execute_task(available, dry_run=dry_run)
            results.append(task_result)

            if task_result['status'] == 'completed':
                executed_tasks.add(available['task_id'])
            elif available.get('critical', False):
                failed_tasks.add(available['task_id'])
                logger.error(f"Tarefa crítica falhou: {available['task_id']}")
                break
            else:
                failed_tasks.add(available['task_id'])
                logger.warning(f"Tarefa não-crítica falhou: {available['task_id']}")

            remaining.remove(available)

        finished_at_utc = datetime.now(timezone.utc)

        self.execution_results = {
            'started_at_utc': self.started_at_utc.isoformat(),
            'finished_at_utc': finished_at_utc.isoformat(),
            'duration_sec': round((finished_at_utc - self.started_at_utc).total_seconds(), 2),
            'total_tasks': len(self.execution_plan),
            'executed_tasks': len(executed_tasks),
            'failed_tasks': len(failed_tasks),
            'status': 'success' if not failed_tasks else 'partial_failure' if not any(t.get('critical') for t in self.execution_plan if t['task_id'] in failed_tasks) else 'failure',
            'results': results,
            'dry_run': dry_run,
        }

        return self.execution_results

    def _execute_task(self, task: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
        """Executa uma tarefa individual."""
        task_id = task['task_id']
        name = task['name']

        logger.info(f"[INICIANDO] {name} ({task_id})")

        if dry_run:
            logger.info(f"[DRY RUN] Seria executado: {' '.join(task['command'])}")
            return {
                'task_id': task_id,
                'name': name,
                'status': 'dry_run',
                'returncode': 0,
            }

        try:
            started = datetime.now(timezone.utc)

            result = subprocess.run(
                task['command'],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=task.get('timeout_sec', 300),
            )

            finished = datetime.now(timezone.utc)
            duration = (finished - started).total_seconds()

            if result.returncode == 0:
                logger.info(f"[✓ SUCESSO] {name} em {duration:.1f}s")
                status = 'completed'
            else:
                logger.error(f"[✗ FALHA] {name}: {result.stderr[:200]}")
                status = 'failed'

            return {
                'task_id': task_id,
                'name': name,
                'status': status,
                'returncode': result.returncode,
                'duration_sec': round(duration, 2),
                'stdout_preview': (result.stdout[:500] + '...') if len(result.stdout) > 500 else result.stdout,
                'stderr_preview': (result.stderr[:500] + '...') if len(result.stderr) > 500 else result.stderr,
            }

        except subprocess.TimeoutExpired as e:
            logger.error(f"[✗ TIMEOUT] {name} excedeu {task.get('timeout_sec')}s")
            return {
                'task_id': task_id,
                'name': name,
                'status': 'timeout',
                'error': str(e),
            }

        except Exception as e:
            logger.error(f"[✗ ERRO] {name}: {e}", exc_info=True)
            return {
                'task_id': task_id,
                'name': name,
                'status': 'error',
                'error': str(e),
            }

    def save_results(self, output_path: Optional[Path] = None) -> Path:
        """Salva resultados em JSON."""
        if not self.execution_results:
            raise ValueError("Nenhum resultado para salvar")

        if output_path is None:
            output_path = DATA_DIR / 'test_results' / f'orchestrator_execution_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json'

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.execution_results, f, ensure_ascii=False, indent=2)

        logger.info(f"Resultados salvos em: {output_path}")
        return output_path

    def print_summary(self):
        """Imprime resumo da execução."""
        if not self.execution_results:
            return

        results = self.execution_results

        print("\n" + "="*70)
        print("RESUMO DE EXECUÇÃO FORENSE".center(70))
        print("="*70)

        print(f"\nTempo total: {results['duration_sec']}s")
        print(f"Status: {results['status'].upper()}")
        print(f"Tarefas: {results['executed_tasks']}/{results['total_tasks']}")

        if results['failed_tasks'] > 0:
            print(f"⚠️  Falhas: {results['failed_tasks']}")

        print("\nDetalhes das tarefas:")
        for result in results['results']:
            status_icon = "✓" if result['status'] == 'completed' else "✗"
            print(f"  {status_icon} {result['name']}: {result.get('status', 'unknown')}")

            if 'duration_sec' in result:
                print(f"      Duração: {result['duration_sec']}s")

            if result['status'] != 'completed' and 'error' in result:
                print(f"      Erro: {result['error']}")

        print("\n" + "="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Executor Autônomo de Orquestração Forense GROM OCR'
    )
    parser.add_argument(
        '--mode',
        choices=['full', 'gates-only', 'calibration'],
        default='full',
        help='Modo de execução (default: full)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Modo simulação (não executa)',
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Arquivo de saída (default: auto)',
    )

    args = parser.parse_args()

    # Criar executor
    executor = OrchestratorExecutor()

    # Planejar baseado no modo
    if args.mode == 'full':
        logger.info("Modo: Revalidação Forense Completa")
        executor.plan_full_revalidation()
    elif args.mode == 'gates-only':
        logger.info("Modo: Gates Apenas")
        executor.plan_gates_only()
    elif args.mode == 'calibration':
        logger.info("Modo: Calibração Apenas")
        executor.plan_calibration_only()

    logger.info(f"Plano gerado com {len(executor.execution_plan)} tarefas")

    # Executar
    results = executor.execute_plan(dry_run=args.dry_run)

    # Salvar e exibir
    output_path = executor.save_results(args.output)
    executor.print_summary()

    # Retornar código de saída apropriado
    if results['status'] == 'success':
        return 0
    else:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
