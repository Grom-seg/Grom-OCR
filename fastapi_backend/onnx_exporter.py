"""
ONNX Exporter - Phase 4
Exporta o modelo YOLOv8 para formato ONNX com quantização INT8 opcional.

Uso direto:
    python -m fastapi_backend.onnx_exporter
    python -m fastapi_backend.onnx_exporter --quantize
"""
import argparse
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Caminhos padrão
_DEFAULT_PT_MODEL = os.getenv('GROM_YOLO_MODEL', 'yolov8n.pt')
_DEFAULT_ONNX_OUTPUT = os.getenv(
    'GROM_ONNX_MODEL',
    str(Path(_DEFAULT_PT_MODEL).with_suffix('.onnx')),
)
_DEFAULT_ONNX_INT8_OUTPUT = os.getenv(
    'GROM_ONNX_INT8_MODEL',
    str(Path(_DEFAULT_PT_MODEL).stem + '_int8.onnx'),
)


def export_to_onnx(
    pt_model_path: str = _DEFAULT_PT_MODEL,
    output_path: Optional[str] = None,
    imgsz: int = 640,
    dynamic: bool = False,
    simplify: bool = True,
    opset: int = 12,
) -> str:
    """
    Exporta modelo YOLOv8 para ONNX.

    Args:
        pt_model_path: Caminho para o arquivo .pt do modelo.
        output_path: Destino do .onnx. Se None, usa mesmo diretório do .pt.
        imgsz: Tamanho de entrada (padrão 640).
        dynamic: Habilita batch size dinâmico.
        simplify: Simplifica o grafo ONNX (requer onnx-simplifier).
        opset: Versão do opset ONNX.

    Returns:
        Caminho absoluto do arquivo .onnx gerado.

    Raises:
        FileNotFoundError: Se o modelo .pt não for encontrado.
        ImportError: Se ultralytics não estiver instalado.
        RuntimeError: Se a exportação falhar.
    """
    if not os.path.exists(pt_model_path):
        raise FileNotFoundError(f'Modelo não encontrado: {pt_model_path}')

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ImportError('ultralytics é necessário para exportar ONNX') from exc

    if output_path is None:
        output_path = str(Path(pt_model_path).with_suffix('.onnx'))

    logger.info('Exportando %s → %s (opset=%d, imgsz=%d)', pt_model_path, output_path, opset, imgsz)
    t0 = time.perf_counter()

    model = YOLO(pt_model_path)
    exported = model.export(
        format='onnx',
        imgsz=imgsz,
        dynamic=dynamic,
        simplify=simplify,
        opset=opset,
        half=False,
    )

    elapsed = time.perf_counter() - t0

    # ultralytics salva ao lado do .pt; se diferente do output_path, renomear
    if exported and str(exported) != output_path:
        import shutil
        shutil.move(str(exported), output_path)

    if not os.path.exists(output_path):
        raise RuntimeError(f'Export falhou: arquivo não encontrado em {output_path}')

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info('ONNX exportado: %s (%.1f MB, %.1fs)', output_path, size_mb, elapsed)
    return os.path.abspath(output_path)


def quantize_onnx_int8(
    onnx_path: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Quantiza modelo ONNX para INT8 usando onnxruntime quantization.

    Args:
        onnx_path: Caminho para o .onnx base.
        output_path: Destino do .onnx quantizado.

    Returns:
        Caminho absoluto do arquivo INT8 gerado.

    Raises:
        ImportError: Se onnxruntime tools não estiverem disponíveis.
        FileNotFoundError: Se onnx_path não existir.
    """
    if not os.path.exists(onnx_path):
        raise FileNotFoundError(f'ONNX não encontrado: {onnx_path}')

    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
    except ImportError as exc:
        raise ImportError('onnxruntime[tools] é necessário para quantização') from exc

    if output_path is None:
        stem = Path(onnx_path).stem
        output_path = str(Path(onnx_path).parent / f'{stem}_int8.onnx')

    logger.info('Quantizando %s → %s', onnx_path, output_path)
    t0 = time.perf_counter()

    quantize_dynamic(
        model_input=onnx_path,
        model_output=output_path,
        weight_type=QuantType.QInt8,
    )

    elapsed = time.perf_counter() - t0
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info('INT8 gerado: %s (%.1f MB, %.1fs)', output_path, size_mb, elapsed)
    return os.path.abspath(output_path)


def get_export_info(onnx_path: str) -> dict:
    """Retorna metadados do arquivo ONNX (inputs, outputs, tamanho)."""
    if not os.path.exists(onnx_path):
        return {'error': f'Arquivo não encontrado: {onnx_path}'}

    info = {
        'path': os.path.abspath(onnx_path),
        'size_mb': round(os.path.getsize(onnx_path) / (1024 * 1024), 2),
    }

    try:
        import onnx
        model = onnx.load(onnx_path)
        graph = model.graph
        info['inputs'] = [
            {'name': i.name, 'shape': [d.dim_value for d in i.type.tensor_type.shape.dim]}
            for i in graph.input
        ]
        info['outputs'] = [
            {'name': o.name, 'shape': [d.dim_value for d in o.type.tensor_type.shape.dim]}
            for o in graph.output
        ]
        info['opset_version'] = model.opset_import[0].version if model.opset_import else None
    except Exception as exc:
        info['onnx_metadata_error'] = str(exc)

    return info


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Exporta YOLOv8 para ONNX')
    parser.add_argument('--model', default=_DEFAULT_PT_MODEL, help='Caminho do .pt')
    parser.add_argument('--output', default=None, help='Destino do .onnx')
    parser.add_argument('--imgsz', type=int, default=640, help='Tamanho de entrada')
    parser.add_argument('--opset', type=int, default=12, help='Versão opset')
    parser.add_argument('--quantize', action='store_true', help='Gerar versão INT8')
    args = parser.parse_args()

    onnx_path = export_to_onnx(
        pt_model_path=args.model,
        output_path=args.output,
        imgsz=args.imgsz,
        opset=args.opset,
    )
    print(f'ONNX: {onnx_path}')
    print(get_export_info(onnx_path))

    if args.quantize:
        int8_path = quantize_onnx_int8(onnx_path)
        print(f'INT8: {int8_path}')
        print(get_export_info(int8_path))
