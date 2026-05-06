import os

DATASET_PATH = os.path.join('data', 'datasets', 'ufpr-planalto801')

print(f"Listando arquivos e pastas em: {DATASET_PATH}\n")

if not os.path.exists(DATASET_PATH):
    print(f"[ERRO] Caminho não encontrado: {DATASET_PATH}")
    exit(1)

for root, dirs, files in os.walk(DATASET_PATH):
    level = root.replace(DATASET_PATH, '').count(os.sep)
    indent = ' ' * 2 * level
    print(f"{indent}{os.path.basename(root)}/")
    subindent = ' ' * 2 * (level + 1)
    for f in files:
        print(f"{subindent}{f}")
