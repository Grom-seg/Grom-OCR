import json
import os
from datetime import datetime
import matplotlib.pyplot as plt

# Caminhos dos resultados
RESULTS = [
    ("Preprocessamento", "data/scene_preprocess_benchmark_results.json"),
    ("Detecção de Placas", "data/plate_detector_benchmark_results.json"),
    ("OCR Reranking", "data/ocr_reranking_benchmark_results_raster.json")
]

report_lines = []
report_lines.append(f"Relatório Visual Consolidado - {datetime.now().isoformat()}")
report_lines.append("")

# Geração de gráficos e análise
for name, path in RESULTS:
    if not os.path.exists(path):
        report_lines.append(f"Arquivo não encontrado: {path}")
        continue
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    report_lines.append(f"== {name} ==")
    if "summary" in data:
        summary = data["summary"]
    else:
        summary = data
    # Métricas principais
    for k, v in summary.items():
        if isinstance(v, (int, float, str)):
            report_lines.append(f"{k}: {v}")
    # Gráfico de acurácia por cenário (se disponível)
    if "scenario_summary" in summary:
        scenarios = summary["scenario_summary"]
        labels = list(scenarios.keys())
        accs = [scenarios[s].get("accuracy_percent", 0) for s in labels]
        plt.figure(figsize=(6,3))
        plt.bar(labels, accs, color='royalblue')
        plt.title(f"Acurácia por cenário - {name}")
        plt.ylabel("Acurácia (%)")
        plt.tight_layout()
        img_path = f"data/{name.lower().replace(' ', '_')}_accuracy.png"
        plt.savefig(img_path)
        plt.close()
        report_lines.append(f"Gráfico salvo em: {img_path}")
    report_lines.append("")
    report_lines.append("-"*60)

# Salva relatório visual consolidado
with open("data/benchmark_visual_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print("Relatório visual consolidado gerado em data/benchmark_visual_report.txt")

# Notificação automática (exemplo: print, pode ser adaptado para e-mail, webhook, etc)
try:
    import smtplib
    from email.mime.text import MIMEText
    # Configuração de exemplo (ajuste para produção)
    SMTP_SERVER = os.environ.get('SMTP_SERVER')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER = os.environ.get('SMTP_USER')
    SMTP_PASS = os.environ.get('SMTP_PASS')
    EMAIL_TO = os.environ.get('EMAIL_TO')
    if SMTP_SERVER and SMTP_USER and SMTP_PASS and EMAIL_TO:
        msg = MIMEText("Relatório visual consolidado gerado com sucesso.")
        msg['Subject'] = 'Benchmark GROM OCR - Relatório Visual'
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
        print(f"Notificação enviada para {EMAIL_TO}")
    else:
        print("Notificação automática não configurada (variáveis de ambiente ausentes)")
except Exception as e:
    print(f"Falha ao enviar notificação automática: {e}")
