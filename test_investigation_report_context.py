import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

from utils.investigation_report_pdf import _build_scene_diagnosis_lines, _coerce_report_ocr_results  # noqa: E402


class InvestigationReportContextTests(unittest.TestCase):
    def test_coerce_report_ocr_results_prefers_ocr_engines_alias(self):
        data = {
            'ocr_engines': {
                'rapidocr': {
                    'text': 'REI5G32',
                    'avg_conf': 87.8,
                    'score': 133.4,
                    'pattern': 'Mercosul',
                }
            }
        }

        result = _coerce_report_ocr_results(data)

        self.assertIn('rapidocr', result)
        self.assertEqual(result['rapidocr']['text'], 'REI5G32')
        self.assertEqual(result['rapidocr']['pattern'], 'Mercosul')

    def test_coerce_report_ocr_results_builds_rows_from_ocr_record(self):
        data = {
            'ocr_record': {
                'leitura_principal': 'REI5G32',
                'avg_conf': 87.8,
                'confidencia_estimativa': 94.2,
                'agreement_ratio': 100.0,
                'padrao_placa': 'Mercosul',
                'supports': ['rapidocr'],
                'leitura_alternativas': [
                    {'text': 'REI3G69', 'avg_conf': 87.4, 'score': 132.3, 'pattern': 'Mercosul', 'engine': 'ensemble'},
                    {'text': 'REI5632', 'avg_conf': 87.8, 'score': 130.0, 'pattern': 'Antigo', 'engine': 'ensemble'},
                ],
            }
        }

        result = _coerce_report_ocr_results(data)

        self.assertIn('ocr_record_principal', result)
        self.assertIn('ocr_record_alt_1', result)
        self.assertEqual(result['ocr_record_principal']['text'], 'REI5G32')
        self.assertEqual(result['ocr_record_alt_1']['text'], 'REI3G69')

    def test_scene_diagnosis_lines_are_more_descriptive(self):
        data = {
            'input_meta': {
                'scene_preprocess': {
                    'scenario_primary': 'bright',
                },
                'plate_detection': {
                    'candidate_count': 22,
                    'selected_region': 'yolo_roi',
                },
            },
            'visual_profile': {
                'vista_detectada': 'traseira',
                'cor_probavel': 'azul',
            },
            'vehicle_basics': {
                'observacoes': ['comparativo_aberto_disponivel'],
            },
        }

        lines = _build_scene_diagnosis_lines('Muito claro', 'gray_world_dehaze', scene_context=data)
        text = ' '.join(lines).lower()

        self.assertIn('cena externa', text)
        self.assertIn('múltiplos veículos', text)
        self.assertIn('roi principal', text)

    def test_scene_diagnosis_avoids_false_rear_blue_for_wide_white_fleet_scene(self):
        data = {
            'input_meta': {
                'scene_preprocess': {
                    'scenario_primary': 'bright',
                    'scenario_reasons': ['imagem_superexposta'],
                },
                'plate_detection': {
                    'candidate_count': 22,
                    'selected_region': 'yolo_roi',
                },
            },
            'visual_profile': {
                'vista_detectada': 'traseira',
                'cor_probavel': 'azul',
                'geometria': {
                    'dual_headlamps': True,
                    'frontal_symmetry': 87.2,
                    'grille_edge_density': 6.32,
                },
                'lanterna_traseira': {
                    'source': 'rear_layout_hint',
                    'vertical_pair': False,
                    'left': None,
                    'right': None,
                },
                'assinaturas_componentes': {
                    'low_context_blocked': True,
                },
            },
            'scene_visual_summary': {
                'white_ratio': 51.2,
                'bright_low_sat_ratio': 51.8,
                'lower_green_ratio': 34.8,
            },
        }

        lines = _build_scene_diagnosis_lines('Muito claro', 'gray_world_dehaze', scene_context=data)
        text = ' '.join(lines).lower()

        self.assertIn('veículos claros', text)
        self.assertIn('frontais', text)
        self.assertIn('gramad', text)
        self.assertNotIn('traseira', text)
        self.assertNotIn('azul', text)


if __name__ == '__main__':
    unittest.main()
