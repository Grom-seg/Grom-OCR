import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

from utils import vehicle_analysis_protocol as protocol  # noqa: E402


class OperationalProtocolConsistencyTests(unittest.TestCase):
    def test_strong_ocr_can_remain_conclusive_without_manual_review(self):
        built = protocol.build_operational_protocol({
            'best_payload': {
                'text': 'REI5G32',
                'avg_conf': 87.8,
                'score': 133.4,
                'pattern': 'Mercosul',
                'support_engines': ['rapidocr'],
            },
            'top_candidates': [],
            'consensus': {
                'agreement_ratio': 100.0,
            },
            'legal_validation': {
                'is_valid': True,
                'law_score': 100.0,
                'detected_pattern': 'Mercosul',
            },
            'plate_pattern_info': {
                'padrao_placa': 'Mercosul',
            },
            'quality_report': {
                'score': 78.0,
                'grade': 'BOA',
                'issues': [],
            },
            'capture_integrity': {
                'integrity_score': 91.0,
                'status': 'ok',
            },
            'plate_detection': {
                'status': 'roi_detectado',
                'selected_quality_score': 86.0,
                'selected_region': 'haar_1',
            },
            'visual_profile': {},
        })

        conclusion = built.get('conclusion', {})
        self.assertEqual(conclusion.get('decision'), 'conclusivo')
        self.assertFalse(conclusion.get('manual_review_required'))
        self.assertTrue(conclusion.get('strong_ocr_evidence'))
        self.assertEqual(built.get('status'), 'atencao')

    def test_weak_capture_without_strong_ocr_stays_inconclusive(self):
        built = protocol.build_operational_protocol({
            'best_payload': {
                'text': '',
                'avg_conf': 0.0,
                'score': 0.0,
                'pattern': 'Indefinido',
                'support_engines': [],
            },
            'top_candidates': [],
            'consensus': {
                'agreement_ratio': 0.0,
            },
            'legal_validation': {
                'is_valid': False,
                'law_score': 0.0,
                'detected_pattern': 'Indefinido',
            },
            'quality_report': {
                'score': 21.0,
                'grade': 'CRITICA',
                'issues': ['imagem_borrada'],
            },
            'capture_integrity': {
                'integrity_score': 62.0,
                'status': 'revisao_obrigatoria',
            },
            'plate_detection': {
                'status': 'sem_candidato',
                'selected_quality_score': 0.0,
                'selected_region': '',
            },
            'visual_profile': {},
        })

        conclusion = built.get('conclusion', {})
        self.assertEqual(conclusion.get('decision'), 'inconclusivo')
        self.assertFalse(conclusion.get('strong_ocr_evidence'))
        self.assertEqual(built.get('status'), 'revisao_obrigatoria')


if __name__ == '__main__':
    unittest.main()
