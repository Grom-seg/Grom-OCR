import sys
import os
import json
import cv2
import numpy as np
from datetime import datetime

# Add project root to sys.path
sys.path.append('python')

# Import core logic (avoiding Flask overhead for direct test)
from utils.scene_preprocess import preprocess_scene_for_ocr
from utils.vehicle_analysis_protocol import build_operational_protocol

def run_forensic_test(image_path, expected_text=None):
    if not os.path.exists(image_path):
        return {"error": f"File not found: {image_path}"}
    
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Failed to load image: {image_path}"}
        
    print(f"Processing {os.path.basename(image_path)}...")
    
    # Simulate the pipeline
    # 1. Pre-processing (The core of our recent changes)
    enhanced, pre_meta = preprocess_scene_for_ocr(img)
    
    # 2. Mocking the OCR consensus for this test (since real OCR might be slow/failed in env)
    # In a real test, we would call the actual engine, but here we want to see the "Forensic Intelligence" metadata logic.
    
    # Save the enhanced image for the user to see
    out_dir = 'data/test_results'
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"enhanced_{os.path.basename(image_path)}")
    cv2.imwrite(out_path, enhanced)
    
    return {
        "filename": os.path.basename(image_path),
        "original_path": image_path,
        "enhanced_path": out_path,
        "metadata": pre_meta,
    }

def generate_report(results):
    report_path = 'data/test_results/forensic_test_report.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Relatório de Teste: Inteligência Forense Grom_OCR\n\n")
        f.write(f"Data do Teste: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for res in results:
            if "error" in res:
                continue
            
            f.write(f"## Imagem: {res['filename']}\n")
            f.write(f"- **Diagnóstico de Cena:** {res['metadata'].get('scenario_display_label', 'Indefinido')}\n")
            f.write(f"- **Filtro Selecionado:** `{res['metadata'].get('selected_variant', 'original')}`\n")
            f.write(f"- **Motivo da Seleção:** {res['metadata'].get('selection_reason', 'N/A')}\n")
            f.write(f"- **Melhoria Técnica (Score):** +{res['metadata'].get('improvement', 0.0)}\n\n")
            
            f.write("### Evidências Visuais\n")
            # In a real artifact I'd use links, but here I'm generating a file on disk.
            f.write(f"| Original | Processada Forense |\n")
            f.write(f"| :---: | :---: |\n")
            # Note: I can't embed local images in markdown that easily in the console,
            # but I will provide the paths.
            f.write(f"| [Ver Original]({res['original_path']}) | [Ver Enhanced]({res['enhanced_path']}) |\n\n")
            
            f.write("### Sequência Pericial (Steps)\n")
            f.write("```json\n")
            f.write(json.dumps(res['metadata'].get('steps', []), indent=2))
            f.write("\n```\n\n")
            f.write("---\n\n")
            
    return report_path

if __name__ == "__main__":
    test_images = [
        'data/uploads/plate_test_degraded.png',
        'data/uploads/20171119_154214_ch6-1024x576.jpg'
    ]
    
    all_results = []
    for img_p in test_images:
        all_results.append(run_forensic_test(img_p))
        
    report = generate_report(all_results)
    print(f"Relatório gerado em: {report}")
