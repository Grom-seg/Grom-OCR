import os
import sys
import unittest

import cv2


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

import ocr_agent as oa  # noqa: E402


class TailDigitGeometryTests(unittest.TestCase):
    def _load_crop(self, name):
        path = os.path.join(PROJECT_ROOT, 'data', 'uploads', name)
        self.assertTrue(os.path.exists(path), f'missing crop fixture: {path}')
        img = cv2.imread(path)
        self.assertIsNotNone(img, f'failed to load crop fixture: {path}')
        return path, img

    def test_tail_digit_geometry_detects_one_on_pxz9991_crop(self):
        _path, img = self._load_crop('placa_10458347_x216.jpg')

        result = oa.analyze_tail_digit_geometry(img)

        self.assertTrue(result.get('available'))
        self.assertEqual(result.get('tail_digit_suggested'), '1')
        self.assertGreaterEqual(float(result.get('tail_digit_one_confidence', 0.0) or 0.0), 68.0)

    def test_tail_digit_geometry_does_not_trigger_on_dfo8819_crop(self):
        _path, img = self._load_crop('placa_20171119_154214_ch6-1024x576.jpg')

        result = oa.analyze_tail_digit_geometry(img)

        self.assertTrue(result.get('available'))
        self.assertNotEqual(result.get('tail_digit_suggested'), '1')

    def test_geometry_refine_builds_pxz9991_candidate(self):
        crop_path, _img = self._load_crop('placa_10458347_x216.jpg')
        plate_detection = {
            'selected_raw_path': crop_path,
            'selected_treated_path': crop_path,
            'selected_path': crop_path,
        }
        ocr_results = {
            'rapidocr': {
                'text': 'PXZ9999',
                'avg_conf': 59.81,
                'score': 59.81,
                'pattern': 'Antigo',
                'region': 'raw_yolo_roi',
                'candidates': [
                    {
                        'text': 'PXZ9999',
                        'avg_conf': 59.81,
                        'score': 59.81,
                        'pattern': 'Antigo',
                        'region': 'raw_yolo_roi',
                    }
                ],
            }
        }

        result = oa.build_geometry_refine_result(ocr_results, plate_detection=plate_detection)

        self.assertIsNotNone(result)
        self.assertEqual(result.get('text'), 'PXZ9991')
        self.assertEqual(result.get('pattern'), 'Antigo')
        self.assertEqual(result.get('selection_reason'), 'tail_digit_geometry_refine')


if __name__ == '__main__':
    unittest.main()
