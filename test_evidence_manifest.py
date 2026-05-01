import os
import sys
import tempfile
import unittest

from PIL import Image


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

from utils.evidence_manifest import build_evidence_manifest, manifest_summary_dict, persist_evidence_manifest  # noqa: E402


class EvidenceManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_image(self, name, size=(640, 480)):
        path = os.path.join(self.tmpdir.name, name)
        Image.new('RGB', size, (24, 36, 48)).save(path, quality=90)
        return path

    def test_image_manifest_summary_and_persistence(self):
        source = self._make_image('source.jpg')
        raw = self._make_image('raw.jpg')
        treated = self._make_image('treated.jpg')

        report_data = {
            'analysis_id': 'image_case_001',
            'analysis_stage': 'final',
            'original_path': source,
            'crop_raw_path': raw,
            'crop_treated_path': treated,
            'metadata': {
                'resolution': {'width': 640, 'height': 480},
            },
            'input_meta': {
                'input_type': 'image',
                'source_path': source,
                'source_resolution': {'width': 640, 'height': 480},
                'scene_preprocess': {
                    'selected_variant': 'original',
                },
                'plate_detection': {
                    'selected_raw_path': raw,
                    'selected_treated_path': treated,
                },
                'human_review': {
                    'status': 'registrado',
                },
            },
            'consensus': {
                'agreement_ratio': 100.0,
                'engines_considered': 3,
            },
            'best_result': {
                'text': 'DFO8819',
                'pattern': 'Antigo',
                'avg_conf': 96.2,
                'score': 87.5,
            },
            'human_review': {
                'status': 'registrado',
            },
            'report_path': os.path.join(self.tmpdir.name, 'report.pdf'),
        }

        manifest = build_evidence_manifest(report_data, analysis_kind='image')
        summary = manifest_summary_dict(manifest)
        persisted = persist_evidence_manifest(manifest, self.tmpdir.name, 'image_case_001', 'image')

        self.assertEqual(manifest['analysis_family'], 'image')
        self.assertEqual(summary['Tipo de análise'], 'Imagem')
        self.assertIn('Recorte bruto', summary)
        self.assertTrue(manifest['manifest_fingerprint'])
        self.assertGreaterEqual(len(manifest.get('derived_artifacts', [])), 2)
        self.assertTrue(os.path.exists(persisted['manifest_path']))
        self.assertTrue(persisted['manifest_url'].endswith('.json'))

    def test_video_manifest_tracks_selected_targets(self):
        source = os.path.join(self.tmpdir.name, 'clip.mp4')
        with open(source, 'wb') as stream:
            stream.write(b'not-a-real-video-but-valid-manifest-input')

        contact = self._make_image('contact.jpg', size=(1200, 800))
        comparison = self._make_image('comparison.jpg', size=(1200, 800))

        report_data = {
            'analysis_id': 'video_case_001',
            'analysis_stage': 'final',
            'video_path': source,
            'video_metadata': {
                'video_path': source,
                'video_filename': 'clip.mp4',
                'width': 1280,
                'height': 720,
                'duration_seconds': 45.0,
                'frame_count': 900,
                'fps': 20.0,
                'codec_fourcc': 'H264',
                'sha256': 'abc123',
            },
            'frame_sampling': {
                'strategy': 'frame_by_frame_scan',
                'coverage_label': '0-45.00s',
                'scan_interval_seconds': 0.25,
                'selected_frame_count': 12,
                'frame_count_total': 900,
            },
            'selected_candidate_ids': ['cand-01'],
            'selected_targets': [
                {
                    'candidate_id': 'cand-01',
                    'display_label': 'Alvo 01',
                    'text': 'DFO8819',
                    'pattern': 'Antigo',
                    'timestamp_seconds': 12.5,
                    'minute_label': '00:12',
                    'minute_range': '00:12-00:13',
                    'frames_count': 4,
                    'best_confidence': 95.0,
                    'best_score': 88.0,
                },
            ],
            'contact_sheet_path': contact,
            'comparison_sheet_path': comparison,
            'report_path': os.path.join(self.tmpdir.name, 'report.pdf'),
            'scan_record_path': os.path.join(self.tmpdir.name, 'scan.json'),
            'best_frame': {
                'timestamp_seconds': 12.5,
                'frame_index': 375,
                'frame_order': 4,
                'ocr': 'DFO8819',
                'pattern': 'Antigo',
            },
            'best_result': {
                'text': 'DFO8819',
                'pattern': 'Antigo',
                'avg_conf': 95.0,
                'score': 88.0,
            },
            'consensus': {
                'agreement_ratio': 100.0,
                'engines_considered': 4,
            },
            'human_review': {
                'status': 'registrado',
                'decision': 'registrado',
            },
            'capture_integrity': {
                'status': 'validado',
                'integrity_score': 96.0,
            },
            'pericial': {
                'summary': 'Video analisado em fluxo pericial.',
            },
            'input_meta': {
                'input_type': 'video',
                'source_path': source,
                'source_resolution': {'width': 1280, 'height': 720},
                'video_metadata': {
                    'frame_count': 900,
                    'duration_seconds': 45.0,
                },
                'capture_integrity': {
                    'status': 'validado',
                },
            },
        }

        manifest = build_evidence_manifest(report_data, analysis_kind='video')
        summary = manifest_summary_dict(manifest)
        persisted = persist_evidence_manifest(manifest, self.tmpdir.name, 'video_case_001', 'video')

        self.assertEqual(manifest['analysis_family'], 'video')
        self.assertEqual(summary['Tipo de análise'], 'Vídeo')
        self.assertIn('Varredura frame a frame', summary['Procedimentos registrados'])
        self.assertEqual(manifest['selection']['selected_target_count'], 1)
        self.assertTrue(os.path.exists(persisted['manifest_path']))


if __name__ == '__main__':
    unittest.main()
