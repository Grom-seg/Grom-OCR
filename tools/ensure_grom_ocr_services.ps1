param(
    [int]$PhpPort = 8080,
    [switch]$PythonOnly,
    [switch]$PhpOnly,
    [int]$ApiPort = 8000,
    [int]$HealthTimeoutSec = 90,
    [switch]$Quiet
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonScript = Join-Path $projectRoot 'tools\start_ocr_api.py'
$tesseractCmd = Join-Path $projectRoot 'tools\tesseract-portable\tesseract.exe'
$tessdataDir = Join-Path $projectRoot 'tools\tesseract-portable\tessdata'

function Write-Status {
    param([string]$Message, [switch]$Warning)
    if ($Quiet) { return }
    if ($Warning) {
        Write-Warning $Message
    }
    else {
        Write-Host $Message
    }
}

function Test-PortListening {
    param([int]$Port)
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return [bool]$connections
    }
    catch {
        return $false
    }
}

function Test-ApiHealth {
    param([int]$Port)
    try {
        $health = Invoke-RestMethod ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 2
        return ($health.status -eq 'ok')
    }
    catch {
        return $false
    }
}

function Resolve-PhpExe {
    $phpCandidates = @()
    $phpCmd = Get-Command php -ErrorAction SilentlyContinue
    if ($phpCmd) {
        $phpCandidates += $phpCmd.Source
    }

    $wingetRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path $wingetRoot) {
        $wingetPhp = Get-ChildItem -Path $wingetRoot -Filter 'php.exe' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like '*PHP.PHP.*' } |
        Select-Object -ExpandProperty FullName
        if ($wingetPhp) {
            $phpCandidates += $wingetPhp
        }
    }

    return ($phpCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
}

function Set-ServiceEnv {
    $env:GROM_OCR_TESSERACT_CMD = $tesseractCmd
    $env:TESSDATA_PREFIX = $tessdataDir
    $yoloModelPath = Join-Path $projectRoot 'models\yolov8n_plate.pt'
    if (-not $env:GROM_OCR_YOLO_MODEL_PATH -and (Test-Path $yoloModelPath)) {
        $env:GROM_OCR_YOLO_MODEL_PATH = $yoloModelPath
    }
    $env:GROM_OCR_ENABLE_EASYOCR = '1'
    $env:GROM_OCR_ENABLE_RAPIDOCR = '1'
    $env:GROM_OCR_ENABLE_TROCR = '0'
    $env:GROM_OCR_ENABLE_DOCTR = '0'
    $env:GROM_OCR_ENABLE_PADDLEOCR = '0'
    $env:GROM_OCR_ENABLE_PADDLE = $env:GROM_OCR_ENABLE_PADDLEOCR
    $env:GROM_OCR_USE_LEGACY_PIPELINE = '1'
    $env:GROM_OCR_FORCE_ENSEMBLE = '0'
    $env:GROM_OCR_ALLOW_HEAVY_COLDSTART = '0'
    $env:GROM_OCR_TROCR_LOCAL_ONLY = '1'
    $env:GROM_OCR_TROCR_DYNAMIC_VARIANTS = '1'
    $env:GROM_OCR_TROCR_MAX_VARIANTS = '4'
    $env:GROM_OCR_TROCR_VARIANT_CONSISTENCY_BONUS = '2.8'
    $env:GROM_OCR_TROCR_MIN_ACCEPT_SCORE = '44'
    $env:GROM_OCR_TROCR_MIN_ACCEPT_CONF = '24'
    $env:GROM_OCR_TROCR_PATTERN_MIN_SCORE = '58'
    $env:GROM_OCR_TROCR_MIN_VARIANT_HITS = '2'
    $env:GROM_OCR_DOCTR_DYNAMIC_VARIANTS = '1'
    $env:GROM_OCR_DOCTR_MAX_VARIANTS = '4'
    $env:GROM_OCR_DOCTR_VARIANT_CONSISTENCY_BONUS = '2.6'
    $env:GROM_OCR_DOCTR_MIN_ACCEPT_SCORE = '42'
    $env:GROM_OCR_DOCTR_MIN_ACCEPT_CONF = '23'
    $env:GROM_OCR_DOCTR_PATTERN_MIN_SCORE = '56'
    $env:GROM_OCR_DOCTR_MIN_VARIANT_HITS = '2'
    $env:GROM_OCR_PLATE_RECOGNIZER_DYNAMIC_VARIANTS = '1'
    $env:GROM_OCR_PLATE_RECOGNIZER_MAX_VARIANTS = '3'
    $env:GROM_OCR_PLATE_RECOGNIZER_TOP_RESULTS = '2'
    $env:GROM_OCR_PLATE_RECOGNIZER_HIT_BONUS = '1.8'
    $env:GROM_OCR_PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS = '2.4'
    $env:GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_SCORE = '54'
    $env:GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_CONF = '58'
    $env:GROM_OCR_PLATE_RECOGNIZER_PATTERN_MIN_SCORE = '66'
    $env:GROM_OCR_PLATE_RECOGNIZER_MIN_VARIANT_HITS = '2'
    $env:GROM_OCR_TESSERACT_MAX_VARIANTS = '6'
    $env:GROM_OCR_TESSERACT_PSM_MODES = '7'
    $env:GROM_OCR_TESSERACT_HIT_BONUS = '2.1'
    $env:GROM_OCR_TESSERACT_MIN_ACCEPT_SCORE = '42'
    $env:GROM_OCR_TESSERACT_MIN_ACCEPT_CONF = '28'
    $env:GROM_OCR_TESSERACT_PATTERN_MIN_SCORE = '58'
    $env:GROM_OCR_TESSERACT_EARLY_EXIT_SCORE = '108'
    $env:GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_ENABLE = '1'
    $env:GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MIN = '0.16'
    $env:GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MAX = '1.00'
    $env:GROM_OCR_EASYOCR_DYNAMIC_VARIANTS = '1'
    $env:GROM_OCR_EASYOCR_MAX_VARIANTS = '4'
    $env:GROM_OCR_EASYOCR_VARIANT_CONSISTENCY_BONUS = '3.6'
    $env:GROM_OCR_EASYOCR_MIN_ACCEPT_SCORE = '48'
    $env:GROM_OCR_EASYOCR_MIN_ACCEPT_CONF = '28'
    $env:GROM_OCR_EASYOCR_PATTERN_MIN_SCORE = '62'
    $env:GROM_OCR_EASYOCR_MIN_VARIANT_HITS = '2'
    $env:GROM_OCR_RAPIDOCR_DYNAMIC_VARIANTS = '1'
    $env:GROM_OCR_RAPIDOCR_MAX_VARIANTS = '4'
    $env:GROM_OCR_RAPIDOCR_VARIANT_CONSISTENCY_BONUS = '3.2'
    $env:GROM_OCR_RAPIDOCR_MIN_ACCEPT_SCORE = '46'
    $env:GROM_OCR_RAPIDOCR_MIN_ACCEPT_CONF = '26'
    $env:GROM_OCR_RAPIDOCR_PATTERN_MIN_SCORE = '60'
    $env:GROM_OCR_RAPIDOCR_MIN_VARIANT_HITS = '2'
    $env:GROM_OCR_PDF_PAGE_CANDIDATE_LIMIT = '2'
    $env:GROM_OCR_PDF_PAGE_EARLY_SCORE = '118'
    $env:GROM_OCR_PDF_MAX_REGION_CANDIDATES = '2'
    $env:GROM_OCR_PDF_PROBE_MAX_SIDE = '1200'
    $env:GROM_OCR_VISUAL_PROFILE_ENABLE = '1'
    $env:GROM_OCR_VISUAL_PROFILE_MAX_SIDE = '1280'
    $env:GROM_OCR_VISUAL_PROFILE_MIN_CONFIDENCE = '42'
    $env:GROM_OCR_VISUAL_PROFILE_TOP_HYPOTHESES = '3'
    $env:GROM_OCR_VISUAL_FIPE_ENABLE = '1'
    $env:GROM_OCR_VISUAL_FIPE_BASE_URL = 'https://fipe.parallelum.com.br/api/v2'
    $env:GROM_OCR_VISUAL_FIPE_TIMEOUT = '3'
}

function Start-PythonApi {
    if (-not (Test-Path $pythonExe)) {
        throw "Python virtualenv nao encontrado em: $pythonExe"
    }
    if (-not (Test-Path $pythonScript)) {
        throw "Script da API OCR nao encontrado em: $pythonScript"
    }

    $logsDir = Join-Path $projectRoot 'logs'
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir | Out-Null
    }

    $pythonOut = Join-Path $logsDir 'python-api.out.log'
    $pythonErr = Join-Path $logsDir 'python-api.err.log'
    $env:GROM_OCR_API_PORT = "$ApiPort"
    $env:GROM_OCR_API_HOST = '127.0.0.1'
    Start-Process -FilePath $pythonExe -ArgumentList $pythonScript -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $pythonOut -RedirectStandardError $pythonErr | Out-Null
}

function Start-PhpServer {
    $phpExe = Resolve-PhpExe
    if (-not $phpExe) {
        Write-Status 'PHP nao encontrado. Instale o PHP ou ajuste o PATH para o arranque automatico.' -Warning
        return $false
    }

    $logsDir = Join-Path $projectRoot 'logs'
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir | Out-Null
    }

    $phpOut = Join-Path $logsDir 'php-server.out.log'
    $phpErr = Join-Path $logsDir 'php-server.err.log'
    $env:GROM_OCR_PYTHON_API_URL = "http://127.0.0.1:$ApiPort"
    Start-Process -FilePath $phpExe -ArgumentList @('-S', "127.0.0.1:$PhpPort", '-t', 'public') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $phpOut -RedirectStandardError $phpErr | Out-Null
    return $true
}

Set-ServiceEnv

$startPython = $true
$startPhp = $true
if ($PythonOnly -and $PhpOnly) {
    Write-Status 'Os switches PythonOnly e PhpOnly sao conflitantes; iniciando ambos os servicos.' -Warning
}
elseif ($PythonOnly) {
    $startPhp = $false
}
elseif ($PhpOnly) {
    $startPython = $false
}

$pythonReady = Test-ApiHealth -Port $ApiPort
if ($startPython -and -not $pythonReady) {
    if (-not (Test-PortListening -Port $ApiPort)) {
        Write-Status "Iniciando API OCR em http://127.0.0.1:$ApiPort ..."
        Start-PythonApi
    }
    else {
        Write-Status "A porta $ApiPort ja esta em uso. Aguardando resposta do /health..." -Warning
    }

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ApiHealth -Port $ApiPort) {
            $pythonReady = $true
            break
        }
        Start-Sleep -Milliseconds 750
    }

    if ($pythonReady) {
        Write-Status "API OCR pronta em http://127.0.0.1:$ApiPort"
    }
    else {
        Write-Status "API OCR ainda nao respondeu ao /health. Verifique os logs em C:\\Grom_OCR\\logs." -Warning
    }
}

if ($startPhp) {
    if (Test-PortListening -Port $PhpPort) {
        Write-Status "Aplicacao PHP ja esta escutando em http://127.0.0.1:$PhpPort"
    }
    else {
        Write-Status "Iniciando aplicacao PHP em http://127.0.0.1:$PhpPort ..."
        [void](Start-PhpServer)
    }
}

Write-Status 'Arranque automatizado concluido.'
