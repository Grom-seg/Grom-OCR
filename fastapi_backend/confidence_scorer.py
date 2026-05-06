"""
Scorer de confiança integrado.
Combina qualidade de imagem + detecção + OCR + validação em um único score.
"""
from typing import Dict, Any, List
import numpy as np

class ConfidenceScorer:
    """
    Scoring integrado de confiança.
    Combina múltiplas fontes de certeza em score 0-1.
    """

    def __init__(self):
        """Inicializa pesos e tresholds."""
        # Pesos para componentes
        self.weights = {
            'detection_confidence': 0.30,  # YOLOv8 bbox confidence
            'ocr_confidence': 0.25,         # PaddleOCR / Tesseract confidence
            'plate_validation': 0.25,       # Validação de padrão + check-digit
            'image_quality': 0.20,          # Qualidade de imagem (blur, contraste)
        }

        # Tresholds por nível de confiança
        self.thresholds = {
            'high': 0.85,      # Altamente confiável, aceitar sem revisão
            'medium': 0.65,    # Revisar antes de usar
            'low': 0.45,       # Descartar ou revisão manual obrigatória
            'reject': 0.0,     # Rejeitar completamente
        }

    def calculate(
        self,
        detection_confidence: float,
        ocr_confidence: float,
        plate_validation: Dict[str, Any],
        image_quality: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calcula score de confiança integrado.

        Args:
            detection_confidence: Confiança do detector YOLOv8 (0-1)
            ocr_confidence: Confiança do OCR (0-1)
            plate_validation: Dict com resultado de validate_plate()
            image_quality: Dict com resultado de analyze_image_quality()

        Returns:
            {
                'overall_confidence': float,
                'confidence_level': str (high, medium, low, reject),
                'component_scores': {
                    'detection': float,
                    'ocr': float,
                    'validation': float,
                    'quality': float,
                },
                'recommendation': str,
                'accept': bool,
                'requires_review': bool,
                'reason': str,
            }
        """

        # Normaliza inputs
        det_score = max(0.0, min(1.0, detection_confidence))
        ocr_score = max(0.0, min(1.0, ocr_confidence))

        # Extrai scores dos dicts
        validation_score = plate_validation.get('score', 0.0)
        quality_score = image_quality.get('overall_quality_score', 0.5)

        # Score integrado (ponderado)
        overall_confidence = (
            det_score * self.weights['detection_confidence'] +
            ocr_score * self.weights['ocr_confidence'] +
            validation_score * self.weights['plate_validation'] +
            quality_score * self.weights['image_quality']
        )

        # Classficação
        if overall_confidence >= self.thresholds['high']:
            confidence_level = 'high'
        elif overall_confidence >= self.thresholds['medium']:
            confidence_level = 'medium'
        elif overall_confidence >= self.thresholds['low']:
            confidence_level = 'low'
        else:
            confidence_level = 'reject'

        # Decisão de aceitação
        accept = overall_confidence >= self.thresholds['medium']
        requires_review = (self.thresholds['low'] <= overall_confidence < self.thresholds['high'])

        # Motivo detalhado
        reason = self._generate_reason(
            det_score, ocr_score, validation_score, quality_score,
            plate_validation, image_quality
        )

        # Recomendação de ação
        recommendation = self._generate_recommendation(confidence_level, reason)

        return {
            'overall_confidence': float(overall_confidence),
            'confidence_level': confidence_level,
            'component_scores': {
                'detection': float(det_score),
                'ocr': float(ocr_score),
                'validation': float(validation_score),
                'quality': float(quality_score),
            },
            'recommendation': recommendation,
            'accept': accept,
            'requires_review': requires_review,
            'reason': reason,
        }

    def _generate_reason(
        self,
        det_score: float,
        ocr_score: float,
        validation_score: float,
        quality_score: float,
        plate_validation: Dict,
        image_quality: Dict
    ) -> str:
        """Gera motivo descritivo do score."""

        components = []

        # Detecção
        if det_score < 0.5:
            components.append(f'detecção fraca ({det_score:.2f})')
        elif det_score < 0.7:
            components.append(f'detecção moderada ({det_score:.2f})')

        # OCR
        if ocr_score < 0.5:
            components.append(f'OCR fraco ({ocr_score:.2f})')
        elif ocr_score < 0.7:
            components.append(f'OCR moderado ({ocr_score:.2f})')

        # Validação
        if not plate_validation.get('valid', False):
            issues = plate_validation.get('issues', [])
            if issues:
                components.append(f'validação inválida: {issues[0]}')
            else:
                components.append('padrão de placa inválido')
        elif validation_score < 0.7:
            components.append(f'validação fraca ({validation_score:.2f})')
            if plate_validation.get('suspicious_chars'):
                components.append(f"{len(plate_validation['suspicious_chars'])} chars suspeitos")

        # Qualidade
        if image_quality.get('issues'):
            components.append(f"qualidade: {image_quality['issues'][0]}")
        elif quality_score < 0.5:
            blur = image_quality.get('blur_level', 'unknown')
            components.append(f'qualidade fraca (blur={blur})')

        if components:
            return '; '.join(components)
        else:
            return 'Resultado válido e confiável'

    def _generate_recommendation(self, confidence_level: str, reason: str) -> str:
        """Gera recomendação de ação."""

        if confidence_level == 'high':
            return '✅ ACEITAR: Resultado altamente confiável. Usar diretamente.'
        elif confidence_level == 'medium':
            return '⚠️ REVISAR: Resultado moderadamente confiável. Recomenda-se revisão antes de usar.'
        elif confidence_level == 'low':
            return '❌ REVISAR MANUALMENTE: Resultado de baixa confiança. Inspeção humana recomendada.'
        else:  # reject
            return '❌ REJEITAR: Resultado não confiável. Não usar. Tentar re-capturar imagem.'

    def batch_score(self, results_list: List[Dict]) -> Dict:
        """
        Calcula scores para lote de resultados.

        Args:
            results_list: Lista de dicts com chaves
                {detection_confidence, ocr_confidence, plate_validation, image_quality}

        Returns:
            {
                'total': int,
                'high_confidence': int,
                'medium_confidence': int,
                'low_confidence': int,
                'rejected': int,
                'average_confidence': float,
                'results': List[Dict],
            }
        """

        scores = []
        stats = {
            'total': len(results_list),
            'high_confidence': 0,
            'medium_confidence': 0,
            'low_confidence': 0,
            'rejected': 0,
            'average_confidence': 0.0,
        }

        confidence_sum = 0.0

        for result in results_list:
            score = self.calculate(
                result.get('detection_confidence', 0.0),
                result.get('ocr_confidence', 0.0),
                result.get('plate_validation', {}),
                result.get('image_quality', {}),
            )

            scores.append(score)
            confidence_sum += score['overall_confidence']

            # Contabiliza por nível
            if score['confidence_level'] == 'high':
                stats['high_confidence'] += 1
            elif score['confidence_level'] == 'medium':
                stats['medium_confidence'] += 1
            elif score['confidence_level'] == 'low':
                stats['low_confidence'] += 1
            else:
                stats['rejected'] += 1

        if stats['total'] > 0:
            stats['average_confidence'] = confidence_sum / stats['total']

        stats['results'] = scores

        return stats


def score_result(
    detection_conf: float,
    ocr_conf: float,
    plate_validation: Dict,
    image_quality: Dict
) -> Dict:
    """Conveniência: calcular score de um resultado."""
    scorer = ConfidenceScorer()
    return scorer.calculate(detection_conf, ocr_conf, plate_validation, image_quality)


# Exemplo
if __name__ == '__main__':
    scorer = ConfidenceScorer()

    # Exemplo 1: Resultado bom
    result1 = scorer.calculate(
        detection_confidence=0.92,
        ocr_confidence=0.88,
        plate_validation={'score': 0.95, 'valid': True, 'issues': []},
        image_quality={'overall_quality_score': 0.85}
    )

    print("=== Resultado 1 (Bom) ===")
    print(f"Confiança: {result1['overall_confidence']:.2f} ({result1['confidence_level']})")
    print(f"Recomendação: {result1['recommendation']}")
    print(f"Aceitar: {result1['accept']}")
    print()

    # Exemplo 2: Resultado moderado
    result2 = scorer.calculate(
        detection_confidence=0.72,
        ocr_confidence=0.65,
        plate_validation={'score': 0.70, 'valid': True, 'suspicious_chars': [(0, 'O', ['0'])]},
        image_quality={'overall_quality_score': 0.60}
    )

    print("=== Resultado 2 (Moderado) ===")
    print(f"Confiança: {result2['overall_confidence']:.2f} ({result2['confidence_level']})")
    print(f"Recomendação: {result2['recommendation']}")
    print(f"Requer revisão: {result2['requires_review']}")
    print()

    # Exemplo 3: Resultado fraco
    result3 = scorer.calculate(
        detection_confidence=0.42,
        ocr_confidence=0.38,
        plate_validation={'score': 0.35, 'valid': False, 'issues': ['Padrão inválido']},
        image_quality={'overall_quality_score': 0.30}
    )

    print("=== Resultado 3 (Fraco) ===")
    print(f"Confiança: {result3['overall_confidence']:.2f} ({result3['confidence_level']})")
    print(f"Recomendação: {result3['recommendation']}")
    print(f"Motivo: {result3['reason']}")
