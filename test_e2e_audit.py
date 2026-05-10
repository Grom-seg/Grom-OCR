#!/usr/bin/env python3
"""
Teste E2E completo do pipeline OCR: diagnostica estado real do sistema
"""
import sys
import os
import json
from pathlib import Path

# Adiciona fastapi_backend ao path
sys.path.insert(0, str(Path(__file__).parent))

print("[AUDITORIA E2E] Iniciando diagnostico completo do pipeline OCR\n")

# 1. Verifica se dependencies estão disponíveis
print("=" * 80)
print("ETAPA 1: Verificando dependências")
print("=" * 80)
try:
    from fastapi_backend.main import app, detect_plate, run_ocr, _build_process_payload, _enrich_payload_with_validation, analyze_vehicle
    print("✓ FastAPI backend carregado com sucesso")
except Exception as e:
    print(f"✗ Erro ao carregar FastAPI: {e}")
    sys.exit(1)

try:
    from PIL import Image
    print("✓ PIL disponível")
except:
    print("✗ PIL não disponível")

# 2. Verifica arquivos de teste
print("\n" + "=" * 80)
print("ETAPA 2: Localizando imagens de teste")
print("=" * 80)

test_image_path = Path("test-assets/plate_test.png")
if not test_image_path.exists():
    print(f"✗ Imagem de teste não encontrada: {test_image_path}")
    sys.exit(1)
print(f"✓ Imagem de teste localizada: {test_image_path}")
print(f"  Tamanho: {test_image_path.stat().st_size / 1024:.1f} KB")

# 3. Detecção de placas
print("\n" + "=" * 80)
print("ETAPA 3: Testando detecção de placas")
print("=" * 80)

from fastapi_backend.preprocessing import preprocess_image
print(f"Preprocessando imagem...")
img = Image.open(test_image_path)
print(f"  Dimensões originais: {img.size}")

tmp_test_path = "/tmp/test_preprocess.jpg"
preprocess_image(str(test_image_path)).save(tmp_test_path)
print(f"✓ Imagem preprocessada")

print(f"Detectando placas...")
detections = detect_plate(tmp_test_path)
print(f"✓ Detecções encontradas: {len(detections)}")
for i, det in enumerate(detections, 1):
    print(f"  [{i}] bbox={det.get('bbox')} | conf={det.get('confidence', 0):.3f} | priority_rank={det.get('priority_rank', '?')}")

if not detections:
    print("✗ PROBLEMA: Nenhuma placa foi detectada!")

# 4. OCR em cada região
print("\n" + "=" * 80)
print("ETAPA 4: Testando OCR em regiões detectadas")
print("=" * 80)

ocr_results = []
if detections:
    for i, det in enumerate(detections, 1):
        x1, y1, x2, y2 = det['bbox']
        crop_path = f"/tmp/crop_{i}.jpg"
        img.crop((x1, y1, x2, y2)).save(crop_path)

        print(f"\n  Região {i}: bbox={det['bbox']}")
        try:
            local_ocr = run_ocr(crop_path)
            print(f"    ✓ OCR executado: {len(local_ocr)} candidatos")
            for j, candidate in enumerate(local_ocr[:3], 1):
                print(f"      [{j}] {candidate.get('text', '?')} | engine={candidate.get('engine', '?')} | conf={candidate.get('confidence', 0):.3f}")
                candidate['bbox'] = det.get('bbox')
                candidate['detection_priority_rank'] = det.get('priority_rank', 99)
                candidate['detection_priority_score'] = det.get('priority_score', 0.0)
                ocr_results.append(candidate)
        except Exception as e:
            print(f"    ✗ OCR falhou: {e}")
else:
    print("  Pulando: nenhuma detecção anterior")

print(f"\nTotal OCR results consolidados: {len(ocr_results)}")

# 5. Construir payload
print("\n" + "=" * 80)
print("ETAPA 5: Construindo payload pericial")
print("=" * 80)

from uuid import uuid4
analysis_id = str(uuid4())
print(f"Analysis ID: {analysis_id}")

try:
    payload = _build_process_payload(
        filename="test_image.png",
        detections=detections,
        ocr_results=ocr_results,
        analysis_stage="preview",
        analysis_id=analysis_id,
        photo_filename="photo_test.jpg",
        plate_filename="plate_test.jpg",
        crop_raw_filename="crop_test.jpg",
        ocr_runtime_info={},
        ocr_runtime_events=[],
        vehicle_info_seed={},
    )
    print("✓ Payload construído com sucesso")

    # Verifica campos críticos
    print("\n  Campos críticos do payload:")
    print(f"    - best.text: '{payload.get('best', {}).get('text', '')}'")
    print(f"    - best.score: {payload.get('best', {}).get('score', 0):.3f}")
    print(f"    - consensus.agreement_ratio: {payload.get('consensus', {}).get('agreement_ratio', 0)}")
    print(f"    - consensus.basis: {payload.get('consensus', {}).get('basis', '?')}")
    print(f"    - top_candidates: {len(payload.get('top_candidates', []))}")
    print(f"    - ocr_engine_summary.engines_executed: {payload.get('ocr_engine_summary', {}).get('engines_executed', [])}")
    print(f"    - warnings: {payload.get('warnings', [])}")

except Exception as e:
    print(f"✗ Erro ao construir payload: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 6. Enriquecimento
print("\n" + "=" * 80)
print("ETAPA 6: Enriquecimento com validação")
print("=" * 80)

try:
    enriched_payload = _enrich_payload_with_validation(payload, str(test_image_path))
    print("✓ Payload enriquecido com sucesso")

    print("\n  Campos após enriquecimento:")
    print(f"    - assessment.evidence_level: {enriched_payload.get('assessment', {}).get('evidence_level', '?')}")
    print(f"    - pericial.status: {enriched_payload.get('pericial', {}).get('status', '?')}")
    print(f"    - confidence_score.overall_confidence: {enriched_payload.get('confidence_score', {}).get('overall_confidence', 0):.3f}")
    print(f"    - image_quality.overall_quality_score: {enriched_payload.get('image_quality', {}).get('overall_quality_score', 0):.3f}")
    print(f"    - plate_validation.valid: {enriched_payload.get('plate_validation', {}).get('valid', '?')}")

except Exception as e:
    print(f"✗ Erro ao enriquecer: {e}")
    import traceback
    traceback.print_exc()

# 7. Análise de veículos
print("\n" + "=" * 80)
print("ETAPA 7: Análise veicular complementar")
print("=" * 80)

try:
    vehicle_analysis = analyze_vehicle(str(test_image_path))
    if vehicle_analysis:
        print("✓ Análise veicular executada")
        vehicles = vehicle_analysis.get('vehicle_detections', [])
        print(f"  Veículos detectados: {len(vehicles)}")
        for v in vehicles[:3]:
            print(f"    - {v.get('class_name', '?')}: bbox={v.get('bbox')} | conf={v.get('confidence', 0):.3f}")
    else:
        print("✗ Nenhuma análise veicular disponível")
except Exception as e:
    print(f"✗ Erro em análise veicular: {e}")

# 8. Resumo
print("\n" + "=" * 80)
print("RESUMO DA AUDITORIA")
print("=" * 80)

print(f"""
STATUS DO PIPELINE:
  ✓ Backend carregado
  ✓ Imagem de teste disponível
  {'✓' if detections else '✗'} Detecção de placas: {len(detections)} região(ões)
  {'✓' if ocr_results else '✗'} OCR executado: {len(ocr_results)} resultado(s)
  {'✓' if payload.get('best', {}).get('text') else '✗'} Melhor candidato identificado
  {'✓' if enriched_payload.get('assessment', {}).get('evidence_level') else '✗'} Nível de evidência atribuído

PROBLEMAS IDENTIFICADOS:
""")

issues = []
if not detections:
    issues.append("- Nenhuma placa detectada (detector falhou ou imagem sem placas)")
if not ocr_results:
    issues.append("- Nenhum OCR executado (OCR falhou em todas as regiões)")
if not payload.get('best', {}).get('text'):
    issues.append("- Nenhum candidato plausível identificado")
if payload.get('consensus', {}).get('agreement_ratio', 0) == 100 and len(payload.get('ocr_engine_summary', {}).get('engines_executed', [])) == 1:
    issues.append("- Consenso falso (100% com apenas um motor)")
if not enriched_payload.get('pericial', {}).get('status') or enriched_payload.get('pericial', {}).get('status') == 'INCONCLUSIVO':
    issues.append("- Status pericial inconclusivo")

if issues:
    for issue in issues:
        print(issue)
else:
    print("  ✓ Nenhum problema crítico identificado no pipeline")

print("\n" + "=" * 80)
print("FIM DA AUDITORIA")
print("=" * 80)

# Salva resultado JSON para análise
result_file = Path("audit_result.json")
with open(result_file, "w", encoding="utf-8") as f:
    json.dump({
        "analysis_id": analysis_id,
        "detections_count": len(detections),
        "ocr_results_count": len(ocr_results),
        "best_text": payload.get('best', {}).get('text', ''),
        "best_score": float(payload.get('best', {}).get('score', 0)),
        "consensus": payload.get('consensus', {}),
        "engines_executed": payload.get('ocr_engine_summary', {}).get('engines_executed', []),
        "warnings": payload.get('warnings', []),
        "assessment": enriched_payload.get('assessment', {}),
        "pericial_status": enriched_payload.get('pericial', {}).get('status', ''),
        "confidence_score": enriched_payload.get('confidence_score', {}),
    }, f, indent=2, ensure_ascii=False)

print(f"\nResultado salvo em: {result_file}")
