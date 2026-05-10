import json
import os
import unittest


PROJECT_ROOT = os.path.dirname(__file__)
RESULT_PATH = os.path.join(PROJECT_ROOT, 'data', 'test_results', 'video_forensic_benchmark_latest.json')
MANIFEST_PATH = os.path.join(PROJECT_ROOT, 'data', 'video_forensic_benchmark_manifest.json')


def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as stream:
        try:
            data = json.load(stream)
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}


class VideoForensicRegressionTests(unittest.TestCase):
    def setUp(self):
        self.report = _load_json(RESULT_PATH)
        self.manifest = _load_json(MANIFEST_PATH)

    def test_benchmark_result_exists(self):
        if not self.report:
            self.skipTest('Resultado de benchmark de vídeo ainda não gerado.')
        self.assertIn('summary', self.report)
        self.assertIn('quality_metrics', self.report)
        self.assertIn('scenario_metrics', self.report)

    def test_quality_class_precision_targets(self):
        if not self.report:
            self.skipTest('Resultado de benchmark de vídeo ainda não gerado.')

        executed = int((self.report.get('summary', {}) if isinstance(self.report.get('summary'), dict) else {}).get('executed_cases', 0) or 0)
        if executed <= 0:
            self.skipTest('Benchmark de vídeo sem casos executados; ajuste o manifesto para arquivos existentes.')

        metrics = self.report.get('quality_metrics', {}) if isinstance(self.report.get('quality_metrics'), dict) else {}
        targets = self.manifest.get('quality_targets', {}) if isinstance(self.manifest.get('quality_targets'), dict) else {}

        for quality_class, target_data in targets.items():
            if not isinstance(target_data, dict):
                continue
            if quality_class not in metrics:
                self.fail(f'Métrica ausente para classe de qualidade: {quality_class}')

            target_precision = float(target_data.get('min_precision', 0.0) or 0.0)
            actual_precision = float(metrics[quality_class].get('precision', 0.0) or 0.0)
            self.assertGreaterEqual(
                actual_precision,
                target_precision,
                f'Classe {quality_class} abaixo da meta: {actual_precision:.4f} < {target_precision:.4f}',
            )

    def test_scenario_precision_targets(self):
        if not self.report:
            self.skipTest('Resultado de benchmark de vídeo ainda não gerado.')

        executed = int((self.report.get('summary', {}) if isinstance(self.report.get('summary'), dict) else {}).get('executed_cases', 0) or 0)
        if executed <= 0:
            self.skipTest('Benchmark de vídeo sem casos executados; ajuste o manifesto para arquivos existentes.')

        metrics = self.report.get('scenario_metrics', {}) if isinstance(self.report.get('scenario_metrics'), dict) else {}
        targets = self.manifest.get('scenario_targets', {}) if isinstance(self.manifest.get('scenario_targets'), dict) else {}

        for scenario, target_data in targets.items():
            if not isinstance(target_data, dict):
                continue
            if scenario not in metrics:
                self.fail(f'Métrica ausente para cenário: {scenario}')

            target_precision = float(target_data.get('min_precision', 0.0) or 0.0)
            actual_precision = float(metrics[scenario].get('precision', 0.0) or 0.0)
            self.assertGreaterEqual(
                actual_precision,
                target_precision,
                f'Cenário {scenario} abaixo da meta: {actual_precision:.4f} < {target_precision:.4f}',
            )


if __name__ == '__main__':
    unittest.main()
