import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

import ocr_agent  # noqa: E402


class AssistedVehicleIdentificationTests(unittest.TestCase):
    def test_build_assisted_vehicle_identification_marks_corroborated_match(self):
        visual_profile = {
            'status': 'ok',
            'vista_detectada': 'frontal',
            'cor_probavel': 'branca',
            'hipotese_principal': {
                'fabricante': 'FIAT',
                'modelo': 'Argo',
                'faixa_ano_modelo': '2017-Atual',
                'confianca': 74.0,
            },
            'hipotese_principal_bruta': {
                'fabricante': 'FIAT',
                'modelo': 'Argo',
            },
            'qualidade_modelo': {
                'model_abstained': False,
            },
            'hipoteses': [
                {'fabricante': 'FIAT', 'modelo': 'Argo', 'confianca': 74.0, 'faixa_ano_modelo': '2017-Atual'},
                {'fabricante': 'FIAT', 'modelo': 'Mobi', 'confianca': 52.0, 'faixa_ano_modelo': '2017-Atual'},
            ],
        }
        external = {
            'execucoes': [
                {
                    'status': 'ok',
                    'nome': 'Rekor CarCheck / OpenALPR',
                    'plate_confidence': 89.0,
                    'matches_internal_vehicle': True,
                    'vehicle': {
                        'fabricante': 'Fiat',
                        'modelo': 'Argo',
                        'cor': 'branca',
                        'ano': '2018',
                        'tipo_carroceria': 'hatch',
                        'confianca_modelo': 84.0,
                        'confianca_fabricante': 82.0,
                    },
                }
            ]
        }

        result = ocr_agent.build_assisted_vehicle_identification(visual_profile, external)

        self.assertEqual(result['status'], 'corroborada_multifonte')
        self.assertTrue(result['corroborated'])
        self.assertTrue(result['manual_review_required'])
        self.assertFalse(result['auto_conclusion_allowed'])
        self.assertIn('Argo', result['label'])
        self.assertGreaterEqual(result['confidence'], 62.0)

    def test_build_assisted_vehicle_identification_keeps_review_required_when_local_model_abstained(self):
        visual_profile = {
            'status': 'review_required',
            'vista_detectada': 'traseira',
            'cor_probavel': 'preta',
            'hipotese_principal': {
                'fabricante': 'FIAT',
                'modelo': 'Não conclusivo',
                'faixa_ano_modelo': '',
                'confianca': 41.0,
            },
            'hipotese_principal_bruta': {
                'fabricante': 'FIAT',
                'modelo': 'Uno',
                'faixa_ano_modelo': '2010-2021',
            },
            'qualidade_modelo': {
                'model_abstained': True,
                'reasons': ['evidencia_discriminativa_insuficiente'],
            },
            'hipoteses': [
                {'fabricante': 'FIAT', 'modelo': 'Uno', 'confianca': 38.9, 'faixa_ano_modelo': '2010-2021'},
                {'fabricante': 'FIAT', 'modelo': 'Mobi', 'confianca': 35.5, 'faixa_ano_modelo': '2017-Atual'},
            ],
        }

        result = ocr_agent.build_assisted_vehicle_identification(visual_profile, {})

        self.assertEqual(result['status'], 'revisao_humana_obrigatoria')
        self.assertTrue(result['manual_review_required'])
        self.assertFalse(result['corroborated'])
        self.assertIn('modelo_local_abstido_por_baixa_evidencia', result['reasons'])
        self.assertGreaterEqual(len(result['alternatives']), 1)


if __name__ == '__main__':
    unittest.main()
