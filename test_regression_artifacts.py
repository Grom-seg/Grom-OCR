import json
import os
import unittest


PROJECT_ROOT = os.path.dirname(__file__)


def _load_json(path):
    if not os.path.exists(path):
        raise AssertionError(f'missing test artifact: {path}')
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)


class RegressionArtifactTests(unittest.TestCase):
    def test_image_smoke_stays_conclusive(self):
        data = _load_json(os.path.join(PROJECT_ROOT, 'data', 'test_results', 'smoke_image_quick.json'))

        self.assertEqual(data.get('ocr'), 'ABC1234')
        self.assertEqual(data.get('status'), 'CONCLUSIVO')
        self.assertEqual(data.get('pattern'), 'Antigo')

    def test_real_video_scan_stays_inconclusive_without_false_target(self):
        data = _load_json(
            os.path.join(
                PROJECT_ROOT,
                'data',
                'uploads',
                'grom_ocr_video_scan_video_real_inconclusive_299191587a32.json',
            )
        )

        frame_results = data.get('frame_results', [])
        selected_targets = data.get('selected_targets', [])
        best_result = data.get('best_result', {})
        consensus = data.get('consensus', {})
        frame_sampling = data.get('frame_sampling', {})

        self.assertEqual(len(frame_results), 16)
        self.assertEqual(int(frame_sampling.get('selected_frame_count', 0) or 0), 16)
        self.assertEqual(best_result.get('text'), 'Indefinido')
        self.assertEqual(best_result.get('pattern'), 'Indefinido')
        self.assertEqual(int(consensus.get('agreement_count', 0) or 0), 0)
        self.assertFalse(selected_targets)
        self.assertEqual({str(entry.get('ocr', '')) for entry in frame_results if isinstance(entry, dict)}, {'Indefinido'})

    def test_real_video_positive_scan_consolidates_target_and_minute(self):
        data = _load_json(
            os.path.join(
                PROJECT_ROOT,
                'data',
                'uploads',
                'grom_ocr_video_scan_video_d9ab7fe6dbcc4a00.json',
            )
        )

        best_result = data.get('best_result', {})
        selected_target = data.get('selected_target', {})
        selected_targets = data.get('selected_targets', [])
        consensus = data.get('consensus', {})

        self.assertEqual(best_result.get('text'), 'DFO8819')
        self.assertEqual(best_result.get('pattern'), 'Antigo')
        self.assertEqual(selected_target.get('text'), 'DFO8819')
        self.assertEqual(selected_target.get('minute_range'), '00:00-01:00')
        self.assertEqual(selected_target.get('display_label'), '00:00-01:00 | DFO8819 | Antigo')
        self.assertEqual(len(selected_targets), 1)
        self.assertEqual(selected_targets[0].get('text'), 'DFO8819')
        self.assertGreater(float(selected_target.get('style_rank_priority', 0.0) or 0.0), 0.0)
        self.assertGreater(float(selected_target.get('support_rank', 0.0) or 0.0), float(selected_target.get('frames_count', 0) or 0))
        self.assertGreaterEqual(int(consensus.get('agreement_count', 0) or 0), 1)


if __name__ == '__main__':
    unittest.main()
