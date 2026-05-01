import os
import sys
import unittest


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
from utils.partial_plate import build_partial_plate_candidates, build_partial_plate_overview  # noqa: E402
from utils.video_session import aggregate_video_partial_candidates  # noqa: E402
from utils.vehicle_confrontation_form import build_vehicle_confrontation_form  # noqa: E402


class PartialPlateEvidenceTests(unittest.TestCase):
    def test_build_partial_plate_candidates_preserves_short_fragments(self):
        ocr_results = {
            'rapidocr': {
                'avg_conf': 83.5,
                'score': 124.0,
                'pattern': 'Antigo',
                'raw_entries': [
                    {'text': 'D', 'conf': 90.0, 'score': 45.0, 'region': 'chars'},
                    {'text': '8', 'conf': 86.0, 'score': 42.0, 'region': 'chars'},
                    {'text': 'O', 'conf': 82.0, 'score': 39.0, 'region': 'chars'},
                ],
            }
        }

        candidates = build_partial_plate_candidates(
            ocr_results,
            top_candidates=[],
            context={
                'analysis_mode': 'image',
                'analysis_id': 'partial-image-1',
                'frame_index': 2,
                'frame_order': 2,
                'timestamp_seconds': 12.5,
                'frame_path': 'C:/tmp/frame.jpg',
                'crop_raw_path': 'C:/tmp/crop_raw.jpg',
                'crop_treated_path': 'C:/tmp/crop_treated.jpg',
            },
            max_candidates=8,
        )

        overview = build_partial_plate_overview(candidates)

        self.assertTrue(candidates)
        self.assertTrue(overview['has_partial'])
        self.assertIn(overview['primary_text'], {'D', '8', 'O'})

    def test_build_partial_plate_evidence_reports_text_and_count(self):
        ocr_results = {
            'rapidocr': {
                'avg_conf': 82.0,
                'score': 118.0,
                'pattern': 'Antigo',
                'raw_entries': [{'text': 'DF', 'conf': 88.0, 'score': 41.0, 'region': 'chars'}],
            }
        }

        evidence = ocr_agent.build_partial_plate_evidence(
            ocr_results,
            top_candidates=[],
            plate_detection={},
            context={
                'analysis_mode': 'image',
                'analysis_id': 'partial-image-2',
                'frame_index': 1,
                'frame_order': 1,
                'timestamp_seconds': 9.0,
                'frame_path': 'C:/tmp/frame2.jpg',
                'crop_raw_path': 'C:/tmp/crop_raw2.jpg',
                'crop_treated_path': 'C:/tmp/crop_treated2.jpg',
            },
            max_candidates=8,
        )

        self.assertTrue(evidence['partial_plate_has_evidence'])
        self.assertEqual(evidence['partial_plate_text'], 'DF')
        self.assertGreaterEqual(evidence['partial_plate_candidates_count'], 1)

    def test_aggregate_video_partial_candidates_groups_minute_context(self):
        frame_results = [
            {
                'frame_index': 10,
                'frame_order': 1,
                'timestamp_seconds': 11.4,
                'partial_plate_candidates': [
                    {
                        'text': 'D',
                        'best_confidence': 89.0,
                        'best_score': 44.0,
                        'minute_index': 0,
                        'minute_range': '00:00-00:59',
                        'frame_index': 10,
                        'frame_order': 1,
                        'frame_path': 'C:/tmp/frame_a.jpg',
                        'crop_raw_path': 'C:/tmp/raw_a.jpg',
                        'crop_treated_path': 'C:/tmp/treated_a.jpg',
                        'support_engines': ['rapidocr'],
                        'fragment_kind': 'caractere_isolado',
                        'slot_hint': 'L',
                    }
                ],
            },
            {
                'frame_index': 11,
                'frame_order': 2,
                'timestamp_seconds': 12.7,
                'partial_plate_candidates': [
                    {
                        'text': 'D',
                        'best_confidence': 92.0,
                        'best_score': 47.0,
                        'minute_index': 0,
                        'minute_range': '00:00-00:59',
                        'frame_index': 11,
                        'frame_order': 2,
                        'frame_path': 'C:/tmp/frame_b.jpg',
                        'crop_raw_path': 'C:/tmp/raw_b.jpg',
                        'crop_treated_path': 'C:/tmp/treated_b.jpg',
                        'support_engines': ['doctr'],
                        'fragment_kind': 'caractere_isolado',
                        'slot_hint': 'L',
                    }
                ],
            },
        ]

        preview, all_candidates = aggregate_video_partial_candidates(frame_results, max_candidates=8)

        self.assertTrue(preview)
        self.assertTrue(all_candidates)
        self.assertEqual(preview[0]['text'], 'D')
        self.assertEqual(preview[0]['minute_range'], '00:00-00:59')
        self.assertEqual(preview[0]['frames_count'], 2)
        self.assertGreaterEqual(preview[0]['best_confidence'], 92.0)

    def test_vehicle_confrontation_form_exposes_partial_fragment(self):
        form = build_vehicle_confrontation_form({
            'analysis_id': 'partial-form-1',
            'photo_filename': 'case.jpg',
            'photo_path': 'C:/tmp/case.jpg',
            'capture_timestamp_utc': '2026-04-12T10:00:00Z',
            'responsavel': 'Operador',
            'operational_protocol': {
                'evidence_preservation': {
                    'source_filename': 'case.jpg',
                    'capture_timestamp_utc': '2026-04-12T10:00:00Z',
                },
                'ocr_record': {
                    'leitura_principal': 'DFO8819',
                    'partial_plate_text': 'DF',
                    'partial_plate_candidates': [
                        {'text': 'DF', 'support_label': '1 motor(es) | 1 leitura(s)'},
                    ],
                    'partial_plate_summary': 'DF (1 motor(es) | 1 leitura(s))',
                },
                'vehicle_basics': {},
                'compatibility_matrix': {},
                'exclusion_checks': {},
                'conclusion': {},
                'quality_triage': {},
            },
        })

        self.assertEqual(form['ocr']['partial_text'], 'DF')
        self.assertEqual(form['ocr']['plate_partial'], 'DF')
        self.assertEqual(form['ocr']['partial_candidates_count'], 1)
        self.assertEqual(form['cruzamento_ocr']['fragmento_parcial'], 'DF')

    def test_scene_level_words_are_not_preserved_as_plate_partial_evidence(self):
        ocr_results = {
            'rapidocr': {
                'avg_conf': 85.0,
                'score': 130.0,
                'pattern': 'Indefinido',
                'raw_entries': [
                    {'text': 'FIAT', 'conf': 91.0, 'score': 51.0, 'region': 'raw_input'},
                    {'text': 'BRASIL', 'conf': 88.0, 'score': 48.0, 'region': 'raw_input'},
                    {'text': 'REI', 'conf': 84.0, 'score': 43.0, 'region': 'lower_wide_focus'},
                    {'text': '32', 'conf': 83.0, 'score': 42.0, 'region': 'lower_wide_focus'},
                ],
            }
        }

        candidates = build_partial_plate_candidates(
            ocr_results,
            top_candidates=[],
            context={
                'analysis_mode': 'image',
                'analysis_id': 'partial-image-scene-filter',
                'frame_index': -1,
                'frame_order': -1,
                'timestamp_seconds': -1.0,
                'frame_path': 'C:/tmp/scene.jpg',
            },
            max_candidates=8,
        )

        texts = {entry.get('text') for entry in candidates if isinstance(entry, dict)}
        self.assertNotIn('FIAT', texts)
        self.assertNotIn('BRASIL', texts)
        self.assertIn('REI', texts)
        self.assertIn('32', texts)

    def test_scene_level_char_fallback_is_not_promoted(self):
        ocr_results = {
            'rapidocr': {
                'avg_conf': 84.0,
                'score': 126.0,
                'pattern': 'Indefinido',
                'raw_entries': [
                    {'text': 'FIAT', 'conf': 90.0, 'score': 50.0, 'region': 'raw_input'},
                    {'text': 'BRASIL', 'conf': 87.0, 'score': 47.0, 'region': 'raw_input'},
                ],
                'chars': [['R', 88.0], ['I', 87.0], ['A', 86.0], ['S', 85.0]],
                'region': 'raw_input',
            }
        }

        candidates = build_partial_plate_candidates(
            ocr_results,
            top_candidates=[],
            context={
                'analysis_mode': 'image',
                'analysis_id': 'partial-image-scene-chars',
                'frame_index': -1,
                'frame_order': -1,
                'timestamp_seconds': -1.0,
                'frame_path': 'C:/tmp/scene-chars.jpg',
            },
            max_candidates=8,
        )

        self.assertFalse(candidates)


if __name__ == '__main__':
    unittest.main()
