#!/usr/bin/env python3
"""Teste rápido dos novos módulos de qualidade/validação."""

from fastapi_backend.plate_validator import PlateValidator
from fastapi_backend.quality_metrics import ImageQualityAnalyzer
from fastapi_backend.confidence_scorer import ConfidenceScorer

print("=" * 60)
print("TESTE DOS NOVOS MÓDULOS - FASE 1")
print("=" * 60)

# Test 1: Validador de placa
print("\n[1] Validador de Placa")
print("-" * 60)
validator = PlateValidator(strict_mode=False)

test_plates = [
    'ABC1234',      # Válido
    'ABCD123',      # Válido
    'ABC1D23',      # Mercosul válido
    '0BC1D23',      # Inválido
    'ABCDEFGH',     # Muito longo
]

for plate in test_plates:
    result = validator.validate(plate)
    print(f"{plate:10} → {result['pattern']:12} (score: {result['score']:.2f}, válida: {result['valid']})")

# Test 2: Confidence Scorer
print("\n[2] Confidence Scorer")
print("-" * 60)
scorer = ConfidenceScorer()

test_scores = [
    {'name': 'Excelente', 'det': 0.92, 'ocr': 0.88, 'val': 0.95, 'qual': 0.85},
    {'name': 'Moderado', 'det': 0.72, 'ocr': 0.65, 'val': 0.70, 'qual': 0.60},
    {'name': 'Fraco', 'det': 0.42, 'ocr': 0.38, 'val': 0.35, 'qual': 0.30},
]

for test in test_scores:
    result = scorer.calculate(
        test['det'], test['ocr'],
        {'score': test['val'], 'valid': test['val'] > 0.5},
        {'overall_quality_score': test['qual']}
    )
    print(f"{test['name']:12} → {result['overall_confidence']:.2f} ({result['confidence_level']:6}) | {result['accept']}")

# Test 3: Análise de imagem (se arquivo existe)
print("\n[3] Análise de Qualidade de Imagem")
print("-" * 60)

import os
analyzer = ImageQualityAnalyzer()

test_image = 'data/datasets/Imagens/fiat.jpg'
if os.path.exists(test_image):
    result = analyzer.analyze(test_image)
    print(f"Imagem: {test_image}")
    print(f"  Blur: {result['blur_level']} ({result['blur_score']:.2f})")
    print(f"  Rotação: {result['rotation_angle']:.1f}°")
    print(f"  Contraste: {result['contrast_score']:.2f}")
    print(f"  Brilho: {result['brightness_level']}")
    print(f"  Resolução: {result['resolution_category']} ({result['resolution_dimensions']})")
    print(f"  Score Geral: {result['overall_quality_score']:.2f}")
    if result['issues']:
        print(f"  Problemas: {result['issues']}")
else:
    print(f"Imagem de teste não encontrada: {test_image}")

print("\n" + "=" * 60)
print("TESTES CONCLUÍDOS COM SUCESSO")
print("=" * 60)
