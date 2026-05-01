import json

with open(r'c:\Grom_OCR\data\test_results\last_simple_test.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

det = d.get('input_meta', {}).get('plate_detection', {})
print('--- REGIOES DETECTADAS (YOLO) ---')
for i, reg in enumerate(det.get('regions', [])):
    print(f"Reg {i}: score={reg.get('score',0):.2f} box={reg.get('box')} crop={reg.get('rel_path')}")

print('\n--- OCR RESULTS no Protocol ---')
context = d.get('operational_protocol', {}).get('context', {})
if not context:
    # try flat
    ocr = d.get('operational_protocol', {}).get('ocr_results', {})
else:
    ocr = context.get('ocr_results', {})

for eng, r in ocr.items():
    print(f"{eng}: [{r.get('text')}] conf={r.get('avg_conf',0):.1f}% regiao={r.get('region')}")
    # se hover sub resultados
    subs = r.get('results', r.get('candidates', []))
    if isinstance(subs, list):
         for sub in subs:
              print(f"  -> sub [{sub.get('text')}] conf={sub.get('avg_conf',0):.1f}% reg={sub.get('region')}")
