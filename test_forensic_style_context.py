import os
import sys
import unittest


# Keep the import path light and deterministic for unit tests.
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
from utils.video_session import normalize_video_target_entry  # noqa: E402


class ForensicStyleContextTests(unittest.TestCase):
    def test_extract_plate_style_context_reads_top_level_style_fields(self):
        plate_detection = {
            'selected_metrics': {
                'quality_score': 87.5,
                'style_hint': 'indefinida',
                'style_confidence': 0.0,
            },
            'selected_style_hint': 'antigo',
            'selected_style_confidence': 88.0,
        }

        style_context = ocr_agent.extract_plate_style_context(plate_detection)

        self.assertEqual(style_context['style_hint'], 'antigo')
        self.assertAlmostEqual(style_context['style_confidence'], 88.0, places=1)

    def test_extract_plate_style_context_reads_ocr_selected_style_fields(self):
        plate_detection = {
            'selected_metrics': {
                'quality_score': 87.5,
                'style_hint': 'indefinida',
                'style_confidence': 0.0,
            },
            'ocr_selected_style_hint': 'mercosul',
            'ocr_selected_style_confidence': 79.5,
        }

        style_context = ocr_agent.extract_plate_style_context(plate_detection)

        self.assertEqual(style_context['style_hint'], 'mercosul')
        self.assertAlmostEqual(style_context['style_confidence'], 79.5, places=1)

    def test_build_ensemble_candidates_prefers_antique_d_over_o_when_style_is_strong(self):
        ocr_results = {
            'rapidocr': {
                'text': 'OFO8819',
                'avg_conf': 81.83,
                'score': 123.45,
                'pattern': 'Antigo',
                'region': 'center_lower_focus',
                'candidates': [
                    {
                        'text': 'OFO8819',
                        'avg_conf': 81.83,
                        'score': 123.45,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                    {
                        'text': 'DFO8819',
                        'avg_conf': 78.24,
                        'score': 119.85,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                    {
                        'text': 'OFO8B19',
                        'avg_conf': 81.83,
                        'score': 120.11,
                        'pattern': 'Mercosul',
                        'region': 'center_lower_focus',
                    },
                ],
            }
        }
        plate_detection = {
            'selected_metrics': {
                'quality_score': 87.5,
                'style_hint': 'indefinida',
                'style_confidence': 0.0,
            },
            'selected_style_hint': 'antigo',
            'selected_style_confidence': 88.0,
        }

        ranked = ocr_agent.build_ensemble_candidates(ocr_results, plate_detection=plate_detection)

        self.assertGreaterEqual(len(ranked), 2)
        self.assertEqual(ranked[0]['text'], 'DFO8819')
        self.assertEqual(ranked[0]['pattern'], 'Antigo')
        self.assertIn('OFO8819', {item['text'] for item in ranked[:3]})

    def test_get_best_result_prefers_antique_d_over_o_even_with_one_less_engine_vote(self):
        ocr_results = {
            'rapidocr': {
                'text': 'OFO8819',
                'avg_conf': 81.83,
                'score': 123.45,
                'pattern': 'Antigo',
                'region': 'center_lower_focus',
                'candidates': [
                    {
                        'text': 'OFO8819',
                        'avg_conf': 81.83,
                        'score': 123.45,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                    {
                        'text': 'DFO8819',
                        'avg_conf': 78.24,
                        'score': 119.85,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                ],
            },
            'easyocr': {
                'text': 'OFO8819',
                'avg_conf': 79.5,
                'score': 121.2,
                'pattern': 'Antigo',
                'region': 'lower_wide_focus',
                'candidates': [
                    {
                        'text': 'OFO8819',
                        'avg_conf': 79.5,
                        'score': 121.2,
                        'pattern': 'Antigo',
                        'region': 'lower_wide_focus',
                    },
                ],
            },
        }
        plate_detection = {
            'selected_metrics': {
                'quality_score': 87.5,
                'style_hint': 'indefinida',
                'style_confidence': 0.0,
            },
            'selected_style_hint': 'antigo',
            'selected_style_confidence': 88.0,
        }

        best_engine, best_result = ocr_agent.get_best_result(ocr_results, plate_detection=plate_detection)

        self.assertEqual(best_engine, 'ensemble')
        self.assertEqual(best_result['text'], 'DFO8819')
        self.assertEqual(best_result['pattern'], 'Antigo')
        self.assertGreater(float(best_result.get('support_rank', 0.0)), float(best_result.get('support_count', 0)))
        self.assertGreater(float(best_result.get('style_rank_priority', 0.0)), 0.0)

    def test_get_best_result_does_not_force_antique_d_when_style_is_weak(self):
        ocr_results = {
            'rapidocr': {
                'text': 'OFO8819',
                'avg_conf': 81.83,
                'score': 123.45,
                'pattern': 'Antigo',
                'region': 'center_lower_focus',
                'candidates': [
                    {
                        'text': 'OFO8819',
                        'avg_conf': 81.83,
                        'score': 123.45,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                    {
                        'text': 'DFO8819',
                        'avg_conf': 78.24,
                        'score': 119.85,
                        'pattern': 'Antigo',
                        'region': 'center_lower_focus',
                    },
                ],
            },
            'easyocr': {
                'text': 'OFO8819',
                'avg_conf': 79.5,
                'score': 121.2,
                'pattern': 'Antigo',
                'region': 'lower_wide_focus',
                'candidates': [
                    {
                        'text': 'OFO8819',
                        'avg_conf': 79.5,
                        'score': 121.2,
                        'pattern': 'Antigo',
                        'region': 'lower_wide_focus',
                    },
                ],
            },
        }
        plate_detection = {
            'selected_metrics': {
                'quality_score': 87.5,
                'style_hint': 'indefinida',
                'style_confidence': 0.0,
            },
            'selected_style_hint': 'antigo',
            'selected_style_confidence': 42.0,
        }

        best_engine, best_result = ocr_agent.get_best_result(ocr_results, plate_detection=plate_detection)

        self.assertEqual(best_engine, 'ensemble')
        self.assertEqual(best_result['text'], 'OFO8819')
        self.assertEqual(best_result['pattern'], 'Antigo')
        self.assertLess(float(best_result.get('support_rank', 0.0)), 3.0)
        self.assertLess(float(best_result.get('style_rank_priority', 0.0)), 1.0)

    def test_normalize_video_target_entry_preserves_video_ranking_context(self):
        target = {
            'candidate_id': 'cand-01',
            'text': 'DFO8819',
            'pattern': 'Antigo',
            'minute_range': '01:00-01:59',
            'frames_count': 4,
            'support_rank': 2.9,
            'style_rank_priority': 1.9,
            'avg_confidence': 82.4,
            'avg_score': 119.8,
            'best_frame': {
                'ocr': 'DFO8819',
                'confidence': 84.0,
                'score': 121.0,
                'pattern': 'Antigo',
                'timestamp_seconds': 65.4,
            },
        }

        normalized = normalize_video_target_entry(target)

        self.assertEqual(normalized['minute_range'], '01:00-01:59')
        self.assertAlmostEqual(normalized['support_rank'], 2.9, places=1)
        self.assertAlmostEqual(normalized['style_rank_priority'], 1.9, places=1)
        self.assertEqual(normalized['display_label'], '01:00-01:59 | DFO8819 | Antigo')

    def test_should_accept_result_rejects_style_conflict_when_weak(self):
        best_result = {
            'text': 'DFO8819',
            'avg_conf': 78.0,
            'score': 120.0,
            'pattern': 'Antigo',
            'support_count': 1,
            'weighted_support': 7.6,
        }
        plate_detection = {
            'selected_style_hint': 'mercosul',
            'selected_style_confidence': 88.0,
        }

        accepted, reason = ocr_agent.should_accept_result(best_result, plate_detection=plate_detection)

        self.assertFalse(accepted)
        self.assertEqual(reason, 'plate_style_conflict')

    def test_should_accept_result_allows_style_consistent_single_engine(self):
        best_result = {
            'text': 'ABC1234',
            'avg_conf': 92.0,
            'score': 149.0,
            'pattern': 'Antigo',
            'support_count': 1,
            'weighted_support': 7.6,
        }
        plate_detection = {
            'selected_style_hint': 'antigo',
            'selected_style_confidence': 88.0,
        }

        accepted, reason = ocr_agent.should_accept_result(best_result, plate_detection=plate_detection)

        self.assertTrue(accepted)
        self.assertEqual(reason, 'style_consistent_single_engine')


if __name__ == '__main__':
    unittest.main()
