#!/usr/bin/env python
"""
Script auxiliar para mockar um endpoint /process com fallback funcional
Rodará como servidor na porta 8888 (não interfere com FastAPI na 8000)
"""

from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Forçar token
os.environ['PLATE_RECOGNIZER_TOKEN'] = 'demo_token'

from fastapi_backend.plate_recognizer_v2 import recognize_plate_external

@app.route('/process-fallback', methods=['POST'])
def process_with_fallback():
    """Proxy simples que chama /process e se OCR vazio, chama Plate Recognizer"""

    files = request.files
    upload_file = files.get('image') or files.get('file')

    if not upload_file:
        return {'error': 'arquivo obrigatório'}, 400

    # Salvar temp
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
        upload_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        # Chamar FastAPI /process
        with open(tmp_path, 'rb') as f:
            resp = requests.post(
                'http://127.0.0.1:8000/process',
                files={'image': f},
                data={'analysis_stage': 'final'},
                timeout=120
            )

        result = resp.json()

        # Verificar se OCR falhou
        best = result.get('best', {})
        ocr_text = best.get('text', '').strip()

        if not ocr_text or len(ocr_text) < 3:
            # Fallback: tentar Plate Recognizer
            success, plate, metadata = recognize_plate_external(tmp_path)
            if success:
                result['best'] = {
                    'text': plate,
                    'engine': 'plate_recognizer_api',
                    'confidence': metadata.get('confidence', 0.95),
                    'score': metadata.get('confidence', 0.95),
                }
                result['fallback_used'] = True
                result['warnings'] = result.get('warnings', [])
                result['warnings'].append('ocr_local_fallback_to_plate_recognizer')

        return result
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

if __name__ == '__main__':
    print("✓ Servidor fallback rodando em http://127.0.0.1:8888/process-fallback")
    app.run(host='127.0.0.1', port=8888, debug=False)
