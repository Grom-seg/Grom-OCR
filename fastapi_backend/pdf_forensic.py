#!/usr/bin/env python3
"""
Novo módulo de geração de PDF profissional forense-jurídico
Replaces _generate_pdf_report em main.py
"""
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
try:
    from fpdf import FPDF
except ImportError:
    from FPDF import FPDF

def _file_sha256(filepath):
    """Calcula SHA-256 de um arquivo."""
    try:
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return ""

class ForensicPDF:
    """
    Gerador de PDF técnico-pericial com padrões forense-jurídicos.
    Implementa:
    - Capa com metadados de análise
    - Cadeia de custódia com hash
    - Metodologia aplicada
    - Foto original em alta qualidade
    - Análise multi-placa detalhada
    - Consenso OCR inter-motores
    - Análise de qualidade de imagem
    - Análise veicular
    - Análise de cena
    - Análise geoespacial
    - Conclusão pericial
    """

    def __init__(self):
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=10)
        self.pdf.add_page()
        self.pdf.set_font("Arial", "", 11)

    def _mc(self, h, txt):
        """FPDF2-safe multi_cell: garante cursor em margem esquerda."""
        self.pdf.set_x(self.pdf.l_margin)
        try:
            self.pdf.multi_cell(0, h, str(txt or ""), new_x='LMARGIN', new_y='NEXT')
        except TypeError:
            # Compatibilidade com implementações legadas sem new_x/new_y.
            self.pdf.multi_cell(0, h, str(txt or ""))

    def _section_title(self, text):
        """Título de seção com faixa visual para aparência timbrada."""
        self.pdf.set_fill_color(235, 241, 248)
        self.pdf.set_draw_color(175, 190, 210)
        self.pdf.set_font("Arial", "B", 10)
        self.pdf.cell(0, 7, str(text or ""), ln=True, fill=True, border=1)
        self.pdf.ln(1)

    def _find_logo_path(self):
        root = Path(__file__).resolve().parent.parent
        logo = root / "public" / "assets" / "grom-report-logo.png"
        return str(logo) if logo.exists() else ""

    def _add_header(self, analysis_id, timestamp_utc):
        """Cabeçalho institucional."""
        self.pdf.set_fill_color(22, 58, 96)
        self.pdf.rect(0, 0, 210, 27, style='F')

        logo_path = self._find_logo_path()
        if logo_path:
            try:
                self.pdf.image(logo_path, x=10, y=5, w=24)
            except Exception:
                pass

        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_xy(38, 7)
        self.pdf.set_font("Arial", "B", 13)
        self.pdf.cell(120, 6, "GROM OCR - RELATORIO TECNICO-PERICIAL", ln=True)
        self.pdf.set_x(38)
        self.pdf.set_font("Arial", "", 9)
        self.pdf.cell(120, 5, "Identificacao veicular com OCR multi-motor e trilha forense", ln=True)

        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_y(31)
        self.pdf.set_draw_color(22, 58, 96)
        self.pdf.set_line_width(0.5)
        self.pdf.line(10, 31, 200, 31)
        self.pdf.ln(3)

        self.pdf.set_font("Arial", "", 9)
        self.pdf.cell(0, 5, f"ID de Analise: {analysis_id}", ln=True)
        self.pdf.cell(0, 5, f"Gerado em (UTC): {timestamp_utc}", ln=True)
        self.pdf.cell(0, 5, "Sistema: GROM-OCR v2.0", ln=True)
        self.pdf.ln(2)

    def _add_cadeia_custodia(self, photo_path, plate_path):
        """Seção de cadeia de custódia com hashes."""
        self._section_title("CADEIA DE CUSTODIA E INTEGRIDADE DIGITAL")
        self.pdf.set_font("Arial", "", 9)

        photo_hash = _file_sha256(photo_path) if os.path.exists(photo_path) else "UNAVAILABLE"
        plate_hash = _file_sha256(plate_path) if os.path.exists(plate_path) else "UNAVAILABLE"

        self._mc(4, f"Arquivo original: {os.path.basename(photo_path)}")
        if photo_hash:
            self._mc(4, f"Hash SHA-256: {photo_hash}")

        self._mc(4, f"\nRecorte principal placa: {os.path.basename(plate_path)}")
        if plate_hash:
            self._mc(4, f"Hash SHA-256: {plate_hash}")

        self.pdf.ln(2)

    def _add_methodology(self, process_trace, ocr_engine_summary):
        """Seção de metodologia técnica aplicada."""
        self._section_title("METODOLOGIA TECNICA APLICADA")
        self.pdf.set_font("Arial", "", 9)

        # Trace do processo
        if isinstance(process_trace, list):
            for step in process_trace[:10]:
                self._mc(4, f"- {str(step)}")

        # Motores executados
        self.pdf.ln(1)
        engines = ocr_engine_summary.get('engines_executed', []) if isinstance(ocr_engine_summary, dict) else []
        engines_text = ", ".join([str(e) for e in engines]) if engines else "indisponível"
        fallback_status = "SIM" if ocr_engine_summary.get('fallback_used') else "NAO"

        self.pdf.set_font("Arial", "", 9)
        self._mc(4, f"Motores OCR executados: {engines_text}")
        self._mc(4, f"Fallback multi-motor acionado: {fallback_status}")
        self.pdf.ln(2)

    def _add_evidence_photo(self, photo_path, max_width=180):
        """Insere foto original com qualidade."""
        self._section_title("EVIDENCIA FOTOGRAFICA ORIGINAL")

        if os.path.exists(photo_path):
            try:
                # Tenta inserir foto
                y_before = self.pdf.get_y()
                self.pdf.image(photo_path, x=10, y=y_before + 2, w=max_width)
                self.pdf.set_y(y_before + 100)  # Espaço após foto
                self.pdf.ln(1)
            except Exception as e:
                self.pdf.set_font("Arial", "", 9)
                self._mc(4, f"Nao foi possivel incorporar foto: {e}")
        else:
            self.pdf.set_font("Arial", "", 9)
            self._mc(4, "Arquivo de foto nao localizado")

        self.pdf.ln(1)

    def _add_multi_plate_analysis(self, top_candidates, plate_analyses):
        """Análise de todas as placas detectadas."""
        self._section_title("ANALISE MULTI-PLACA - TODAS AS REGIOES")

        if isinstance(plate_analyses, list) and plate_analyses:
            self.pdf.set_font("Arial", "", 8)
            for plate_row in plate_analyses[:20]:
                if not isinstance(plate_row, dict):
                    continue
                rank = int(plate_row.get('priority_rank', 0) or 0)
                best_text = str(plate_row.get('best_text', '') or '').strip()
                best_engine = str(plate_row.get('best_engine', '') or '').strip()
                best_conf = float(plate_row.get('best_confidence', 0.0) or 0.0)
                det_conf = float(plate_row.get('detection_confidence', 0.0) or 0.0)
                is_primary = " [PLACA PRIMARIA]" if plate_row.get('is_primary_candidate') else ""

                line = f"Rank {rank}{is_primary}: {best_text or 'NAO RECONHECIDA'} | "
                line += f"Motor: {best_engine or '-'} | Conf OCR: {best_conf:.3f} | Conf Det: {det_conf:.3f}"
                self._mc(4, line)

        if isinstance(top_candidates, list) and top_candidates:
            self.pdf.ln(1)
            self.pdf.set_font("Arial", "B", 10)
            self.pdf.cell(0, 6, "Consolidacao de candidatos por motor OCR:", ln=True)
            self.pdf.set_font("Arial", "", 8)

            for row in top_candidates[:30]:
                if not isinstance(row, dict):
                    continue
                txt = str(row.get('text', '') or '').strip()
                eng = str(row.get('engine', '-') or '-')
                sc = float(row.get('score', 0.0) or 0.0)
                sup = int(row.get('support_count', 1) or 1)
                eng_support = int(row.get('engine_support_count', 0) or 0)
                agr = float(row.get('agreement_ratio', 0) or 0)

                line = f"- {txt or 'VAZIO'} | Motor primario: {eng} | "
                line += f"Score: {sc:.3f} | Suporte: {sup} detec | Consenso: {agr:.1f}%"
                self._mc(4, line)

        self.pdf.ln(1)

    def _add_consensus_analysis(self, consensus, assessment):
        """Análise de consenso inter-motores."""
        self._section_title("ANALISE DE CONSENSO OCR INTER-MOTORES")
        self.pdf.set_font("Arial", "", 9)

        if isinstance(consensus, dict):
            agreement = float(consensus.get('agreement_ratio', 0) or 0)
            basis = str(consensus.get('basis', 'unknown') or 'unknown')
            engines_count = int(consensus.get('engines_executed_count', 0) or 0)
            supporting_count = int(consensus.get('engines_supporting_best_count', 0) or 0)
            supporting_engines = consensus.get('engines_supporting_best', [])

            self._mc(4,
                f"Motores executados: {engines_count} | "
                f"Motores suportando melhor candidato: {supporting_count} ({supporting_count}/{engines_count})")
            self._mc(4, f"Motores concordes: {', '.join([str(e) for e in supporting_engines])}")
            self._mc(4, f"Taxa de concordancia: {agreement:.1f}%")
            self._mc(4, f"Tipo de consenso: {basis}")

            if basis == "single_engine_or_no_consensus":
                self._mc(4,
                    "ATENCAO: Resultado obtido de apenas um motor OCR. "
                    "Recomenda-se validacao manual ou multi-motor.")

        self.pdf.ln(1)

    def _add_quality_analysis(self, image_quality):
        """Análise de qualidade de imagem."""
        self._section_title("ANALISE DE QUALIDADE FOTOGRAFICA")
        self.pdf.set_font("Arial", "", 9)

        if isinstance(image_quality, dict):
            blur = str(image_quality.get('blur_level', '?') or '?')
            contrast = float(image_quality.get('contrast_score', 0.5) or 0.5)
            brightness = str(image_quality.get('brightness_level', '?') or '?')
            rotation = float(image_quality.get('rotation_angle', 0) or 0)
            overall = float(image_quality.get('overall_quality_score', 0) or 0)

            self._mc(4,
                f"Nitidez: {blur} | Contraste: {contrast:.2f} | "
                f"Brilho: {brightness} | Rotacao: {rotation:.1f} graus")
            self._mc(4, f"Score geral de qualidade: {overall:.3f}")

            recommendations = image_quality.get('recommendations', [])
            if isinstance(recommendations, list) and recommendations:
                self.pdf.set_font("Arial", "B", 9)
                self.pdf.cell(0, 5, "Recomendacoes:", ln=True)
                self.pdf.set_font("Arial", "", 8)
                for rec in recommendations[:5]:
                    self._mc(4, f"- {str(rec)}")

        self.pdf.ln(1)

    def _add_scene_analysis(self, scene_brief_report, vehicle_analysis):
        """Análise de cena e contexto veicular."""
        self._section_title("ANALISE DE CENA E CONTEXTO OPERACIONAL")
        self.pdf.set_font("Arial", "", 9)

        if isinstance(scene_brief_report, dict):
            scene_type = str(scene_brief_report.get('scene_type', '?') or '?')
            capture = str(scene_brief_report.get('capture_condition', '?') or '?')
            context = str(scene_brief_report.get('operational_context', '?') or '?')
            conclusion = str(scene_brief_report.get('conclusion', '') or '')

            self._mc(4, f"Tipo de cena: {scene_type}")
            self._mc(4, f"Condicao de captura: {capture}")
            self._mc(4, f"Contexto operacional: {context}")

            if conclusion:
                self._mc(4, f"Conclusao preliminar: {conclusion}")

        if isinstance(vehicle_analysis, dict):
            vehicles = vehicle_analysis.get('vehicle_detections', [])
            if vehicles:
                self.pdf.ln(1)
                self.pdf.set_font("Arial", "B", 9)
                self.pdf.cell(0, 5, f"Veiculos detectados: {len(vehicles)}", ln=True)
                self.pdf.set_font("Arial", "", 8)
                for v in vehicles[:10]:
                    conf = float(v.get('confidence', 0) or 0)
                    class_name = str(v.get('class_name', '?') or '?')
                    self._mc(4, f"- {class_name}: confianca {conf:.3f}")

        self.pdf.ln(1)

    def _add_conclusion(self, pericial, assessment, warnings):
        """Conclusão pericial."""
        self._section_title("CONCLUSAO PERICIAL")
        self.pdf.set_font("Arial", "", 9)

        if isinstance(pericial, dict):
            status = str(pericial.get('status', '?') or '?')
            quality_score = float(pericial.get('quality', {}).get('score', 0) or 0)
            self._mc(4, f"Status: {status}")
            self._mc(4, f"Score de qualidade pericial: {quality_score:.3f}")

        if isinstance(assessment, dict):
            evidence_level = str(assessment.get('evidence_level', '?') or '?')
            recommendation = str(assessment.get('confidence_recommendation', '') or '')
            self._mc(4, f"Nivel de evidencia: {evidence_level}")

            if recommendation:
                self.pdf.set_font("Arial", "B", 9)
                self.pdf.cell(0, 5, "Recomendacao:", ln=True)
                self.pdf.set_font("Arial", "", 8)
                self._mc(4, recommendation)

        if isinstance(warnings, list) and warnings:
            self.pdf.ln(1)
            self.pdf.set_font("Arial", "B", 10)
            self.pdf.cell(0, 6, f"ALERTAS TECNICOS ({len(warnings)}):", ln=True)
            self.pdf.set_font("Arial", "", 8)
            for warning in warnings[:20]:
                self._mc(4, f"- {str(warning)}")

        self.pdf.ln(1)

    def _add_judicial_readiness(self, report_context, assessment):
        """Seção objetiva para triagem de uso jurídico da evidência."""
        self._section_title("PRONTIDAO JURIDICO-PERICIAL")
        self.pdf.set_font("Arial", "", 9)

        readiness = {}
        if isinstance(report_context, dict) and isinstance(report_context.get('judicial_readiness'), dict):
            readiness = report_context.get('judicial_readiness', {})

        if not readiness and isinstance(assessment, dict):
            readiness = {
                'status': str(assessment.get('judicial_readiness_status', '') or ''),
                'recommendation': str(assessment.get('judicial_recommendation', '') or ''),
            }

        status = str(readiness.get('status', 'indisponivel') or 'indisponivel')
        recommendation = str(readiness.get('recommendation', '') or '')

        self._mc(4, f"Status de triagem: {status}")
        if recommendation:
            self._mc(4, f"Recomendacao: {recommendation}")

        blockers = readiness.get('blockers', []) if isinstance(readiness, dict) else []
        cautions = readiness.get('cautions', []) if isinstance(readiness, dict) else []
        legal_notes = readiness.get('legal_notes', []) if isinstance(readiness, dict) else []

        if isinstance(blockers, list) and blockers:
            self.pdf.set_font("Arial", "B", 9)
            self.pdf.cell(0, 5, "Bloqueadores:", ln=True)
            self.pdf.set_font("Arial", "", 8)
            for item in blockers[:8]:
                self._mc(4, f"- {str(item)}")

        if isinstance(cautions, list) and cautions:
            self.pdf.set_font("Arial", "B", 9)
            self.pdf.cell(0, 5, "Riscos / cuidados:", ln=True)
            self.pdf.set_font("Arial", "", 8)
            for item in cautions[:10]:
                self._mc(4, f"- {str(item)}")

        if isinstance(legal_notes, list) and legal_notes:
            self.pdf.set_font("Arial", "B", 9)
            self.pdf.cell(0, 5, "Notas legais:", ln=True)
            self.pdf.set_font("Arial", "", 8)
            for item in legal_notes[:10]:
                self._mc(4, f"- {str(item)}")

        self.pdf.ln(1)

    def _add_certification(self, analysis_id):
        """Assinatura e certificação."""
        self.pdf.ln(2)
        self.pdf.set_font("Arial", "I", 8)
        self._mc(4,
            "Este relatorio foi gerado automaticamente pelo sistema GROM-OCR. "
            "Representa uma analise tecnica de evidencia digital submetida para identificacao de placa veicular "
            "via tecnicas de reconhecimento optico de caracteres (OCR). "
            "A confiabilidade deste relatorio e funcao da qualidade da imagem submetida e consenso entre motores OCR disponibilizados. "
            "Recomenda-se validacao manual de resultados criticos antes de uso em procedimentos legais.")

        self.pdf.ln(1)
        self.pdf.set_font("Arial", "", 8)
        timestamp = datetime.now(timezone.utc).isoformat()
        self._mc(4, f"Gerado em: {timestamp}")
        self._mc(4, f"ID de Analise: {analysis_id}")

    def generate(self, photo_path, plate_path, recognized_text, analysis_id, report_context,
                 vehicle_info, forensic, consensus, assessment, pericial, warnings, output_path):
        """Gera o PDF completo."""

        # Obtém timestamp
        timestamp_utc = datetime.now(timezone.utc).isoformat()

        # Construir PDF seção por seção
        self._add_header(analysis_id, timestamp_utc)
        self._add_cadeia_custodia(photo_path, plate_path)

        process_trace = report_context.get('process_trace', []) if isinstance(report_context, dict) else []
        ocr_engine_summary = report_context.get('ocr_engine_summary', {}) if isinstance(report_context, dict) else {}
        self._add_methodology(process_trace, ocr_engine_summary)

        self._add_evidence_photo(photo_path)

        top_candidates = report_context.get('top_candidates', []) if isinstance(report_context, dict) else []
        plate_analyses = report_context.get('plate_analyses', []) if isinstance(report_context, dict) else []
        self._add_multi_plate_analysis(top_candidates, plate_analyses)

        self._add_consensus_analysis(consensus, assessment)

        image_quality = report_context.get('image_quality', {}) if isinstance(report_context, dict) else {}
        self._add_quality_analysis(image_quality)

        scene_brief_report = report_context.get('scene_brief_report', {}) if isinstance(report_context, dict) else {}
        vehicle_analysis = report_context.get('vehicle_analysis', {}) if isinstance(report_context, dict) else {}
        self._add_scene_analysis(scene_brief_report, vehicle_analysis)

        self._add_judicial_readiness(report_context, assessment)

        self._add_conclusion(pericial, assessment, warnings)
        self._add_certification(analysis_id)

        # Salvar PDF
        try:
            self.pdf.output(output_path)
            return True, output_path
        except Exception as e:
            return False, str(e)


def generate_forensic_pdf(photo_path, plate_path, recognized_text, analysis_id, report_context,
                          vehicle_info, forensic, consensus, assessment, pericial, warnings, output_dir):
    """
    Função wrapper para gerar PDF forense.
    Retorna (pdf_filename, success_flag)
    """
    from pathlib import Path

    # Nome do arquivo
    source_name = os.path.basename(photo_path or 'report.jpg')
    name_without_ext = Path(source_name).stem
    pdf_name = f"relatorio_{name_without_ext}_{analysis_id}.pdf"
    output_path = os.path.join(output_dir, pdf_name)

    # Gerar PDF
    generator = ForensicPDF()
    success, result = generator.generate(
        photo_path, plate_path, recognized_text, analysis_id,
        report_context, vehicle_info, forensic, consensus,
        assessment, pericial, warnings, output_path
    )

    if success:
        return pdf_name, True
    else:
        return None, False
