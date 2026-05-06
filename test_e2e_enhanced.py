#!/usr/bin/env python3
"""Teste E2E dos novos módulos integrados ao /process endpoint."""

import requests
import json
import time
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
TEST_IMAGE = "data/datasets/Imagens/fiat.jpg"

def wait_for_api():
    """Aguarda API estar pronta."""
    for i in range(15):
        try:
            requests.get(f"{BASE_URL}/health", timeout=2)
            return True
        except:
            if i < 14:
                time.sleep(1)
    return False

def test_process_with_validation():
    """Testa /process com validação integrada."""
    print("\n[TESTE] Endpoint /process com validação + qualidade + confiança")
    print("-" * 70)

    if not Path(TEST_IMAGE).exists():
        print(f"✗ Imagem de teste não encontrada: {TEST_IMAGE}")
        return False

    try:
        with open(TEST_IMAGE, "rb") as f:
            files = {"image": (TEST_IMAGE, f, "image/jpeg")}
            r = requests.post(f"{BASE_URL}/process", files=files, timeout=30)

        if r.status_code != 200:
            print(f"✗ Erro HTTP: {r.status_code}")
            print(f"Resposta: {r.text[:200]}")
            return False

        data = r.json()

        # Campos esperados
        required_fields = [
            'best', 'detections', 'ocr_engine_status',
            'plate_validation', 'image_quality', 'confidence_score'
        ]

        for field in required_fields:
            if field not in data:
                print(f"✗ Campo faltante: {field}")
                return False

        # Exibe resultados
        print(f"\n✅ Resposta recebida com sucesso")

        best_text = data['best'].get('text', '').strip()
        if best_text:
            print(f"\n📄 Resultado OCR:")
            print(f"   Placa: {best_text}")
            print(f"   Engine: {data['best'].get('engine', 'unknown')}")
            print(f"   Confiança OCR: {data['best'].get('avg_conf', 0):.2f}")
        else:
            print(f"\n⚠️  Sem detecção de placa na imagem")

        print(f"\n🔍 Validação de Placa:")
        pv = data['plate_validation']
        print(f"   Válida: {pv.get('valid', False)}")
        print(f"   Padrão: {pv.get('pattern', 'unknown')}")
        print(f"   Score: {pv.get('score', 0):.2f}")
        if pv.get('issues'):
            print(f"   Problemas: {pv['issues']}")

        print(f"\n🖼️  Qualidade de Imagem:")
        iq = data['image_quality']
        print(f"   Score Geral: {iq.get('overall_quality_score', 0):.2f}")
        print(f"   Blur: {iq.get('blur_level', 'unknown')}")
        print(f"   Rotação: {iq.get('rotation_angle', 0):.1f}°")
        print(f"   Resolução: {iq.get('resolution_category', 'unknown')}")

        print(f"\n✔️  Confiança Integrada:")
        cs = data['confidence_score']
        print(f"   Score: {cs.get('overall_confidence', 0):.2f}")
        print(f"   Nível: {cs.get('confidence_level', 'unknown')}")
        print(f"   Aceitar: {cs.get('accept', False)}")
        print(f"   Recomendação: {cs.get('recommendation', '')}")

        print(f"\n📊 Componentes:")
        comps = cs.get('component_scores', {})
        print(f"   Detecção: {comps.get('detection', 0):.2f}")
        print(f"   OCR: {comps.get('ocr', 0):.2f}")
        print(f"   Validação: {comps.get('validation', 0):.2f}")
        print(f"   Qualidade: {comps.get('quality', 0):.2f}")

        print(f"\n🔧 Assessment Atualizado:")
        assess = data.get('assessment', {})
        print(f"   Nível Confiança: {assess.get('confidence_level', 'unknown')}")
        print(f"   Revisão Necessária: {assess.get('manual_review_required', False)}")

        return True

    except Exception as e:
        print(f"✗ Erro: {e}")
        return False

def main():
    print("=" * 70)
    print("TESTE E2E - SISTEMA ALPR APRIMORADO")
    print("=" * 70)

    print("\n[0] Aguardando API...")
    if not wait_for_api():
        print("✗ API não respondeu. Abortando.")
        return False
    print("✅ API pronta")

    success = test_process_with_validation()

    print("\n" + "=" * 70)
    if success:
        print("✅ TESTE COMPLETADO COM SUCESSO")
    else:
        print("❌ TESTE FALHOU")
    print("=" * 70)

    return success

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
