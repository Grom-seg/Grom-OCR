# Grom_OCR

Sistema hibrido em PHP + Python para leitura OCR de placas, registro de analises e geracao de relatorios PDF.

## Linha de Versao

- v1.0: plataforma inicial concentrada em Python.
- v2.0: evolucao para aplicacao web em PHP com backend Python de OCR/forense.

Para reduzir peso do repositorio na v2.0, o pacote binario do Tesseract portatil foi migrado para distribuicao externa (release/artefato), com bootstrap e validacao automatica no startup.

## Estrutura

- `public/`: entradas web em PHP (`index.php`, `login.php`, `upload.php`, `historico.php`, `logout.php`)
- `app/controllers/`: fluxo de autenticacao, dashboard e persistencia
- `app/models/`: acesso a dados
- `app/services/`: integracoes auxiliares, incluindo conexao PDO e consulta externa
- `config/`: configuracao da aplicacao e banco
- `python/`: API Flask responsavel pelo OCR e pelo PDF
- `python/utils/vehicle_analysis_protocol.py`: protocolo operacional pericial com preservacao de evidencia, triagem, OCR, matriz de compatibilidade e conclusao
- `python/utils/scene_preprocess.py`: limpeza e normalizacao da cena antes do OCR
- `python/utils/plate_geometry.py`: geometria da placa, correcao de perspectiva e qualidade do recorte canônico

## Dependencias

- PHP 8+ com extensoes `curl`, `pdo`, `pdo_mysql`
- MySQL ou MariaDB
- Python 3.10+ com `pip`
- Tesseract OCR instalado no sistema
- Opcional: `easyocr`, `rapidocr-onnxruntime`, `pypdfium2`, `transformers`, `sentencepiece`, `safetensors`, `python-doctr`, `paddleocr`, `ultralytics`
- Observacao: `paddleocr` pode exigir `paddlepaddle` no ambiente, dependendo da plataforma.

## Configuracao

Defina as variaveis abaixo antes de subir o sistema:

- `GROM_OCR_DB_HOST`
- `GROM_OCR_DB_PORT`
- `GROM_OCR_DB_NAME`
- `GROM_OCR_DB_USER`
- `GROM_OCR_DB_PASS`
- `GROM_OCR_DB_CHARSET`
- `GROM_OCR_PYTHON_API_URL`
- `GROM_OCR_MIN_CONFIDENCE`
- `GROM_OCR_FORCE_ENSEMBLE`
- `GROM_OCR_ALLOW_HEAVY_COLDSTART`
- `GROM_OCR_ENSEMBLE_TOP_PER_ENGINE`
- `GROM_OCR_ENSEMBLE_WEIGHTS`
- `GROM_OCR_CHAIN_SIGNING_KEY`
- `GROM_OCR_UPLOAD_DIR`
- `PLATE_RECOGNIZER_TOKEN`
- `PLATE_RECOGNIZER_TIMEOUT`
- `GROM_OCR_PLATE_RECOGNIZER_DYNAMIC_VARIANTS`
- `GROM_OCR_PLATE_RECOGNIZER_MAX_VARIANTS`
- `GROM_OCR_PLATE_RECOGNIZER_TOP_RESULTS`
- `GROM_OCR_PLATE_RECOGNIZER_HIT_BONUS`
- `GROM_OCR_PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_SCORE`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_CONF`
- `GROM_OCR_PLATE_RECOGNIZER_PATTERN_MIN_SCORE`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_VARIANT_HITS`
- `GROM_OCR_VEHICLE_LOOKUP_URL`
- `GROM_OCR_VEHICLE_LOOKUP_URLS`
- `GROM_OCR_SENATRAN_ENABLE`
- `GROM_OCR_SENATRAN_URL`
- `GROM_OCR_SENATRAN_METHOD`
- `GROM_OCR_SENATRAN_PLATE_PARAM`
- `GROM_OCR_SENATRAN_TOKEN`
- `GROM_OCR_SENATRAN_TOKEN_HEADER`
- `GROM_OCR_SENATRAN_TOKEN_PREFIX`
- `GROM_OCR_SENATRAN_EXTRA_HEADERS`
- `GROM_OCR_SENATRAN_RESPONSE_PATH`
- `GROM_OCR_SENATRAN_SOURCE_LABEL`
- `GROM_OCR_SENATRAN_SOURCE_KIND`
- `GROM_OCR_SENATRAN_PRIORITY`
- `GROM_OCR_PRODESP_ENABLE`
- `GROM_OCR_PRODESP_URL`
- `GROM_OCR_PRODESP_METHOD`
- `GROM_OCR_PRODESP_PLATE_PARAM`
- `GROM_OCR_PRODESP_TOKEN`
- `GROM_OCR_PRODESP_TOKEN_HEADER`
- `GROM_OCR_PRODESP_TOKEN_PREFIX`
- `GROM_OCR_PRODESP_EXTRA_HEADERS`
- `GROM_OCR_PRODESP_RESPONSE_PATH`
- `GROM_OCR_PRODESP_SOURCE_LABEL`
- `GROM_OCR_PRODESP_SOURCE_KIND`
- `GROM_OCR_PRODESP_PRIORITY`
- `GROM_OCR_VEHICLE_LOOKUP_TOKEN`
- `GROM_OCR_VEHICLE_LOOKUP_TOKEN_HEADER`
- `GROM_OCR_VEHICLE_LOOKUP_TOKEN_PREFIX`
- `GROM_OCR_VEHICLE_LOOKUP_EXTRA_HEADERS`
- `GROM_OCR_VEHICLE_LOOKUP_TIMEOUT`
- `GROM_OCR_VEHICLE_LOOKUP_MAX_SOURCES` (limita quantas fontes configuradas sao consultadas por placa)
- `GROM_OCR_VEHICLE_LOOKUP_SOURCE_KIND` (ex.: `official_senatran`, `official_serpro`, `official_prodesp`, `official_sinesp`, `external_provider`)
- `GROM_OCR_VEHICLE_LOOKUP_STRICT_OFFICIAL=0` (use `1` para exigir fonte classificada como oficial)
- `GROM_OCR_VEHICLE_REVEAL_SENSITIVE_FIELDS=0` (use `1` apenas em ambiente com controle de acesso rigoroso)
- `GROM_OCR_OPEN_DATA_ENABLE`
- `GROM_OCR_OPEN_DATA_FIPE_BASE_URL`
- `GROM_OCR_OPEN_DATA_FIPE_TOKEN`
- `GROM_OCR_OPEN_DATA_TIMEOUT`
- `GROM_OCR_HTTP_CA_BUNDLE`
- `GROM_OCR_HTTP_INSECURE_SKIP_VERIFY`
- `GROM_OCR_EXTERNAL_COMPARE_ENABLE`
- `GROM_OCR_EXTERNAL_COMPARE_TIMEOUT`
- `GROM_OCR_EXTERNAL_COMPARE_MAX_CANDIDATES`
- `OPENALPR_SECRET_KEY`
- `GROM_OCR_OPENALPR_ENDPOINT`
- `GROM_OCR_OPENALPR_COUNTRY`
- `GROM_OCR_OPENALPR_RECOGNIZE_VEHICLE`
- `GROM_OCR_OPENALPR_TOPN`
- `GROM_OCR_NOMEROFF_COMPARE_ENDPOINT`
- `GROM_OCR_NOMEROFF_COMPARE_TOKEN`
- `GROM_OCR_NOMEROFF_COMPARE_TOKEN_HEADER`
- `GROM_OCR_AUDIT_LOG_PATH`
- `GROM_OCR_ADMIN_USER`
- `GROM_OCR_ADMIN_PASS_HASH`
- `GROM_OCR_ADMIN_PASS`
- `GROM_OCR_TESSERACT_CMD`
- `GROM_OCR_TESSERACT_ROOT` (opcional; pasta externa contendo `tesseract.exe` e `tessdata`)
- `GROM_OCR_TESSERACT_PORTABLE_DIR` (opcional; alias para pasta do pacote portátil)
- `GROM_OCR_TESSDATA_PREFIX` (opcional; override explícito de `tessdata`)
- `TESSDATA_PREFIX`
- `GROM_OCR_TESSERACT_ARTIFACT_URL` (URL do ZIP do pacote portatil)
- `GROM_OCR_TESSERACT_ARTIFACT_PATH` (caminho local para ZIP do pacote portatil)
- `GROM_OCR_TESSERACT_ARTIFACT_SHA256` (hash opcional para validacao de integridade)
- `GROM_OCR_TESSERACT_BOOTSTRAP` (default `1`; use `0` para desativar bootstrap automatico)
- `GROM_OCR_ENABLE_EASYOCR`
- `GROM_OCR_ENABLE_RAPIDOCR`
- `GROM_OCR_ENABLE_PADDLEOCR`
- `GROM_OCR_ENABLE_TROCR`
- `GROM_OCR_ENABLE_DOCTR`
- `GROM_OCR_EASYOCR_ALLOWLIST`
- `GROM_OCR_EASYOCR_DECODER`
- `GROM_OCR_EASYOCR_BEAM_WIDTH`
- `GROM_OCR_EASYOCR_HIT_BONUS`
- `GROM_OCR_EASYOCR_REGION_EARLY_SCORE`
- `GROM_OCR_EASYOCR_DYNAMIC_VARIANTS`
- `GROM_OCR_EASYOCR_MAX_VARIANTS`
- `GROM_OCR_EASYOCR_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_EASYOCR_MIN_ACCEPT_SCORE`
- `GROM_OCR_EASYOCR_MIN_ACCEPT_CONF`
- `GROM_OCR_EASYOCR_PATTERN_MIN_SCORE`
- `GROM_OCR_EASYOCR_MIN_VARIANT_HITS`
- `GROM_OCR_RAPIDOCR_HIT_BONUS`
- `GROM_OCR_RAPIDOCR_REGION_EARLY_SCORE`
- `GROM_OCR_RAPIDOCR_DYNAMIC_VARIANTS`
- `GROM_OCR_RAPIDOCR_MAX_VARIANTS`
- `GROM_OCR_RAPIDOCR_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_RAPIDOCR_MIN_ACCEPT_SCORE`
- `GROM_OCR_RAPIDOCR_MIN_ACCEPT_CONF`
- `GROM_OCR_RAPIDOCR_PATTERN_MIN_SCORE`
- `GROM_OCR_RAPIDOCR_MIN_VARIANT_HITS`
- `GROM_OCR_PADDLEOCR_LANG`
- `GROM_OCR_PADDLEOCR_USE_GPU`
- `GROM_OCR_PADDLEOCR_USE_ANGLE_CLS`
- `GROM_OCR_PADDLEOCR_DYNAMIC_VARIANTS`
- `GROM_OCR_PADDLEOCR_MAX_VARIANTS`
- `GROM_OCR_PADDLEOCR_REGION_LIMIT`
- `GROM_OCR_PADDLEOCR_REGION_EARLY_SCORE`
- `GROM_OCR_PADDLEOCR_HIT_BONUS`
- `GROM_OCR_PADDLEOCR_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_PADDLEOCR_MIN_ACCEPT_SCORE`
- `GROM_OCR_PADDLEOCR_MIN_ACCEPT_CONF`
- `GROM_OCR_PADDLEOCR_PATTERN_MIN_SCORE`
- `GROM_OCR_PADDLEOCR_MIN_VARIANT_HITS`
- `GROM_OCR_TROCR_MODEL_ID`
- `GROM_OCR_TROCR_MAX_NEW_TOKENS`
- `GROM_OCR_TROCR_REGION_LIMIT`
- `GROM_OCR_TROCR_HIT_BONUS`
- `GROM_OCR_TROCR_REGION_EARLY_SCORE`
- `GROM_OCR_TROCR_BASE_CONFIDENCE`
- `GROM_OCR_TROCR_LOCAL_ONLY`
- `GROM_OCR_TROCR_DYNAMIC_VARIANTS`
- `GROM_OCR_TROCR_MAX_VARIANTS`
- `GROM_OCR_TROCR_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_TROCR_MIN_ACCEPT_SCORE`
- `GROM_OCR_TROCR_MIN_ACCEPT_CONF`
- `GROM_OCR_TROCR_PATTERN_MIN_SCORE`
- `GROM_OCR_TROCR_MIN_VARIANT_HITS`
- `GROM_OCR_TESSERACT_MAX_VARIANTS`
- `GROM_OCR_TESSERACT_PSM_MODES`
- `GROM_OCR_TESSERACT_HIT_BONUS`
- `GROM_OCR_TESSERACT_MIN_ACCEPT_SCORE`
- `GROM_OCR_TESSERACT_MIN_ACCEPT_CONF`
- `GROM_OCR_TESSERACT_PATTERN_MIN_SCORE`
- `GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_ENABLE`
- `GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MIN`
- `GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MAX`
- `GROM_OCR_TESSERACT_EARLY_EXIT_SCORE`
- `GROM_OCR_TESSERACT_REGION_EARLY_SCORE`
- `GROM_OCR_DOCTR_REGION_LIMIT`
- `GROM_OCR_DOCTR_HIT_BONUS`
- `GROM_OCR_DOCTR_REGION_EARLY_SCORE`
- `GROM_OCR_DOCTR_BASE_CONFIDENCE`
- `GROM_OCR_DOCTR_DYNAMIC_VARIANTS`
- `GROM_OCR_DOCTR_MAX_VARIANTS`
- `GROM_OCR_DOCTR_VARIANT_CONSISTENCY_BONUS`
- `GROM_OCR_DOCTR_MIN_ACCEPT_SCORE`
- `GROM_OCR_DOCTR_MIN_ACCEPT_CONF`
- `GROM_OCR_DOCTR_PATTERN_MIN_SCORE`
- `GROM_OCR_DOCTR_MIN_VARIANT_HITS`
- `GROM_OCR_ENABLE_YOLO_DETECTOR`
- `GROM_OCR_YOLO_MODEL_PATH`
- `GROM_OCR_YOLO_CONFIDENCE`
- `GROM_OCR_YOLO_IOU`
- `GROM_OCR_YOLO_MAX_DETECTIONS`
- `GROM_OCR_YOLO_PLATE_CLASS`
- `GROM_OCR_YOLO_MIN_ASPECT`
- `GROM_OCR_YOLO_MAX_ASPECT`
- `GROM_OCR_ENABLE_PDF_INPUT`
- `GROM_OCR_PDF_MAX_PAGES`
- `GROM_OCR_PDF_RENDER_SCALE`
- `GROM_OCR_PDF_PAGE_CANDIDATE_LIMIT`
- `GROM_OCR_PDF_PAGE_EARLY_SCORE`
- `GROM_OCR_PDF_MAX_REGION_CANDIDATES`
- `GROM_OCR_PDF_PROBE_MAX_SIDE`
- `GROM_OCR_PDF_PROBE_REGION_LIMIT`
- `GROM_OCR_PDF_REGION_MAX_SIDE`
- `GROM_OCR_PDF_QUICK_ENGINE_MAX_SIDE`
- `GROM_OCR_VISUAL_PROFILE_ENABLE`
- `GROM_OCR_VISUAL_PROFILE_MAX_SIDE`
- `GROM_OCR_VISUAL_PROFILE_MIN_CONFIDENCE`
- `GROM_OCR_VISUAL_PROFILE_TOP_HYPOTHESES`
- `GROM_OCR_VISUAL_MODEL_ABSTAIN_ENABLE`
- `GROM_OCR_VISUAL_MODEL_MIN_CONFIDENCE`
- `GROM_OCR_VISUAL_MODEL_MIN_MARGIN`
- `GROM_OCR_VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE`
- `GROM_OCR_VISUAL_BRAND_MIN_CONFIDENCE`
- `GROM_OCR_VISUAL_FIPE_ENABLE`
- `GROM_OCR_VISUAL_FIPE_BASE_URL`
- `GROM_OCR_VISUAL_FIPE_TOKEN`
- `GROM_OCR_VISUAL_FIPE_TIMEOUT`
- `OPENAI_API_KEY` (opcional, para servico externo de visao no script avancado)
- `GROM_OCR_VISION_MODEL` (opcional; padrao `gpt-4.1-mini`)
- `GROM_OCR_VISION_URL` (opcional; padrao `https://api.openai.com/v1/responses`)
- `SERPAPI_KEY` (opcional; API de busca)
- `BRAVE_SEARCH_API_KEY` (opcional; API de busca)
- `GOOGLE_API_KEY` (opcional; API de busca custom search)
- `GOOGLE_CSE_ID` (opcional; ID do mecanismo custom search)

Se o seu MySQL local estiver com usuario `root` sem senha, `GROM_OCR_DB_PASS` pode ficar ausente.

## Subida local

1. Crie a tabela com [`config/migrations.sql`](C:\Grom_OCR\config\migrations.sql).
2. Instale as dependencias Python com `pip install -r python/requirements.txt`.
3. Se quiser habilitar a engine opcional, rode `pip install -r python/requirements.optional.txt`.
4. Inicie a API OCR com caminho absoluto:
   `C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\start_ocr_api.py`
5. Suba o PHP apontando para [`public/index.php`](C:\Grom_OCR\public\index.php).
   Exemplo: `php -S 127.0.0.1:8080 -t public`.
6. Abra o sistema no navegador e valide login, upload e historico.
7. Opcional (subida automatica via PowerShell): execute `powershell -ExecutionPolicy Bypass -File C:\Grom_OCR\tools\start_grom_ocr.ps1`
8. Opcional (sem depender de politica de script): execute `C:\Grom_OCR\tools\start_grom_ocr.cmd`
9. Para autostart no login do Windows, execute `powershell -ExecutionPolicy Bypass -File C:\Grom_OCR\tools\install_grom_ocr_autostart.ps1`
10. Para remover o autostart, execute `powershell -ExecutionPolicy Bypass -File C:\Grom_OCR\tools\uninstall_grom_ocr_autostart.ps1`
11. Na primeira inicializacao, aguarde o carregamento dos motores OCR (pode levar ate ~90s) e valide em `http://127.0.0.1:8000/health` antes do primeiro upload.

`tools/start_ocr_api.py` resolve o Tesseract por prioridade: variaveis de ambiente (externo) -> bootstrap por artefato -> pacote local em `tools/tesseract-portable` (se existir) -> instalacao de sistema, mantendo compatibilidade e permitindo externalizacao sem regressao.

O bootstrap e executado por `tools/bootstrap_tesseract_portable.py` e aceita configuracao por variaveis de ambiente ou por arquivo local `config/tesseract_artifact.json` (veja exemplo em `config/tesseract_artifact.example.json`).
Ao subir por `start_ocr_api.py` ou `start_grom_ocr.*`, o modo profissional entra com um perfil mais rapido por padrao: `easyocr` e `rapidocr` ficam habilitados, `GROM_OCR_FORCE_ENSEMBLE=0`, e o Tesseract roda como OCR de linha unica para placa (ANPR/LPR) para reduzir latencia sem perder o fallback inteligente. Os motores `PaddleOCR`, `TrOCR` e `docTR` continuam em opt-in por padrao para evitar boot pesado sem ganho comprovado no acervo atual.
Por padrao, o endpoint FastAPI `/process` delega para o pipeline forense consolidado (`python/ocr_agent.py`) via `GROM_OCR_USE_LEGACY_PIPELINE=1`, mantendo compatibilidade de rota e reduzindo risco de regressao de acuracia.
O arranque agora e idempotente: se a API ou o PHP ja estiverem rodando, o script apenas confirma o estado e nao cria instancias duplicadas. O autostart de login usa a chave `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`.
Perfil padrao de calibracao EasyOCR:

- `GROM_OCR_EASYOCR_ALLOWLIST=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789`
- `GROM_OCR_EASYOCR_DECODER=greedy`
- `GROM_OCR_EASYOCR_BEAM_WIDTH=8`
- `GROM_OCR_EASYOCR_HIT_BONUS=2.5`
- `GROM_OCR_EASYOCR_REGION_EARLY_SCORE=106`

Modo de comparacao profissional (todos os motores por upload):

- `GROM_OCR_FORCE_ENSEMBLE=1`
- `GROM_OCR_ACCURACY_FIRST=1` (varre mais recortes e desativa atalhos de decisao cedo, para auditoria pericial mais exaustiva)
- `GROM_OCR_ENSEMBLE_TOP_PER_ENGINE=4`
- `GROM_OCR_ENSEMBLE_WEIGHTS=easyocr=1.0,rapidocr=0.96,paddleocr=0.98,tesseract=0.92,trocr=0.8,doctr=0.8,plate_recognizer=1.2`

Perfil Plate Recognizer (quando `PLATE_RECOGNIZER_TOKEN` estiver configurado):

- `PLATE_RECOGNIZER_TIMEOUT=15`
- `GROM_OCR_PLATE_RECOGNIZER_DYNAMIC_VARIANTS=1`
- `GROM_OCR_PLATE_RECOGNIZER_MAX_VARIANTS=3`
- `GROM_OCR_PLATE_RECOGNIZER_TOP_RESULTS=2`
- `GROM_OCR_PLATE_RECOGNIZER_HIT_BONUS=1.8`
- `GROM_OCR_PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS=2.4`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_SCORE=54`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_CONF=58`
- `GROM_OCR_PLATE_RECOGNIZER_PATTERN_MIN_SCORE=66`
- `GROM_OCR_PLATE_RECOGNIZER_MIN_VARIANT_HITS=2`

Perfil padrao do 3o motor (RapidOCR):

- `GROM_OCR_ENABLE_RAPIDOCR=1`
- `GROM_OCR_RAPIDOCR_HIT_BONUS=2.0`
- `GROM_OCR_RAPIDOCR_REGION_EARLY_SCORE=105`

Perfil padrao do 4o motor (PaddleOCR, desligado por padrao):

- `GROM_OCR_ENABLE_PADDLEOCR=0`
- `GROM_OCR_PADDLEOCR_LANG=en`
- `GROM_OCR_PADDLEOCR_USE_GPU=0`
- `GROM_OCR_PADDLEOCR_USE_ANGLE_CLS=1`
- `GROM_OCR_PADDLEOCR_DYNAMIC_VARIANTS=1`
- `GROM_OCR_PADDLEOCR_MAX_VARIANTS=5`
- `GROM_OCR_PADDLEOCR_REGION_LIMIT=3`
- `GROM_OCR_PADDLEOCR_REGION_EARLY_SCORE=106`
- `GROM_OCR_PADDLEOCR_HIT_BONUS=2.3`
- `GROM_OCR_PADDLEOCR_VARIANT_CONSISTENCY_BONUS=3.0`
- `GROM_OCR_PADDLEOCR_MIN_ACCEPT_SCORE=47`
- `GROM_OCR_PADDLEOCR_MIN_ACCEPT_CONF=27`
- `GROM_OCR_PADDLEOCR_PATTERN_MIN_SCORE=60`
- `GROM_OCR_PADDLEOCR_MIN_VARIANT_HITS=2`

Perfil padrao do 5o motor (TrOCR, desligado por padrao):

- `GROM_OCR_ENABLE_TROCR=0`
- `GROM_OCR_TROCR_MODEL_ID=microsoft/trocr-small-printed`
- `GROM_OCR_TROCR_MAX_NEW_TOKENS=24`
- `GROM_OCR_TROCR_REGION_LIMIT=2`
- `GROM_OCR_TROCR_HIT_BONUS=1.5`
- `GROM_OCR_TROCR_REGION_EARLY_SCORE=103`
- `GROM_OCR_TROCR_BASE_CONFIDENCE=54`

Perfil padrao do 6o motor (docTR, desligado por padrao):

- `GROM_OCR_ENABLE_DOCTR=0`
- `GROM_OCR_DOCTR_REGION_LIMIT=2`
- `GROM_OCR_DOCTR_HIT_BONUS=1.9`
- `GROM_OCR_DOCTR_REGION_EARLY_SCORE=104`
- `GROM_OCR_DOCTR_BASE_CONFIDENCE=52`
- `GROM_OCR_DOCTR_DYNAMIC_VARIANTS=1`
- `GROM_OCR_DOCTR_MAX_VARIANTS=4`
- `GROM_OCR_DOCTR_VARIANT_CONSISTENCY_BONUS=2.6`
- `GROM_OCR_DOCTR_MIN_ACCEPT_SCORE=42`
- `GROM_OCR_DOCTR_MIN_ACCEPT_CONF=23`
- `GROM_OCR_DOCTR_PATTERN_MIN_SCORE=56`
- `GROM_OCR_DOCTR_MIN_VARIANT_HITS=2`

Os motores `PaddleOCR`, `TrOCR` e `docTR` ficam desligados por padrao no fluxo principal porque o benchmark real recente nao trouxe ganho consistente sobre `RapidOCR` no acervo testado. Se quiser reavaliar, habilite explicitamente por ambiente e rode o benchmark direto antes de promover a mudanca.

Detector opcional de placa via Ultralytics YOLO:

- `GROM_OCR_ENABLE_YOLO_DETECTOR=1`
- `GROM_OCR_YOLO_MODEL_PATH=C:\caminho\para\modelo_placa.pt`
- `GROM_OCR_YOLO_CONFIDENCE=0.35`
- `GROM_OCR_YOLO_IOU=0.45`
- `GROM_OCR_YOLO_MAX_DETECTIONS=3`
- `GROM_OCR_YOLO_PLATE_CLASS=` (opcional, id ou nome da classe)
- `GROM_OCR_YOLO_MIN_ASPECT=1.6`
- `GROM_OCR_YOLO_MAX_ASPECT=10`

Se o caminho nao for informado, o bootstrap usa o modelo embarcado em `models/yolov8n_plate.pt` quando ele estiver presente no repositorio.

Entrada PDF (imagem dentro de PDF):

- `GROM_OCR_ENABLE_PDF_INPUT=1`
- `GROM_OCR_PDF_MAX_PAGES=3`
- `GROM_OCR_PDF_RENDER_SCALE=2.4`
- `GROM_OCR_PDF_PAGE_CANDIDATE_LIMIT=2`
- `GROM_OCR_PDF_PAGE_EARLY_SCORE=118`
- `GROM_OCR_PDF_MAX_REGION_CANDIDATES=2`
- `GROM_OCR_PDF_PROBE_MAX_SIDE=1200`
- `GROM_OCR_PDF_PROBE_REGION_LIMIT=3`
- `GROM_OCR_PDF_REGION_MAX_SIDE=1360`
- `GROM_OCR_PDF_QUICK_ENGINE_MAX_SIDE=980`
- `GROM_OCR_SCENE_PREPROCESS_CALIBRATION_PATH=C:\Grom_OCR\data\scene_preprocess_calibration.json`

Seguranca da entrada / upload:

- `GROM_OCR_ALLOWED_INPUT_EXTENSIONS=jpg,jpeg,png,webp,bmp,tif,tiff,pdf`
- `GROM_OCR_MAX_UPLOAD_MB=80`
- `GROM_OCR_MAX_UPLOAD_BYTES=` (opcional, sobrescreve o limite em bytes)
- a API Python e o front PHP validam extensao, assinatura do arquivo e tamanho antes de chamar o OCR
- quando o arquivo passa, o relatório passa a exibir `input_meta.input_security` e `pericial.cross_checks.capture_integrity`

Calibracao fina da integridade da captura:

- `GROM_OCR_CAPTURE_INTEGRITY_REVIEW_THRESHOLD=68`
- `GROM_OCR_CAPTURE_INTEGRITY_CRITICAL_THRESHOLD=52`
- `GROM_OCR_CAPTURE_INTEGRITY_INPUT_PENALTY=12`
- `GROM_OCR_CAPTURE_INTEGRITY_SIGNATURE_PENALTY=30`
- `GROM_OCR_CAPTURE_INTEGRITY_FALLBACK_PENALTY=18`
- `GROM_OCR_CAPTURE_INTEGRITY_FULL_IMAGE_PENALTY=18`
- `GROM_OCR_CAPTURE_INTEGRITY_SEM_CANDIDATE_PENALTY=32`
- `GROM_OCR_CAPTURE_INTEGRITY_LOW_CANDIDATE_PENALTY=12`
- `GROM_OCR_CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD=55`
- `GROM_OCR_CAPTURE_INTEGRITY_LOW_QUALITY_MAX_PENALTY=28`
- `GROM_OCR_CAPTURE_INTEGRITY_WARNING_PENALTY=5`
- `GROM_OCR_CAPTURE_INTEGRITY_WARNING_LIMIT=3`
- `GROM_OCR_CAPTURE_INTEGRITY_FALLBACK_ALWAYS_REVIEW=1`
- `GROM_OCR_PLATE_DETECTION_FULL_IMAGE_SELECTION_MARGIN=8`
- a nota e a faixa aparecem na tela, no PDF e no bloco `capture_integrity`

Calibracao do detector / recorte da placa:

- `GROM_OCR_PLATE_DETECTION_CALIBRATION_PATH=C:\Grom_OCR\data\plate_detector_calibration.json`
- `GROM_OCR_OCR_RERANKING_CALIBRATION_PATH=C:\Grom_OCR\data\ocr_reranking_calibration.json`
- `GROM_OCR_PLATE_DETECTION_ASPECT_TARGET=4.2`
- `GROM_OCR_PLATE_DETECTION_ASPECT_MIN=1.7`
- `GROM_OCR_PLATE_DETECTION_ASPECT_MAX=9.2`
- `GROM_OCR_PLATE_DETECTION_AREA_MIN_RATIO=0.0018`
- `GROM_OCR_PLATE_DETECTION_AREA_MAX_RATIO=0.42`
- `GROM_OCR_PLATE_DETECTION_MIN_IMAGE_WIDTH=64`
- `GROM_OCR_PLATE_DETECTION_MIN_IMAGE_HEIGHT=32`
- `GROM_OCR_PLATE_DETECTION_MIN_BOX_WIDTH=34`
- `GROM_OCR_PLATE_DETECTION_MIN_BOX_HEIGHT=14`
- `GROM_OCR_PLATE_CROP_PAD_RATIO=0.08`
- `GROM_OCR_PLATE_CROP_PAD_RATIO_SMALL=0.05`
- `GROM_OCR_PLATE_CROP_PAD_RATIO_LARGE=-0.02`
- `GROM_OCR_PLATE_CROP_MIN_WIDTH=58`
- `GROM_OCR_PLATE_CROP_MIN_HEIGHT=18`
- `GROM_OCR_PLATE_QUALITY_ASPECT_TARGET=4.2`
- `GROM_OCR_PLATE_QUALITY_ASPECT_TOLERANCE=1.8`
- `GROM_OCR_PLATE_QUALITY_ASPECT_MIN=1.5`
- `GROM_OCR_PLATE_QUALITY_ASPECT_MAX=8.5`
- o recorte candidato agora passa por normalizacao canonica com `deskew` e `padding` antes do OCR
- o painel e o PDF passam a mostrar `aspecto`, `faixa` e `qualidade` do ROI selecionado para apoiar a calibracao fina

Benchmark do detector / recorte de placa:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\benchmark_plate_detector.py --manifest C:\Grom_OCR\data\plate_detector_benchmark_manifest.json --output C:\Grom_OCR\data\plate_detector_benchmark_results.json --export-calibration C:\Grom_OCR\data\plate_detector_calibration.generated.json`

Se o benchmark encontrar uma melhor base de ajuste, a forma recomendada de aplicar e apontar `GROM_OCR_PLATE_DETECTION_CALIBRATION_PATH` para o JSON gerado.

Subconjunto duro separado:

`C:\Grom_OCR\data\plate_detector_benchmark_manifest_hard.json`

Benchmark do re-ranking OCR:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\benchmark_ocr_reranking.py --manifest C:\Grom_OCR\data\ocr_reranking_benchmark_manifest.json --output C:\Grom_OCR\data\ocr_reranking_benchmark_results.json --export-calibration C:\Grom_OCR\data\ocr_reranking_calibration.generated.json`

O benchmark usa amostras reais rotuladas e recalibra os pesos do ensemble, a penalidade por rank e os limiares de consenso. A calibracao ativa atual ficou em `2026-04-04-r3`, com reranking mais slot-aware e um peso maior para `RapidOCR`. Se a calibracao gerada ficar melhor que a ativa, aponte `GROM_OCR_OCR_RERANKING_CALIBRATION_PATH` para o JSON exportado.

Modo direto, recomendado para calibracao em crops reais sem passar pelo `/process`:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\benchmark_ocr_reranking.py --manifest C:\Grom_OCR\data\ocr_reranking_benchmark_manifest_crops_real.json --direct --engines tesseract,rapidocr,easyocr --output C:\Grom_OCR\data\ocr_reranking_benchmark_results_direct_real.json --export-calibration C:\Grom_OCR\data\ocr_reranking_calibration.generated.json --apply-calibration`

Opcionalmente, valide no subconjunto duro de crops reais:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\benchmark_ocr_reranking.py --manifest C:\Grom_OCR\data\ocr_reranking_benchmark_manifest_crops_real_hard.json --direct --engines tesseract,rapidocr,easyocr --output C:\Grom_OCR\data\ocr_reranking_benchmark_results_direct_real_hard.json --export-calibration C:\Grom_OCR\data\ocr_reranking_calibration.generated.json`

Subconjunto duro separado:

`C:\Grom_OCR\data\ocr_reranking_benchmark_manifest_hard.json`

Microcalibracao isolada por amostra:

- `GROM_OCR_MICROCALIBRATION_PATH=C:\Grom_OCR\data\ocr_microcalibration.json`
- use para ratificar manualmente casos isolados por hash ou nome de arquivo
- a microcalibracao preserva o OCR bruto para auditoria e aplica apenas o texto final ratificado no laudo

Perfil visual do veiculo (hipoteses por imagem):

- `GROM_OCR_VISUAL_PROFILE_ENABLE=1`
- `GROM_OCR_VISUAL_PROFILE_MAX_SIDE=1280`
- `GROM_OCR_VISUAL_PROFILE_MIN_CONFIDENCE=42`
- `GROM_OCR_VISUAL_PROFILE_TOP_HYPOTHESES=3`
- `GROM_OCR_VISUAL_MODEL_ABSTAIN_ENABLE=1`
- `GROM_OCR_VISUAL_MODEL_MIN_CONFIDENCE=78`
- `GROM_OCR_VISUAL_MODEL_MIN_MARGIN=8`
- `GROM_OCR_VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE=1`
- `GROM_OCR_VISUAL_BRAND_MIN_CONFIDENCE=58`
- `GROM_OCR_VISUAL_FIPE_ENABLE=1`
- `GROM_OCR_VISUAL_FIPE_BASE_URL=https://fipe.parallelum.com.br/api/v2`
- `GROM_OCR_VISUAL_FIPE_TOKEN=` (opcional)
- `GROM_OCR_VISUAL_FIPE_TIMEOUT=3`

Modo forense profissional:

- `GROM_OCR_CHAIN_SIGNING_KEY=<segredo forte para HMAC da cadeia de custodia>`
- Prioridade recomendada de fontes:
  `Senatran/SERPRO -> Prodesp (Detran-SP) -> fontes externas autorizadas -> complemento FIPE`
- Configuracao Senatran/SERPRO:
  `GROM_OCR_SENATRAN_ENABLE=1`
  `GROM_OCR_SENATRAN_URL=https://seu-endpoint-oficial/{plate}`
  `GROM_OCR_SENATRAN_METHOD=GET`
  `GROM_OCR_SENATRAN_PLATE_PARAM=placa`
  `GROM_OCR_SENATRAN_TOKEN_HEADER=Authorization`
  `GROM_OCR_SENATRAN_TOKEN_PREFIX=Bearer`
  `GROM_OCR_SENATRAN_TOKEN=<token>`
  `GROM_OCR_SENATRAN_RESPONSE_PATH=` (opcional; use notacao com ponto se o JSON vier aninhado)
- Configuracao Prodesp (Detran-SP):
  `GROM_OCR_PRODESP_ENABLE=1`
  `GROM_OCR_PRODESP_URL=https://seu-endpoint-prodesp/{plate}`
  `GROM_OCR_PRODESP_METHOD=GET`
  `GROM_OCR_PRODESP_PLATE_PARAM=placa`
  `GROM_OCR_PRODESP_TOKEN_HEADER=Authorization`
  `GROM_OCR_PRODESP_TOKEN_PREFIX=Bearer`
  `GROM_OCR_PRODESP_TOKEN=<token>`
  `GROM_OCR_PRODESP_RESPONSE_PATH=` (opcional)
- `GROM_OCR_VEHICLE_LOOKUP_URL=https://seu-provedor/api/consulta/{plate}`
- `GROM_OCR_VEHICLE_LOOKUP_URLS=https://fonte1/api/{plate};https://fonte2/consulta?placa={plate}` (fallback em cadeia)
- `GROM_OCR_VEHICLE_LOOKUP_PROVIDER=usezapay` ou `GROM_OCR_USEZAPAY_ENABLE=1`
- `GROM_OCR_USEZAPAY_BASE_URL=https://api.b2b.usezapay.com.br/v2/vehicle/debts`
- `GROM_OCR_USEZAPAY_USERNAME=<usuario_b2b>`
- `GROM_OCR_USEZAPAY_PASSWORD=<senha_b2b>`
- `GROM_OCR_USEZAPAY_BASIC_AUTH_B64=<base64(usuario:senha)>` (opcional)
- `GROM_OCR_USEZAPAY_WEBHOOK_SECRET=<secret_key_usada_no_cadastro_do_webhook>`
- `GROM_OCR_USEZAPAY_WEBHOOK_AUTH_TOKEN=<token_complementar_do_webhook>` (opcional)
- `GROM_OCR_USEZAPAY_WEBHOOK_AUTH_HEADER=Authorization` ou `X-Api-Key`
- `GROM_OCR_ADMIN_PASS_HASH=<hash gerado com password_hash no PHP>`
- Para dados sensiveis veiculares, priorize apenas integracoes oficiais ou autorizadas. O sistema classifica a procedencia da consulta e mascara campos sensiveis por padrao.
- O motor de lookup trata `Senatran/SERPRO` como fonte oficial principal e `Prodesp` como fonte oficial estadual prioritaria quando configuradas.
- Auth padrao (Bearer):
  `GROM_OCR_VEHICLE_LOOKUP_TOKEN=<token>`
- Auth custom (ex.: x-api-key):
  `GROM_OCR_VEHICLE_LOOKUP_TOKEN_HEADER=x-api-key`
  `GROM_OCR_VEHICLE_LOOKUP_TOKEN_PREFIX=`
  `GROM_OCR_VEHICLE_LOOKUP_TOKEN=<chave>`
- Webhook UseZapay:
  `public/webhooks/usezapay.php`
  - cadastre a URL no painel/API da Zapay
  - a API envia `x-hmac-signature` e suporta token adicional via `authorization` ou `x-api-key`
- Consulta de status local UseZapay:
  `public/api/usezapay_status.php`
  - permite consultar por `plate` ou `request_id`
  - retorna o ultimo evento consolidado e o resumo do cache local
- Complemento em base aberta (FIPE API):
  `GROM_OCR_OPEN_DATA_ENABLE=1`
  `GROM_OCR_OPEN_DATA_FIPE_BASE_URL=https://fipe.parallelum.com.br/api/v2`
  `GROM_OCR_OPEN_DATA_FIPE_TOKEN=` (opcional; aumenta limite diario no provedor)
  `GROM_OCR_OPEN_DATA_TIMEOUT=5`
- Validacao oficial pos-placa deve ser feita via provedor oficial/autorizado e nao por scraping de fontes aleatorias. Fontes publicas para referencia operacional:
  `https://www.gov.br/pt-br/servicos/consultar-online-os-dados-de-placa-veicular`
  `https://www.gov.br/pt-br/servicos/consultar-dados-de-veiculo-na-base-renavam`
  `https://www.gov.br/pt-br/servicos/consultar-informacoes-do-crv-atual-do-veiculo`
  `https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/diretoria-de-gestao-e-integracao-de-informacoes-1/produtos/sinesp_cidadao`
- TLS para consultas HTTP externas:
  `GROM_OCR_HTTP_CA_BUNDLE=C:\caminho\cacert.pem` (recomendado)
  `GROM_OCR_HTTP_INSECURE_SKIP_VERIFY=0` (use `1` apenas em ambiente controlado)
- Comparativo com outros sistemas de identificacao:
  `GROM_OCR_EXTERNAL_COMPARE_ENABLE=1`
  `GROM_OCR_EXTERNAL_COMPARE_TIMEOUT=8`
  `GROM_OCR_EXTERNAL_COMPARE_MAX_CANDIDATES=3`
  `OPENALPR_SECRET_KEY=<chave Rekor/OpenALPR>`
  `GROM_OCR_OPENALPR_ENDPOINT=https://api.openalpr.com/v3/recognize`
  `GROM_OCR_OPENALPR_COUNTRY=br`
  `GROM_OCR_OPENALPR_RECOGNIZE_VEHICLE=1`
  `GROM_OCR_OPENALPR_TOPN=5`
  `GROM_OCR_NOMEROFF_COMPARE_ENDPOINT=http://127.0.0.1:9001/recognize` (opcional, endpoint proprio)
  `GROM_OCR_NOMEROFF_COMPARE_TOKEN=` (opcional)
  `GROM_OCR_NOMEROFF_COMPARE_TOKEN_HEADER=Authorization` (opcional)

Modo anti-travamento (padrao recomendado):

- `GROM_OCR_ALLOW_HEAVY_COLDSTART=0`
- `GROM_OCR_TROCR_LOCAL_ONLY=1`
- `GROM_OCR_TESSERACT_MAX_VARIANTS=14`
- `GROM_OCR_TESSERACT_PSM_MODES=7`
- `GROM_OCR_TESSERACT_HIT_BONUS=2.1`
- `GROM_OCR_TESSERACT_MIN_ACCEPT_SCORE=42`
- `GROM_OCR_TESSERACT_MIN_ACCEPT_CONF=28`
- `GROM_OCR_TESSERACT_PATTERN_MIN_SCORE=58`

## Endpoints uteis da secao de investigacao visual

- `GET /health`: checagem rapida da API Python
- `POST /warmup_heavy`: aquece TrOCR/docTR sem travar a primeira pesquisa
- `POST /process`: pipeline completa de OCR (delegada ao pipeline pericial legado por padrão)
- `POST /process-ensemble`: pipeline com detecção em ensemble + orquestração forense
- `POST /full-pipeline`: pipeline completo orquestrado ponta a ponta
- `POST /enrich_report`: atualiza PDF com dados externos de veiculo
- `POST /process_simple`: pipeline simplificada
- `GET /pdf/<arquivo>`: download do relatorio gerado

## Orquestração Forense e Auditoria Institucional

A partir da v1.0, o GROM OCR implementa **orquestração centralizada** com hierarquia de tarefas, delegação robusta e cadeia de custódia digital para garantir conformidade institucional:

### Arquitetura de Orquestração

```text
Entrada (imagem de placa)
    ↓
[ForensicOrchestrator]
    ├── Cria contexto com analysis_id único (UUID)
    ├── Define hierarquia de tarefas com dependências (topológico)
    ├── Tenta delegação ao pipeline pericial legado (mais confiável)
    ├── Em falha: executa fallback local com rastreamento
    └── Consolida com cadeia de custódia digital
    ↓
Saída (análise + auditoria + compliance)
```

**Benefícios:**

- ✅ **Máxima Confiabilidade**: Pipeline legado é mais confiável e testado
- ✅ **Cadeia de Custódia**: Cada operação é auditada com timestamp UTC
- ✅ **Rastreabilidade Total**: Saber exatamente o que foi executado e por quê
- ✅ **Conformidade Institucional**: Preparado para adopção por órgãos públicos
- ✅ **Graceful Degradation**: Se legado falhar, sistema continua com fallback

### Revalidação Forense com Gates de Qualidade

Executar revalidação completa antes de promover para produção:

```bash
# Modo completo (gates + integração + relatório)
python tools/orchestrator_executor.py --mode full

# Apenas gates de qualidade
python tools/orchestrator_executor.py --mode gates-only

# Apenas bateria de calibração
python tools/orchestrator_executor.py --mode calibration

# Modo simulação (dry-run)
python tools/orchestrator_executor.py --mode full --dry-run
```

**Resultado:**

- `data/test_results/forensic_revalidation_latest.json` - Métricas estruturadas
- `data/test_results/forensic_revalidation_latest.md` - Sumário para apresentação
- `data/test_results/institutional_assessment_latest.json` - Avaliação institucional
- `logs/orchestrator_executor.log` - Log completo de execução

### Policy de Gates de Qualidade

Editar `data/phase1_quality_gate_policy.json` para ajustar conformidade por instituição:

```json
{
  "phase": "1",
  "gates": {
    "ocr_text_confidence_min": {
      "value": 0.75,
      "description": "Confiança mínima de OCR (0.0-1.0)",
      "required": true
    },
    "consensus_ratio_min": {
      "value": 0.80,
      "description": "Proporção mínima de consenso entre motores",
      "required": true
    },
    "pattern_valid": {
      "value": true,
      "description": "Placa deve seguir padrão legal válido",
      "required": true
    }
  }
}
```

### Documentação de Padrões

Para contribuidores e outras instituições:

- **[ARCHITECTURE_PERICIAL.md](ARCHITECTURE_PERICIAL.md)** - Arquitetura completa com exemplos
- **[CONTRIBUTING_PATTERNS.md](CONTRIBUTING_PATTERNS.md)** - Padrões de desenvolvimento e orquestração
- **[fastapi_backend/orchestrator.py](fastapi_backend/orchestrator.py)** - Código-fonte do orquestrador

## Comando dedicado de identificacao visual

## Script avancado de identificacao visual de veiculos

Para analise dedicada de fabricante/modelo com comparacao entre modelos parecidos e validacao em fontes abertas especializadas (automoveis, motocicletas e caminhoes):

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\vehicle_visual_investigator.py C:\caminho\imagem.jpg`

Opcoes comuns:

- `--search-provider auto|serpapi|brave|google_cse|none`
- `--skip-vision-service` (roda apenas heuristica local)
- `--output-json C:\caminho\saida.json`

Benchmark do pre-processamento de cena:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\benchmark_scene_preprocess.py --manifest C:\Grom_OCR\data\scene_preprocess_benchmark_manifest.json --output C:\Grom_OCR\data\scene_preprocess_benchmark_results.json`

Opcional:

- `--route /process | /process_simple`
- `--api-url http://127.0.0.1:8000` para usar a API em execucao
- `--export-calibration C:\Grom_OCR\data\scene_preprocess_calibration.generated.json`

Os manifests agora sao gerados a partir de `C:\Grom_OCR\data\benchmark_catalog.json`, com um subconjunto duro separado em `C:\Grom_OCR\data\scene_preprocess_benchmark_manifest_hard.json`.

Para regenerar todos os manifests:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\generate_benchmark_manifests.py`

Suite permanente de benchmark:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\run_benchmark_suite.py --mode all`

Suite com gate de regressao (politica oficial):

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\run_benchmark_suite.py --mode hard --policy-file C:\Grom_OCR\data\phase1_quality_gate_policy.json --skip-refresh-manifests`

Bateria canonica com gate:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\run_image_calibration_battery.py --policy-file C:\Grom_OCR\data\phase1_quality_gate_policy.json`

Orquestrador unico de revalidacao (gera JSON + Markdown consolidado):

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\revalidate_forensic_quality.py --policy-file C:\Grom_OCR\data\phase1_quality_gate_policy.json --skip-refresh-manifests`

Opcional para incluir os subconjuntos OCR reais em modo direto:

`C:\Grom_OCR\.venv\Scripts\python.exe C:\Grom_OCR\tools\run_benchmark_suite.py --mode all --include-real`

O runner regenera os manifests a partir do catalogo mestre por padrao, grava cada execucao em `C:\Grom_OCR\data\benchmark_runs\<run_id>\`, preserva os logs por job e atualiza `C:\Grom_OCR\data\benchmark_suite_latest.json` e `C:\Grom_OCR\data\benchmark_suite_latest_index.json` com o resumo consolidado. Se quiser apenas validar os manifests existentes, use `--skip-refresh-manifests`.
Observacao: a suite e longa por desenho, porque mede os mesmos cenarios fixos de forma reproduzivel e auditavel.

Fluxo implementado no script:

- entrada + pre-processamento (brilho, contraste, nitidez) e recorte automatico do veiculo
- inferencia de categoria veicular (`automovel`, `motocicleta`, `caminhao`) com confianca e sinais tecnicos
- analise visual inicial por assinatura de componentes (emblema, grade, farois, lanternas, portas, capo, tampa traseira, carroceria)
- geracao de 3 a 5 candidatos com confianca
- comparacao entre modelos parecidos com descarte justificado
- validacao cruzada por fontes independentes via APIs de busca e consultas abertas por categoria
- fallback de fontes com links prontos para fabricantes, concessionarias, foruns, anuncios e buscadores (Google/Yahoo)
- aviso automatico quando `confianca_final < 80%`

## Observacoes de qualidade

- O pipeline aplica tratamento de imagem para cenarios dificeis (baixa nitidez, iluminacao ruim e angulo irregular), incluindo normalizacao de contraste, denoise, sharpen, padding de placa, deskew e variantes de binarizacao.
- O pipeline agora aplica preprocessamento global inteligente da cena combinando OpenCV e Pillow, com selecao da melhor variante entre original, balanceamento de cor, denoise adaptativo, CLAHE, gamma, unsharp, autocontrast, equalize e filtros adicionais, com metrica de qualidade antes/depois, classificacao de cenario e lista das variantes avaliadas em `input_meta.scene_preprocess`.
- A placa agora passa por uma etapa dedicada de geometria/crop canonico em `input_meta.plate_detection`, com priorizacao de recorte retificado, score visual do ROI, fonte do recorte e modo OCR em linha unica antes do ensemble.
- O endpoint raiz `/` responde status JSON para evitar falso erro de "404" ao abrir a API no navegador.
- Arquivos PDF sao suportados: o sistema renderiza paginas, avalia multiplas regioes por pagina e seleciona tecnicamente a melhor pagina/regiao para OCR, alem de escolher separadamente a melhor cena visual (foto) para perfil de veiculo.
- O fluxo de PDF aplica fallback visual inteligente (`pdf_probe_using_visual_focus_fallback`) quando o probe textual da pagina estiver fraco ou inconsistente, reduzindo a chance de OCR em blocos de texto do proprio relatorio.
- Regioes PDF agora passam por limitacao de tamanho antes do OCR, com probe rapido dedicado (RapidOCR/EasyOCR/Tesseract) para melhorar tempo de resposta sem forcar leitura inventada.
- O candidato `pdf_probe` nao encerra resultado final sozinho: para evitar falso positivo de texto do proprio PDF, ele exige corroboracao por outro motor OCR para ser aceito como leitura final.
- A resposta da API agora inclui `ocr_engine_status` e `ocr_engine_summary` (configurados, disponiveis, prontos, executados, com texto, sem texto, pulados, falhos, desabilitados e indisponiveis) para deixar transparente por que nem todos os motores entram em toda execucao.
- A resposta da API inclui `external_systems_comparison`, com comparativo entre sistemas externos (quando configurados), taxa de concordancia com OCR interno e compatibilidade com a hipotese visual.
- O PDF e a tela web agora exibem o comparativo externo por sistema (status, placa retornada, confianca e compatibilidade), alem do catalogo de referencias abertas.
- Cada analise gera `analysis_id`, hashes SHA-256 (fonte e recorte da placa) e assinatura digital para cadeia de custodia.
- A escolha final prioriza consenso entre motores (votacao ponderada) antes do fallback por score individual.
- O ensemble aplica peso dinamico em todos os motores OCR para reduzir impacto de candidatos ruidosos, mantendo o Tesseract recalibrado e rebaixando automaticamente motores com baixa confianca, conflito elevado ou abstencao.
- O TrOCR aplica leitura multi-variantes com bonus de consistencia; quando a evidencia for insuficiente, entra em abstencao inteligente (`trocr_low_reliability_abstained`) e retorna vazio em vez de forcar texto.
- O EasyOCR aplica leitura multi-variantes com bonus de consistencia entre variantes; quando a confianca nao atinge criterios minimos, entra em abstenção inteligente (`easyocr_low_reliability_abstained`) e devolve vazio para evitar texto inventado.
- O RapidOCR tambem aplica leitura multi-variantes com bonus de consistencia; quando a evidência e fraca, entra em abstenção inteligente (`rapidocr_low_reliability_abstained`) e retorna vazio em vez de forcar texto.
- O docTR agora aplica leitura multi-variantes com bonus de consistencia; quando a confianca nao passa nos criterios minimos, entra em abstencao inteligente (`doctr_low_reliability_abstained`) e retorna vazio em vez de inventar texto.
- O Plate Recognizer agora aplica leitura multi-variantes da cena com bonus de consistencia; quando nao houver confianca suficiente, entra em abstencao inteligente (`plate_recognizer_low_reliability_abstained`) e retorna vazio em vez de forcar placa incorreta.
- `TrOCR` e `docTR` entram de forma inteligente quando ha divergencia entre motores centrais, evitando travamento desnecessario.
- Com `GROM_OCR_ALLOW_HEAVY_COLDSTART=0` (padrao), o sistema evita cold start pesado no primeiro upload; se quiser preaquecer os motores, use `POST /warmup_heavy`.
- O sistema calcula consenso entre motores e classifica nivel probatorio (`ALTA`, `MEDIA`, `BAIXA`) com indicacao de revisao manual.
- A validacao pericial automatizada aplica checagem legal brasileira (padrao antigo e Mercosul), reranking por slots criticos da placa, score de qualidade da imagem, ambiguidade de caracteres e cruzamentos com historico local/fonte externa.
- O relatorio PDF inclui a secao pericial com status, qualidade, conformidade legal e cruzamentos (`historico local` e `fonte externa`) quando disponiveis.
- O relatorio adota redacao tecnico-pericial preliminar e reforca explicitamente a obrigatoriedade de revisao humana e correlacao com demais provas.
- A tela `upload.php` opera em dois passos: a pre-analise mostra a foto, os recortes tratados e os candidatos provaveis; o PDF final so e gerado apos a conferencia humana e a confirmacao do operador.
- O PDF final inclui a secao `Conferencia Humana` com decisao, operador, candidato confirmado, texto final e observacoes de revisao.
- O relatorio passa a listar de forma explicita os motores de busca e os motores de analise utilizados na execucao, alem das fontes consultadas.
- O enriquecimento veicular externo nao usa dados simulados por padrao: use `GROM_OCR_VEHICLE_LOOKUP_URL`, `GROM_OCR_VEHICLE_LOOKUP_URLS` ou `GROM_OCR_USEZAPAY_ENABLE=1` para consulta por placa em fontes externas estruturadas.
- Quando houver mais de uma fonte configurada, a consulta consolida os retornos, ranqueia a melhor origem por procedencia e expõe `consulta_multifonte_*` com consenso e divergencias.
- A Zapay B2B pode ser usada como conector assíncrono oficial/autorizado: a consulta retorna `request_id`, o webhook cai em `public/webhooks/usezapay.php` e o sistema consolida o retorno por placa.
- Sem provedor por placa, o sistema pode exibir apenas estimativa de fontes abertas/heuristica visual (explicitamente marcada), sem inferir chassi real.
- Quando a consulta externa retorna fabricante/modelo/ano, o sistema complementa automaticamente com FIPE (base aberta) e grava a origem dos dados em `fonte`, `fonte_complementar` e `fontes_utilizadas`.
- A API retorna `visual_profile` com hipoteses tecnicas de cor, assinatura de emblema, fabricante/modelo provavel e faixa de ano; esse bloco tambem entra no PDF e no painel web.
- O perfil visual aplica abstencao inteligente de modelo: quando a evidencia discriminativa e insuficiente, retorna `modelo=Nao conclusivo` e registra o motivo (`qualidade_modelo.reasons`) em vez de forcar um modelo errado.
- O `visual_profile` tambem inclui assinaturas de componentes (emblema, grade, farois, lanternas, portas, tampa traseira, capo e carroceria), checklist pericial de comparacao e links de consulta aberta por componente para revisao manual orientada.
- O catalogo de referencias abertas foi centralizado em `python/utils/visual_reference_catalog.py`, cobrindo press kits oficiais, NetCarShow, Cars.com Research, Edmunds, Automobile Catalog, Inmetro/PBE Veicular e os portais de autopecas informados.
- As consultas abertas do painel, do PDF e do investigador passam a ser geradas por esse catalogo central, reduzindo duplicacao e mantendo a trilha documental consistente.
- O `visual_profile` agora inclui uma `matriz_evidencias` que explica, por candidato, quais sinais visuais e quais fontes abertas sustentam fabricante/modelo/faixa de ano.
- O `visual_profile` passa a incluir `caracteristicas_forenses` com achados potenciais (ex.: possivel amassado de paralama, diferenca de pintura por painel, retrovisor possivelmente danificado, possivel adesivo traseiro), sempre com confianca e natureza nao conclusiva para validacao humana.
- O comparativo aberto inclui `consultas_caracteristicas` para apoiar investigacao manual dos achados forenses em fontes abertas.
- A consulta veicular pos-placa expõe bloco de `validacao_oficial` com procedencia da fonte, classificacao da consulta e mascaramento padrao de campos sensiveis.
- Na disputa `FIAT Uno x FIAT Mobi` em vista nao frontal/baixa confianca, a heuristica aplica priorizacao pericial de `Uno` quando os scores estao proximos, para reduzir falso positivo de `Mobi` em lanterna traseira ambigua.

## O que foi ajustado para uso no Codex

- configuracao centralizada para banco e URL da API Python
- conexao PDO compartilhada e com mensagens de erro claras
- fluxo de upload mais resiliente a falhas de OCR e banco
- historico com tratamento de falha de configuracao
- API Python com pasta de upload portavel, `healthcheck` e melhor parse de confianca OCR
- geracao de PDF mais tolerante a caracteres e caminhos ausentes
- fallback automatico de persistencia em `data/analises_fallback.json` quando o MySQL estiver indisponivel

## Verificacao feita neste ambiente

- estrutura completa do projeto revisada
- arquivos Python compilam (`py_compile`)
- API OCR validada em `http://127.0.0.1:8000/health`
- fluxo web validado em `http://127.0.0.1:8080` (login, upload, OCR e historico)

## Fluxo operacional enquanto aguarda BRCars

Checklist de prontidao pre-BRCars (mantem evolucao sem regressao):

`c:/Grom_OCR/.venv/Scripts/python.exe c:/Grom_OCR/tools/check_pre_brcars_readiness.py`

Atalho no Windows (executa o checklist e abre o relatorio):

`C:\\Grom_OCR\\tools\\check_pre_brcars_readiness.cmd`

Saida gerada:

- `data/datasets/brcars/pre_brcars_readiness_report.json`

Interpretacao rapida do status:

- `blocked`: falta dependencia basica ou teste de integracao falhou
- `ready_waiting_brcars`: sistema pronto, faltando apenas `brcars_summary.json`
- `fully_ready`: BRCars ja disponivel e stack completa validada

Quando o ZIP real autorizado chegar:

`c:/Grom_OCR/.venv/Scripts/python.exe c:/Grom_OCR/tools/finalize_brcars_integration.py --zip-path "CAMINHO_DO_ZIP_REAL"`

Isso executa preparacao do dataset, validacao de sumario, testes de integracao e gera:

- `data/datasets/brcars/brcars_summary.json`
- `data/datasets/brcars/brcars_finalize_report.json`
