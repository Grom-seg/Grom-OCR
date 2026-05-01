import os
import sys
import tempfile
import unittest

import cv2
import numpy as np


os.environ['GROM_OCR_ENABLE_EASYOCR'] = '0'
os.environ['GROM_OCR_ENABLE_RAPIDOCR'] = '0'
os.environ['GROM_OCR_ENABLE_TROCR'] = '0'
os.environ['GROM_OCR_ENABLE_DOCTR'] = '0'
os.environ['GROM_OCR_ENABLE_PADDLEOCR'] = '0'
os.environ['GROM_OCR_ENABLE_YOLO_DETECTOR'] = '0'
os.environ['GROM_OCR_ALLOW_HEAVY_COLDSTART'] = '0'
os.environ['GROM_OCR_ACCURACY_FIRST'] = '1'


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

import ocr_agent  # noqa: E402


class QuickImageTriageTests(unittest.TestCase):
    def test_build_image_quick_triage_decision_marks_strong_case_as_apto(self):
        decision = ocr_agent.build_image_quick_triage_decision(
            {
                'status': 'roi_detectado',
                'used_full_image': False,
                'candidate_count': 3,
                'selected_quality_score': 82.0,
                'selected_region': 'detected_1',
            },
            {'score': 79.0, 'grade': 'BOA'},
            {'integrity_score': 93.0},
            {
                'text': 'ABC1234',
                'pattern': 'Antigo',
                'avg_conf': 74.0,
                'score': 118.0,
                'law_score': 100.0,
            },
        )

        self.assertEqual(decision['triage_status'], 'apto_ocr')
        self.assertTrue(decision['material_minimo_ocr'])
        self.assertEqual(decision['recommended_next_step'], 'seguir_com_ocr_completo')

    def test_build_image_quick_triage_decision_marks_missing_roi_as_insufficient(self):
        decision = ocr_agent.build_image_quick_triage_decision(
            {
                'status': 'sem_candidato',
                'used_full_image': True,
                'candidate_count': 0,
                'selected_quality_score': 18.0,
                'selected_region': 'full_image',
            },
            {'score': 31.0, 'grade': 'CRITICA'},
            {'integrity_score': 62.0},
            {
                'text': '',
                'pattern': 'Indefinido',
                'avg_conf': 0.0,
                'score': 0.0,
                'law_score': 0.0,
            },
        )

        self.assertEqual(decision['triage_status'], 'insuficiente')
        self.assertFalse(decision['material_minimo_ocr'])
        self.assertIn('sem_roi_confiavel', decision['reasons'])

    def test_process_simple_triage_mode_returns_quick_payload_without_pdf(self):
        temp_path = None
        try:
            synthetic = np.full((160, 320, 3), 245, dtype=np.uint8)
            cv2.rectangle(synthetic, (90, 60), (230, 110), (20, 20, 20), 2)
            cv2.putText(
                synthetic,
                'ABC1234',
                (98, 95),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (15, 15, 15),
                2,
                cv2.LINE_AA,
            )

            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as handle:
                temp_path = handle.name
            cv2.imwrite(temp_path, synthetic)

            client = ocr_agent.app.test_client()
            with open(temp_path, 'rb') as stream:
                response = client.post(
                    '/process_simple',
                    data={
                        'analysis_mode': 'triage',
                        'image': (stream, 'triage_case.jpg'),
                    },
                    content_type='multipart/form-data',
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload.get('analysis_mode'), 'triage')
            self.assertIn(payload.get('triage_status'), {'apto_ocr', 'marginal_revisao', 'insuficiente'})
            self.assertIn('material_minimo_ocr', payload)
            self.assertNotIn('report_url', payload)
            self.assertFalse(payload.get('report_generated', True))
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == '__main__':
    unittest.main()
