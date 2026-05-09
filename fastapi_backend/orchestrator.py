"""
Orquestrador Central de Análise Forense de Placas Veiculares (GROM OCR)

Este módulo coordena toda a delegação, hierarquia de tarefas, monitoramento
e execução de pipelines periciaiscom conformidade institucional.

Propósito: garantir que toda análise de placa seja realizada com máxima
confiabilidade, auditoria, rastreabilidade e conformidade com protocolos
forenses nacionais.

Criado para: revolucionar análise pericial de placas no Brasil e servir
como referência nacional para instituições de segurança pública.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = PROJECT_ROOT / 'python'
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

# Configurar logging forense
logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Estados de execução de tarefa."""
    PENDING = "pending"
    RUNNING = "running"
    DELEGATED = "delegated"
    COMPLETED = "completed"
    FAILED = "failed"
    FALLBACK = "fallback"


class TaskDomain(str, Enum):
    """Domínios de análise forense."""
    PLATE_DETECTION = "plate_detection"
    OCR_RECOGNITION = "ocr_recognition"
    VEHICLE_ANALYSIS = "vehicle_analysis"
    ENSEMBLE_DETECTION = "ensemble_detection"
    CALIBRATION = "calibration"
    QUALITY_VALIDATION = "quality_validation"
    REPORT_GENERATION = "report_generation"
    FORENSIC_CHAIN = "forensic_chain"


@dataclass
class TaskExecutionMetrics:
    """Métricas de execução de tarefa."""
    task_id: str
    task_name: str
    domain: TaskDomain
    status: TaskStatus = TaskStatus.PENDING
    started_at_utc: Optional[str] = None
    finished_at_utc: Optional[str] = None
    duration_ms: float = 0.0
    delegated: bool = False
    delegated_engine: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    result_preview: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        data = asdict(self)
        data['domain'] = self.domain.value
        data['status'] = self.status.value
        return data


@dataclass
class ForensicAnalysisContext:
    """Contexto completo de uma análise forense."""
    analysis_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source_filename: Optional[str] = None
    analysis_stage: str = "final"  # preview, investigacao, final
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Hierarquia de tarefas
    tasks: Dict[str, TaskExecutionMetrics] = field(default_factory=dict)
    task_dependencies: Dict[str, List[str]] = field(default_factory=dict)
    task_order: List[str] = field(default_factory=list)

    # Resultados consolidados
    delegated_results: Dict[str, Any] = field(default_factory=dict)
    fallback_results: Dict[str, Any] = field(default_factory=dict)
    enriched_payload: Dict[str, Any] = field(default_factory=dict)

    # Auditoria
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)
    quality_gates_passed: Dict[str, bool] = field(default_factory=dict)


class ForensicOrchestrator:
    """
    Orquestrador central de análise forense.

    Responsável por:
    - Coordenar delegação para pipeline legado
    - Executar hierarquia de tarefas com dependências
    - Monitorar qualidade forense em tempo real
    - Gerar cadeia de custódia digital
    - Auditar conformidade institucional
    """

    def __init__(self, legacy_ocr_agent=None, enable_delegations: bool = True):
        self.legacy_ocr_agent = legacy_ocr_agent
        self.enable_delegations = enable_delegations
        self.context: Optional[ForensicAnalysisContext] = None

    def create_analysis_context(
        self,
        source_filename: Optional[str] = None,
        analysis_stage: str = "final",
    ) -> ForensicAnalysisContext:
        """Cria novo contexto de análise."""
        self.context = ForensicAnalysisContext(
            source_filename=source_filename,
            analysis_stage=analysis_stage,
        )
        return self.context

    def define_task_hierarchy(
        self,
        tasks: Dict[str, TaskDomain],
        dependencies: Dict[str, List[str]] = None,
    ) -> List[str]:
        """
        Define hierarquia de tarefas com dependências.

        Exemplo:
            tasks = {
                'detect': TaskDomain.PLATE_DETECTION,
                'ocr': TaskDomain.OCR_RECOGNITION,
                'validate': TaskDomain.QUALITY_VALIDATION,
            }
            dependencies = {
                'ocr': ['detect'],
                'validate': ['ocr'],
            }

        Retorna a ordem topológica de execução.
        """
        if not self.context:
            self.context = self.create_analysis_context()

        self.context.task_dependencies = dependencies or {}

        # Validar ciclos
        if self._has_cycle(tasks, self.context.task_dependencies):
            raise ValueError("Ciclo detectado na hierarquia de tarefas")

        # Computar ordem topológica
        order = self._topological_sort(tasks, self.context.task_dependencies)
        self.context.task_order = order

        # Inicializar métricas
        for task_name, domain in tasks.items():
            self.context.tasks[task_name] = TaskExecutionMetrics(
                task_id=f"{self.context.analysis_id}_{task_name}",
                task_name=task_name,
                domain=domain,
            )

        return order

    def execute_task(
        self,
        task_name: str,
        executor: Callable,
        *args,
        **kwargs,
    ) -> Tuple[bool, Any]:
        """
        Executa uma tarefa com delegação e fallback.

        Retorna: (sucesso, resultado)
        """
        if not self.context or task_name not in self.context.tasks:
            raise ValueError(f"Tarefa '{task_name}' não definida no contexto")

        metrics = self.context.tasks[task_name]
        metrics.status = TaskStatus.RUNNING
        metrics.started_at_utc = datetime.now(timezone.utc).isoformat()

        try:
            # Executar com delegação se aplicável
            result = self._execute_with_delegation(
                task_name, executor, *args, **kwargs
            )

            metrics.status = TaskStatus.COMPLETED
            metrics.finished_at_utc = datetime.now(timezone.utc).isoformat()
            metrics.duration_ms = (
                (datetime.fromisoformat(metrics.finished_at_utc.replace('Z', '+00:00')) -
                 datetime.fromisoformat(metrics.started_at_utc.replace('Z', '+00:00'))).total_seconds() * 1000
            )

            # Registrar na auditoria
            self._audit_log(f"task_completed:{task_name}", metrics.to_dict())

            return True, result

        except Exception as exc:
            error_msg = str(exc)
            metrics.errors.append(error_msg)
            metrics.status = TaskStatus.FAILED
            metrics.finished_at_utc = datetime.now(timezone.utc).isoformat()

            logger.error(f"Falha na tarefa '{task_name}': {error_msg}", exc_info=True)
            self._audit_log(f"task_failed:{task_name}", {
                'error': error_msg,
                'task_id': metrics.task_id,
            })

            return False, None

    def _execute_with_delegation(
        self,
        task_name: str,
        executor: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """Executa tarefa com tentativa de delegação ao pipeline legado."""
        if not self.enable_delegations or not self.legacy_ocr_agent:
            return executor(*args, **kwargs)

        metrics = self.context.tasks[task_name]

        try:
            # Tentar delegação
            result = self._delegate_to_legacy_engine(task_name, *args, **kwargs)
            metrics.delegated = True
            metrics.delegated_engine = "ocr_agent_flask"
            metrics.status = TaskStatus.DELEGATED
            return result

        except Exception as delegate_exc:
            # Fallback para executor local
            logger.warning(
                f"Delegação falhou para '{task_name}': {delegate_exc}. "
                f"Executando fallback local...",
            )
            metrics.fallback_used = True
            metrics.fallback_reason = str(delegate_exc)
            metrics.warnings.append(f"delegacao_fallback:{delegate_exc}")
            metrics.status = TaskStatus.FALLBACK

            return executor(*args, **kwargs)

    def _delegate_to_legacy_engine(self, task_name: str, *args, **kwargs) -> Any:
        """Delega tarefa ao pipeline forense legado (ocr_agent)."""
        if not self.legacy_ocr_agent or not hasattr(self.legacy_ocr_agent, 'app'):
            raise RuntimeError("Pipeline legado não disponível")

        # Criar cliente de teste do Flask
        client = self.legacy_ocr_agent.app.test_client()

        # Mapear tarefas para endpoints legacy
        endpoint_map = {
            'detect': '/detect-plate',
            'ocr': '/process',
            'full_pipeline': '/process',
            'ensemble': '/process-ensemble',
        }

        endpoint = endpoint_map.get(task_name)
        if not endpoint:
            raise ValueError(f"Nenhuma delegação mapeada para tarefa '{task_name}'")

        # Para tarefas que envolvem arquivo
        if args and hasattr(args[0], 'file'):
            upload_file = args[0]
            upload_bytes = upload_file.file.read()
            upload_file.file.seek(0)

            response = client.post(
                endpoint,
                data={
                    'analysis_stage': kwargs.get('analysis_stage', 'final'),
                    'image': (io.BytesIO(upload_bytes), upload_file.filename or 'image.jpg'),
                },
                content_type='multipart/form-data',
            )

            payload = response.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ValueError(f"Resposta inválida do pipeline legado: {response.status_code}")

            return payload

        raise ValueError(f"Não foi possível delegar tarefa '{task_name}'")

    def consolidate_results(self) -> Dict[str, Any]:
        """Consolida resultados de todas as tarefas."""
        if not self.context:
            return {}

        report = {
            'analysis_id': self.context.analysis_id,
            'analysis_stage': self.context.analysis_stage,
            'source_filename': self.context.source_filename,
            'created_at_utc': self.context.created_at_utc,
            'execution_summary': {
                'total_tasks': len(self.context.tasks),
                'completed': sum(1 for t in self.context.tasks.values() if t.status == TaskStatus.COMPLETED),
                'delegated': sum(1 for t in self.context.tasks.values() if t.delegated),
                'fallback_used': sum(1 for t in self.context.tasks.values() if t.fallback_used),
                'failed': sum(1 for t in self.context.tasks.values() if t.status == TaskStatus.FAILED),
            },
            'tasks': {name: task.to_dict() for name, task in self.context.tasks.items()},
            'quality_gates': self.context.quality_gates_passed,
            'audit_trail': self.context.audit_trail[-20:],  # Últimos 20 eventos
        }

        # Mesclar resultados delegados
        if self.context.delegated_results:
            report['delegated_results'] = self.context.delegated_results

        if self.context.fallback_results:
            report['fallback_results'] = self.context.fallback_results

        # Mesclar payload enriquecido
        if self.context.enriched_payload:
            report['enriched_payload'] = self.context.enriched_payload

        return report

    def _audit_log(self, event: str, details: Dict[str, Any]) -> None:
        """Registra evento na cadeia de auditoria."""
        if not self.context:
            return

        audit_entry = {
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'analysis_id': self.context.analysis_id,
            'event': event,
            'details': details,
        }
        self.context.audit_trail.append(audit_entry)
        logger.info(f"[AUDIT] {event}: {json.dumps(details)}")

    @staticmethod
    def _has_cycle(nodes: Dict, edges: Dict) -> bool:
        """Verifica se há ciclo no grafo de dependências."""
        visited = set()
        rec_stack = set()

        def dfs(node):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in edges.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in nodes:
            if node not in visited:
                if dfs(node):
                    return True

        return False

    @staticmethod
    def _topological_sort(nodes: Dict, edges: Dict) -> List[str]:
        """Retorna ordem topológica de nós baseada em dependências."""
        from collections import deque

        in_degree = {node: 0 for node in nodes}
        adj = {node: [] for node in nodes}

        for node, deps in edges.items():
            for dep in deps:
                adj[dep].append(node)
                in_degree[node] += 1

        queue = deque([node for node in nodes if in_degree[node] == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)

            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result


# Instância global
_global_orchestrator: Optional[ForensicOrchestrator] = None


def get_global_orchestrator() -> ForensicOrchestrator:
    """Obtém instância global do orquestrador."""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = ForensicOrchestrator()
    return _global_orchestrator


def init_global_orchestrator(legacy_ocr_agent=None, enable_delegations: bool = True):
    """Inicializa orquestrador global."""
    global _global_orchestrator
    _global_orchestrator = ForensicOrchestrator(
        legacy_ocr_agent=legacy_ocr_agent,
        enable_delegations=enable_delegations,
    )
    return _global_orchestrator
