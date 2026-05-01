import json
with open(r'c:\Grom_OCR\data\test_results\last_process_test.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

ocr_results = d.get('ocr', {})
for name, payload in ocr_results.items():
    if not isinstance(payload, dict): continue
    print(f'Engine: {name}')
    for c in payload.get('candidates', [])[:10]:
        print(f"  - {c.get('text')} (score={c.get('score')})")
