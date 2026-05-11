import os
from pathlib import Path
from typing import Dict, Optional


def _existing_file(path_value: str) -> Optional[str]:
    value = (path_value or '').strip()
    if not value:
        return None
    if os.path.isfile(value):
        return value
    return None


def _existing_dir(path_value: str) -> Optional[str]:
    value = (path_value or '').strip()
    if not value:
        return None
    if os.path.isdir(value):
        return value
    return None


def _cmd_from_root(root_value: str) -> Optional[str]:
    root = _existing_dir(root_value)
    if not root:
        return None
    candidate = os.path.join(root, 'tesseract.exe')
    return candidate if os.path.isfile(candidate) else None


def resolve_tesseract_runtime(project_root: Optional[str] = None) -> Dict[str, str]:
    root = project_root or str(Path(__file__).resolve().parents[2])

    cmd_candidates = [
        ('GROM_OCR_TESSERACT_CMD', _existing_file(os.environ.get('GROM_OCR_TESSERACT_CMD', ''))),
        ('TESSERACT_CMD', _existing_file(os.environ.get('TESSERACT_CMD', ''))),
        ('GROM_OCR_TESSERACT_ROOT', _cmd_from_root(os.environ.get('GROM_OCR_TESSERACT_ROOT', ''))),
        ('GROM_OCR_TESSERACT_PORTABLE_DIR', _cmd_from_root(os.environ.get('GROM_OCR_TESSERACT_PORTABLE_DIR', ''))),
        (
            'project_default',
            _existing_file(os.path.join(root, 'tools', 'tesseract-portable', 'tesseract.exe')),
        ),
        ('system_default_program_files', _existing_file(r'C:\Program Files\Tesseract-OCR\tesseract.exe')),
        ('system_default_program_files_x86', _existing_file(r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe')),
    ]

    selected_cmd = ''
    cmd_source = 'not_found'
    for source, candidate in cmd_candidates:
        if candidate:
            selected_cmd = candidate
            cmd_source = source
            break

    tess_candidates = [
        ('TESSDATA_PREFIX', _existing_dir(os.environ.get('TESSDATA_PREFIX', ''))),
        ('GROM_OCR_TESSDATA_PREFIX', _existing_dir(os.environ.get('GROM_OCR_TESSDATA_PREFIX', ''))),
    ]

    if selected_cmd:
        tess_candidates.append(('sibling_tessdata', _existing_dir(os.path.join(os.path.dirname(selected_cmd), 'tessdata'))))

    root_from_env = _existing_dir(os.environ.get('GROM_OCR_TESSERACT_ROOT', ''))
    if root_from_env:
        tess_candidates.append(('tesseract_root_tessdata', _existing_dir(os.path.join(root_from_env, 'tessdata'))))

    portable_dir_from_env = _existing_dir(os.environ.get('GROM_OCR_TESSERACT_PORTABLE_DIR', ''))
    if portable_dir_from_env:
        tess_candidates.append(('portable_dir_tessdata', _existing_dir(os.path.join(portable_dir_from_env, 'tessdata'))))

    tess_candidates.append(
        (
            'project_default_tessdata',
            _existing_dir(os.path.join(root, 'tools', 'tesseract-portable', 'tessdata')),
        )
    )

    selected_tessdata = ''
    tessdata_source = 'not_found'
    for source, candidate in tess_candidates:
        if candidate:
            selected_tessdata = candidate
            tessdata_source = source
            break

    return {
        'cmd': selected_cmd,
        'cmd_source': cmd_source,
        'tessdata_prefix': selected_tessdata,
        'tessdata_source': tessdata_source,
    }


def apply_tesseract_env_defaults(project_root: Optional[str] = None) -> Dict[str, str]:
    runtime = resolve_tesseract_runtime(project_root=project_root)
    if runtime.get('cmd'):
        os.environ.setdefault('GROM_OCR_TESSERACT_CMD', runtime['cmd'])
    if runtime.get('tessdata_prefix'):
        os.environ.setdefault('TESSDATA_PREFIX', runtime['tessdata_prefix'])
    return runtime
