import os
import requests

API_URL = "http://127.0.0.1:8000"
IMG_DIR = os.path.join('data', 'datasets', 'Imagens')

# Busca uma imagem de exemplo
img_path = None
if os.path.exists(IMG_DIR):
    for f in os.listdir(IMG_DIR):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            img_path = os.path.join(IMG_DIR, f)
            break

if not img_path:
    print(f"Nenhuma imagem encontrada em {IMG_DIR}. Adicione imagens para testar.")
    exit(1)

with open(img_path, 'rb') as img_file:
    files = {'file': (os.path.basename(img_path), img_file, 'image/jpeg')}
    print(f"Testando /detect-plate/ com {img_path}")
    r = requests.post(f"{API_URL}/detect-plate/", files=files)
    print(r.json())

with open(img_path, 'rb') as img_file:
    files = {'file': (os.path.basename(img_path), img_file, 'image/jpeg')}
    print(f"Testando /ocr-plate/ com {img_path}")
    r = requests.post(f"{API_URL}/ocr-plate/", files=files)
    print(r.json())

with open(img_path, 'rb') as img_file:
    files = {'file': (os.path.basename(img_path), img_file, 'image/jpeg')}
    print(f"Testando /full-pipeline/ com {img_path}")
    r = requests.post(f"{API_URL}/full-pipeline/", files=files)
    print(r.json())
