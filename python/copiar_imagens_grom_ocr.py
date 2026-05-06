import os
import shutil

# Caminho de origem fornecido pelo usuário
ORIGEM = r"C:\Users\Família Grom\OneDrive\Desktop\Josuel\Placas"
DESTINO = os.path.join('data', 'datasets', 'grom-ocr', 'imagens')

# Cria o diretório de destino, se não existir
os.makedirs(DESTINO, exist_ok=True)

# Copia todas as imagens jpg/png do diretório de origem para o destino
copiados = 0
for root, dirs, files in os.walk(ORIGEM):
    for f in files:
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            src = os.path.join(root, f)
            dst = os.path.join(DESTINO, f)
            shutil.copy2(src, dst)
            copiados += 1

print(f"{copiados} imagens copiadas para {DESTINO}")
