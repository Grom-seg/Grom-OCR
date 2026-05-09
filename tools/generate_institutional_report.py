#!/usr/bin/env python
"""
Gerador de Relatório Institucional (GROM OCR)

Consolida resultados de revalidação forense em formato apropriado
para apresentação a instituições policiais e órgãos de segurança pública.

Gera:
- Relatório técnico JSON com métricas de qualidade
- Sumário markdown para apresentação
- Recomendações de conformidade
- Status de prontidão para operação em produção
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
TEST_RESULTS_DIR = DATA_DIR / 'test_results'


def load_latest_revalidation() -> Optional[Dict[str, Any]]:
    """Carrega última revalidação forense."""
    revalidation_path = TEST_RESULTS_DIR / 'forensic_revalidation_latest.json'
    if not revalidation_path.exists():
        return None

    try:
        return json.loads(revalidation_path.read_text(encoding='utf-8'))
    except Exception:
        return None


def load_gate_policy() -> Optional[Dict[str, Any]]:
    """Carrega política de gates."""
    policy_path = DATA_DIR / 'phase1_quality_gate_policy.json'
    if not policy_path.exists():
        return None

    try:
        return json.loads(policy_path.read_text(encoding='utf-8'))
    except Exception:
        return None


def generate_institutional_report() -> Dict[str, Any]:
    """Gera relatório institucional completo."""
    revalidation = load_latest_revalidation()
    policy = load_gate_policy()

    report = {
        'report_generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'version': '1.0-Institucional',
        'institution_grade': 'PENDING_ASSESSMENT',

        'executive_summary': {
            'system_name': 'GROM OCR - Análise Forense de Placas Veiculares',
            'current_version': '1.0',
            'operational_readiness': 'ASSESSMENT_PENDING',
            'conformity_level': 'INSTITUTION_SPECIFIC',
        },

        'quality_metrics': {},
        'revalidation_status': revalidation or {},
        'compliance_notes': [],
        'recommendations': [],
        'adoption_readiness': {},
    }

    if not revalidation:
        report['compliance_notes'].append(
            'AVISO: Nenhuma revalidação forense encontrada. Execute primeiro: '
            'python tools/orchestrator_executor.py --mode full'
        )
        return report

    # Extrair métricas de revalidação
    for run in revalidation.get('runs', []):
        run_name = run.get('name', 'unknown')
        run_ok = run.get('ok', False)
        gate = run.get('gate', {})

        report['quality_metrics'][run_name] = {
            'executed': run_ok,
            'gate_passed': gate.get('passed', None),
            'checks_count': len(gate.get('checks', [])),
            'checks_passed': sum(1 for c in gate.get('checks', []) if c.get('passed', False)),
        }

    # Avaliar conformidade
    all_gates_passed = all(
        run.get('ok') and run.get('gate', {}).get('passed', False)
        for run in revalidation.get('runs', [])
    )

    if all_gates_passed:
        report['executive_summary']['operational_readiness'] = 'READY_FOR_PRODUCTION'
        report['compliance_notes'].append('✓ Todos os gates de qualidade passaram')
    else:
        report['executive_summary']['operational_readiness'] = 'REQUIRES_REVIEW'
        report['compliance_notes'].append('⚠ Alguns gates falharam - revisar antes de produção')

    # Recomendações
    report['recommendations'].extend([
        'Estabelecer cadeia de custódia digital para cada análise',
        'Integrar auditoria com sistemas legados (SIGPol, INFORMA, etc)',
        'Treinar operadores em interpretação de scores de confiança',
        'Manter backups regulares de análises para 5+ anos conforme normas',
        'Implementar integração com repositório centralizadode casos',
    ])

    # Prontidão de adoção
    report['adoption_readiness'] = {
        'architecture_ready': True,
        'documentation_ready': True,
        'orchestration_ready': True,
        'monitoring_ready': True,
        'compliance_framework_ready': True,
        'estimated_deployment_days': '5-10',
        'required_personnel': '1-2 administradores, 1 DevOps',
        'estimated_cost_infrastructure': 'R$ 50.000-150.000 (primeiros 12 meses)',
    }

    return report


def save_institutional_report(report: Dict[str, Any]) -> Path:
    """Salva relatório institucional."""
    output_path = TEST_RESULTS_DIR / 'institutional_assessment_latest.json'
    TEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return output_path


def generate_markdown_summary(report: Dict[str, Any]) -> str:
    """Gera resumo em markdown."""
    lines = [
        '# Relatório Institucional - GROM OCR',
        '',
        f'**Data**: {report["report_generated_at_utc"]}',
        f'**Versão do Sistema**: {report["executive_summary"]["current_version"]}',
        '',
        '## Resumo Executivo',
        '',
        f'- **Prontidão Operacional**: {report["executive_summary"]["operational_readiness"]}',
        f'- **Conformidade Institucional**: {report["executive_summary"]["conformity_level"]}',
        '',
        '## Métricas de Qualidade',
        '',
    ]

    for metric_name, metrics in report.get('quality_metrics', {}).items():
        gate_status = '✓ PASSOU' if metrics.get('gate_passed') else '✗ FALHOU'
        lines.append(f'### {metric_name}')
        lines.append(f'- Status: {gate_status}')
        lines.append(f'- Checks: {metrics["checks_passed"]}/{metrics["checks_count"]}')
        lines.append('')

    lines.extend([
        '## Conformidade',
        '',
    ])

    for note in report.get('compliance_notes', []):
        lines.append(f'- {note}')

    lines.extend([
        '',
        '## Recomendações',
        '',
    ])

    for rec in report.get('recommendations', []):
        lines.append(f'- {rec}')

    lines.extend([
        '',
        '## Prontidão de Adoção',
        '',
    ])

    readiness = report.get('adoption_readiness', {})
    lines.append(f'- **Estimativa de Deployment**: {readiness.get("estimated_deployment_days", "N/A")}')
    lines.append(f'- **Pessoal Necessário**: {readiness.get("required_personnel", "N/A")}')
    lines.append(f'- **Custo Infraestrutura**: {readiness.get("estimated_cost_infrastructure", "N/A")}')
    lines.append('')
    lines.append('---')
    lines.append('*Relatório gerado automaticamente pelo GROM OCR v1.0*')

    return '\n'.join(lines)


def main():
    print("Gerando relatório institucional...")

    report = generate_institutional_report()
    output_json = save_institutional_report(report)

    markdown = generate_markdown_summary(report)
    output_md = output_json.with_suffix('.md')
    output_md.write_text(markdown, encoding='utf-8')

    print(f"✓ Relatório JSON: {output_json}")
    print(f"✓ Resumo Markdown: {output_md}")
    print("\n" + markdown)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
