import os

IMG_DIR = os.path.join('data', 'datasets', 'Imagens')

print(f"Listando arquivos em: {IMG_DIR}\n")
if not os.path.exists(IMG_DIR):
    print(f"[ERRO] Caminho não encontrado: {IMG_DIR}")
    exit(1)

arquivos = os.listdir(IMG_DIR)
if arquivos:
    for f in arquivos:
        print(f)
    print(f"\nTotal de arquivos encontrados: {len(arquivos)}")
else:
    print("Nenhum arquivo encontrado.")
