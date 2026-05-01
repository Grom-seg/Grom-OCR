from flask import Flask, render_template_string, request, jsonify, send_file
import os
import json
from datetime import datetime
import glob

app = Flask(__name__)

# Caminhos dos resultados e imagens
RESULTS_DIR = "data"
IMAGES_DIR = "data/uploads"

# Template HTML do dashboard
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Dashboard Pericial GROM OCR</title>
    <style>body{font-family:sans-serif;}h2{color:#003366;}table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ccc;padding:6px;}th{background:#f4f4f4;}tr:hover{background:#eef;}img{max-width:300px;max-height:120px;}</style>
</head>
<body>
<h2>Dashboard Pericial GROM OCR</h2>
<form method="get">
    <label>Filtro por confiança mínima: <input type="number" name="min_conf" value="{{min_conf}}" min="0" max="100"></label>
    <button type="submit">Filtrar</button>
</form>
<table>
<tr><th>Data</th><th>Imagem</th><th>Leitura</th><th>Confiança</th><th>Conclusão</th><th>Relatório</th></tr>
{% for r in resultados %}
<tr>
    <td>{{r['data']}}</td>
    <td>{% if r['imagem'] %}<img src="/imagem/{{r['imagem']}}">{% endif %}</td>
    <td>{{r['leitura']}}</td>
    <td>{{r['confianca']}}%</td>
    <td>{{r['conclusao']}}</td>
    <td><a href="/relatorio/{{r['id']}}" target="_blank">Ver Relatório</a></td>
</tr>
{% endfor %}
</table>
</body></html>
'''

def carregar_resultados(min_conf=0):
    # Busca todos os arquivos de resultado OCR
    paths = glob.glob(os.path.join(RESULTS_DIR, "ocr_reranking_benchmark_results*.json"))
    resultados = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for idx, r in enumerate(data.get("results", [])):
            # Tenta obter confiança de múltiplos campos possíveis
            conf = (
                r.get("confidence")
                or r.get("observed_best_confidence")
                or r.get("observed_confidence")
                or 0
            )
            if conf is None:
                conf = 0
            try:
                conf = float(conf)
            except Exception:
                conf = 0
            if conf < min_conf:
                continue
            # Tenta obter leitura de múltiplos campos possíveis
            leitura = (
                r.get("observed_text")
                or r.get("observed_best_text")
                or r.get("top_candidate_text")
                or "INCONCLUSIVO"
            )
            if not leitura or not isinstance(leitura, str) or leitura.strip() == "":
                leitura = "INCONCLUSIVO"
            resultados.append({
                "id": f"{os.path.basename(path)}_{idx}",
                "data": data.get("generated_at_utc", ""),
                "imagem": os.path.basename(r.get("image", "")),
                "leitura": leitura,
                "confianca": conf,
                "conclusao": "INCONCLUSIVO" if conf < 95 else "IDENTIFICAÇÃO FORTE",
            })
    return resultados

@app.route("/")
def dashboard():
    min_conf = int(request.args.get("min_conf", 0))
    resultados = carregar_resultados(min_conf)
    return render_template_string(DASHBOARD_TEMPLATE, resultados=resultados, min_conf=min_conf)

@app.route("/imagem/<nome>")
def imagem(nome):
    path = os.path.join(IMAGES_DIR, nome)
    if os.path.exists(path):
        return send_file(path)
    return "Imagem não encontrada", 404

@app.route("/relatorio/<rid>")
def relatorio(rid):
    # Gera relatório estruturado para o resultado
    parts = rid.split("_", 1)
    if len(parts) != 2:
        return "ID inválido", 400
    path, idx = parts
    path = os.path.join(RESULTS_DIR, path)
    if not os.path.exists(path):
        return "Resultado não encontrado", 404
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    idx = int(idx)
    if idx >= len(data.get("results", [])):
        return "Índice inválido", 400
    r = data["results"][idx]
    # Busca confiança e leitura igual ao dashboard
    conf = (
        r.get("confidence")
        or r.get("observed_best_confidence")
        or r.get("observed_confidence")
        or 0
    )
    if conf is None:
        conf = 0
    try:
        conf = float(conf)
    except Exception:
        conf = 0
    leitura = (
        r.get("observed_text")
        or r.get("observed_best_text")
        or r.get("top_candidate_text")
        or "INCONCLUSIVO"
    )
    if not leitura or not isinstance(leitura, str) or leitura.strip() == "":
        leitura = "INCONCLUSIVO"
    estrutura = f"""
[1] RESUMO\nAnálise visual e OCR de placa veicular.\n
[2] QUALIDADE DA IMAGEM\n{r.get('quality_before', {})}\n
[3] ELEMENTOS DETECTADOS\n{r.get('notes', 'Não informado')}\n
[4] OCR / LEITURA\nLeitura provável: {leitura}\nConfiança global: {conf}%\n
[5] ANÁLISE TÉCNICA\nLeitura automática via OCR, validação obrigatória.\n
[6] LIMITAÇÕES\nVer qualidade da imagem e fatores ambientais.\n
[7] CONCLUSÃO\n{'INCONCLUSIVO' if conf < 95 else 'IDENTIFICAÇÃO FORTE (sujeita à validação)'}\n
[8] GRAU DE CONFIANÇA\n{conf}%\n
[9] RECOMENDAÇÃO OPERACIONAL\nRevisão humana obrigatória.\n
[10] OBSERVAÇÃO PERICIAL\nAnálise automatizada, não substitui perícia oficial."""
    return f"<pre>{estrutura}</pre>"

@app.route("/api/resultados")
def api_resultados():
    min_conf = int(request.args.get("min_conf", 0))
    resultados = carregar_resultados(min_conf)
    return jsonify(resultados)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
