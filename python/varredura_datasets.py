import os

# Parâmetros para datasets conhecidos
DATASETS = [
    'data/datasets/ccpd',
    'data/datasets/rodosol-alpr',
    'data/datasets/ufpr-planalto801',
    'data/datasets/Artificial-Mercosur-License-Plates',
    'data/datasets/Brazil-Plates-Detector',
    'data/datasets/LPLC',
    'data/datasets/grom-ocr',
]

print("\n[Varredura automática de datasets no projeto]")

for dataset_path in DATASETS:
    abs_path = os.path.abspath(dataset_path)
    print(f"\n--- {dataset_path} ---")
    if os.path.exists(dataset_path):
        for root, dirs, files in os.walk(dataset_path):
            level = root.replace(dataset_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for f in files:
                print(f"{subindent}{f}")
    else:
        print(f"[AVISO] Caminho não encontrado: {abs_path}")

# Varredura total do projeto para encontrar outros datasets
print("\n[Varredura total do projeto por possíveis datasets]")
for root, dirs, files in os.walk('.'):
    for d in dirs:
        if any(x in d.lower() for x in ['dataset', 'alpr', 'plate', 'placa', 'ocr']):
            print(f"Possível dataset encontrado: {os.path.join(root, d)}")
