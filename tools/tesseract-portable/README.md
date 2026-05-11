# Tesseract Portatil (Distribuicao Externa)

Este diretorio e apenas um placeholder.

A partir da transicao para a versao 2.0 (aplicacao PHP + backend Python),
o pacote binario do Tesseract deixou de ser versionado no repositorio
para reduzir peso e acelerar clone/pull.

No startup, o bootstrap automatico tenta preparar o runtime usando:

1. `GROM_OCR_TESSERACT_ARTIFACT_PATH` (zip local)
2. `GROM_OCR_TESSERACT_ARTIFACT_URL` (download remoto)
3. `config/tesseract_artifact.json` (config local opcional)

Script responsavel: `tools/bootstrap_tesseract_portable.py`.

Se o bootstrap nao estiver configurado, o sistema ainda tenta fallback para:

- caminho local antigo (se existir)
- instalacao de sistema em `C:\Program Files\Tesseract-OCR`
