import subprocess
import sys
import os
from datetime import datetime

BENCHMARKS = [
    {
        "name": "scene_preprocess",
        "cmd": [
            sys.executable, "tools/benchmark_scene_preprocess.py",
            "--manifest", "data/scene_preprocess_benchmark_manifest.json",
            "--output", "data/scene_preprocess_benchmark_results.json",
            "--export-calibration", "data/scene_preprocess_calibration.generated.json"
        ]
    },
    {
        "name": "plate_detector",
        "cmd": [
            sys.executable, "tools/benchmark_plate_detector.py",
            "--manifest", "data/plate_detector_benchmark_manifest.json",
            "--output", "data/plate_detector_benchmark_results.json",
            "--export-calibration", "data/plate_detector_calibration.generated.json"
        ]
    },
    {
        "name": "ocr_reranking",
        "cmd": [
            sys.executable, "tools/benchmark_ocr_reranking.py",
            "--manifest", "data/ocr_reranking_benchmark_manifest_raster.json",
            "--output", "data/ocr_reranking_benchmark_results_raster.json",
            "--export-calibration", "data/ocr_reranking_calibration_raster.generated.json",
            "--direct"
        ]
    }
]

report_lines = []
report_lines.append(f"Relatório consolidado de benchmarks - {datetime.now().isoformat()}")
report_lines.append("")

for bench in BENCHMARKS:
    report_lines.append(f"Executando: {bench['name']}")
    try:
        result = subprocess.run(bench["cmd"], capture_output=True, text=True, check=True)
        report_lines.append("Saída:")
        report_lines.append(result.stdout.strip())
        if result.stderr.strip():
            report_lines.append("Erros:")
            report_lines.append(result.stderr.strip())
    except subprocess.CalledProcessError as e:
        report_lines.append(f"Erro ao executar {bench['name']}:")
        report_lines.append(e.stdout or "")
        report_lines.append(e.stderr or "")
    report_lines.append("\n" + ("-"*60) + "\n")

# Salva relatório consolidado
with open("data/benchmark_consolidated_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print("Execução sequencial concluída. Relatório salvo em data/benchmark_consolidated_report.txt")
