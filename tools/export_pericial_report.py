import json
import os
from datetime import datetime
from fpdf import FPDF
from jinja2 import Template
import requests

# Configurações
RESULTS_PATH = "data/ocr_reranking_benchmark_results_raster.json"
HTML_REPORT_PATH = "data/relatorio_pericial_placa.html"
PDF_REPORT_PATH = "data/relatorio_pericial_placa.pdf"
WEBHOOK_URL = os.environ.get("GROM_OCR_WEBHOOK_URL")

# Template HTML estruturado
HTML_TEMPLATE = '''
<html><head><meta charset="utf-8"><title>Relatório Pericial - OCR Placa</title>
<style>body{font-family:sans-serif;}h2{color:#003366;}pre{background:#f4f4f4;padding:8px;}</style></head><body>
<h2>Relatório Pericial Estruturado - OCR de Placa Veicular</h2>
<p><b>Data:</b> {{ data }}</p>
<pre>{{ estrutura }}</pre>
</body></html>
'''

def gerar_estrutura_pericial(result):
    # Estrutura pericial conforme diretriz
    estrutura = []
    estrutura.append("[1] RESUMO\nFoi realizada análise visual e OCR de placa veicular.")
    estrutura.append(f"[2] QUALIDADE DA IMAGEM\n{result.get('qualidade_imagem', 'Não avaliada')}")
    estrutura.append(f"[3] ELEMENTOS DETECTADOS\n{result.get('elementos_detectados', 'Não detectados')}")
    estrutura.append(f"[4] OCR / LEITURA\nLeitura provável: {result.get('leitura', 'INCONCLUSIVO')}\nConfiança global: {result.get('confianca_global', 'INDETERMINADA')}%\nCaracteres: {result.get('caracteres', 'Não avaliados')}")
    estrutura.append(f"[5] ANÁLISE TÉCNICA\n{result.get('analise_tecnica', 'Não realizada')}")
    estrutura.append(f"[6] LIMITAÇÕES\n{result.get('limitacoes', 'Não informadas')}")
    estrutura.append(f"[7] CONCLUSÃO\n{result.get('conclusao', 'INCONCLUSIVO')}")
    estrutura.append(f"[8] GRAU DE CONFIANÇA\n{result.get('confianca_global', 'INDETERMINADA')}%")
    estrutura.append(f"[9] RECOMENDAÇÃO OPERACIONAL\n{result.get('recomendacao', 'Revisão humana obrigatória.')}")
    estrutura.append(f"[10] OBSERVAÇÃO PERICIAL\n{result.get('observacao', 'Análise auxiliar, não substitui perícia oficial.')}")
    return "\n\n".join(estrutura)

def extrair_resultado_ocr(path):
    # Exemplo: extrai o melhor resultado do benchmark OCR
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Busca o melhor match
    best = None
    for r in data.get("results", []):
        if r.get("matched"):
            best = r
            break
    if not best and data.get("results"):
        best = data["results"][0]
    if not best:
        return None
    # Monta estrutura pericial
    return {
        "qualidade_imagem": best.get("quality_before", {}),
        "elementos_detectados": best.get("notes", "Não informado"),
        "leitura": best.get("observed_text", "INCONCLUSIVO"),
        "confianca_global": best.get("confidence", 0),
        "caracteres": best.get("observed_text", "INCONCLUSIVO"),
        "analise_tecnica": "Leitura automática via OCR, validação obrigatória.",
        "limitacoes": "Ver qualidade da imagem e fatores ambientais.",
        "conclusao": "INCONCLUSIVO" if best.get("confidence", 0) < 95 else "IDENTIFICAÇÃO FORTE (sujeita à validação)",
        "recomendacao": "Revisão humana obrigatória.",
        "observacao": "Análise automatizada, não substitui perícia oficial."
    }

def gerar_html(estrutura):
    t = Template(HTML_TEMPLATE)
    return t.render(data=datetime.now().isoformat(), estrutura=estrutura)

def gerar_pdf(html, pdf_path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    for line in html.split("\n"):
        pdf.multi_cell(0, 8, line)
    pdf.output(pdf_path)

def enviar_webhook(payload):
    if not WEBHOOK_URL:
        print("Webhook não configurado.")
        return
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Webhook enviado: {resp.status_code}")
    except Exception as e:
        print(f"Falha ao enviar webhook: {e}")

if __name__ == "__main__":
    resultado = extrair_resultado_ocr(RESULTS_PATH)
    if not resultado:
        print("Nenhum resultado OCR encontrado.")
        exit(1)
    estrutura = gerar_estrutura_pericial(resultado)
    html = gerar_html(estrutura)
    with open(HTML_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    gerar_pdf(estrutura, PDF_REPORT_PATH)
    print(f"Relatórios HTML e PDF gerados.")
    enviar_webhook({"timestamp": datetime.now().isoformat(), "estrutura": estrutura})
