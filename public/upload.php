<?php
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_start();
}
if (!isset($_SESSION['user_id'])) {
    header('Location: /login.php');
    exit;
}

require_once __DIR__ . '/../app/models/User.php';

$responsavelAnalise = trim((string) (
    User::resolveSessionLabel($_SESSION)
));
if ($responsavelAnalise === '') {
    $responsavelAnalise = 'Operador autenticado';
}
$operatorLabel = $responsavelAnalise;

@set_time_limit(600);
@ini_set('max_execution_time', '600');

$app = require __DIR__ . '/../config/app.php';
$db = require __DIR__ . '/../config/database.php';
$pythonApiUrl = $app['python_api_url'];
$ocrMinConfidence = (float) ($app['ocr_min_confidence'] ?? 75);

$result = null;
$errorMessage = null;
$dbWarning = null;
$veiculo = [];
$vehicleLookupUrl = trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_URL') ?: ''));
$vehicleLookupUrls = trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_URLS') ?: ''));
$vehicleLookupProvider = strtolower(trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_PROVIDER') ?: '')));
$senatranEnabledRaw = strtolower(trim((string) (getenv('GROM_OCR_SENATRAN_ENABLE') ?: '0')));
$senatranConfigured = in_array($senatranEnabledRaw, ['1', 'true', 'yes', 'on', 'sim'], true)
    || in_array($vehicleLookupProvider, ['senatran', 'serpro', 'senatran_serpro', 'wsdenatran', 'consulta_senatran'], true)
    || trim((string) (getenv('GROM_OCR_SENATRAN_URL') ?: '')) !== '';
$prodespEnabledRaw = strtolower(trim((string) (getenv('GROM_OCR_PRODESP_ENABLE') ?: '0')));
$prodespConfigured = in_array($prodespEnabledRaw, ['1', 'true', 'yes', 'on', 'sim'], true)
    || in_array($vehicleLookupProvider, ['prodesp', 'prodesp_detran_sp', 'detran_sp', 'consulta_veiculos_sp'], true)
    || trim((string) (getenv('GROM_OCR_PRODESP_URL') ?: '')) !== '';
$useZapayEnabledRaw = strtolower(trim((string) (getenv('GROM_OCR_USEZAPAY_ENABLE') ?: '0')));
$useZapayConfigured = in_array($useZapayEnabledRaw, ['1', 'true', 'yes', 'on', 'sim'], true) || $vehicleLookupProvider === 'usezapay';
$vehicleLookupConfigured = $vehicleLookupUrl !== '' || $vehicleLookupUrls !== '' || $useZapayConfigured || $senatranConfigured || $prodespConfigured;
$openDataEnabledRaw = strtolower(trim((string) (getenv('GROM_OCR_OPEN_DATA_ENABLE') ?: '1')));
$openDataEnabled = !in_array($openDataEnabledRaw, ['0', 'false', 'off', 'nao', 'no'], true);
$requestMethod = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$finalizeReviewRequested = $requestMethod === 'POST' && isset($_POST['finalize_review']);
$analysisPreviewRequested = $requestMethod === 'POST' && !$finalizeReviewRequested;

function parseAllowedUploadExtensions(string $raw): array
{
    $raw = trim($raw);
    if ($raw === '') {
        return ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.pdf'];
    }

    $extensions = [];
    foreach (preg_split('/[;,|]+/', $raw) ?: [] as $token) {
        $item = strtolower(trim((string) $token));
        if ($item === '') {
            continue;
        }
        if ($item[0] !== '.') {
            $item = '.' . $item;
        }
        $extensions[$item] = true;
    }

    return $extensions ? array_keys($extensions) : ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.pdf'];
}

function parsePositiveIntEnv(string $name, int $default): int
{
    $raw = trim((string) (getenv($name) ?: ''));
    if ($raw === '') {
        return $default;
    }
    if (!is_numeric($raw)) {
        return $default;
    }
    $parsed = (int) floor((float) $raw);
    return $parsed > 0 ? $parsed : $default;
}

function getUploadMaxBytes(): int
{
    $explicit = parsePositiveIntEnv('GROM_OCR_MAX_UPLOAD_BYTES', 0);
    if ($explicit > 0) {
        return $explicit;
    }

    $maxMb = parsePositiveIntEnv('GROM_OCR_MAX_UPLOAD_MB', 80);
    return $maxMb * 1024 * 1024;
}

function detectUploadSignature(string $tmpPath): array
{
    $signature = [
        'kind' => 'unknown',
        'mime' => '',
        'family' => 'unknown',
        'recognized' => false,
    ];

    if ($tmpPath === '' || !is_file($tmpPath)) {
        return $signature;
    }

    $handle = @fopen($tmpPath, 'rb');
    if (!$handle) {
        return $signature;
    }

    $header = fread($handle, 16);
    fclose($handle);
    if (!is_string($header)) {
        return $signature;
    }

    if (strncmp($header, '%PDF', 4) === 0) {
        return ['kind' => 'pdf', 'mime' => 'application/pdf', 'family' => 'pdf', 'recognized' => true];
    }
    if (strlen($header) >= 3 && substr($header, 0, 3) === "\xFF\xD8\xFF") {
        return ['kind' => 'jpeg', 'mime' => 'image/jpeg', 'family' => 'image', 'recognized' => true];
    }
    if (strlen($header) >= 8 && substr($header, 0, 8) === "\x89PNG\r\n\x1A\n") {
        return ['kind' => 'png', 'mime' => 'image/png', 'family' => 'image', 'recognized' => true];
    }
    if (strlen($header) >= 12 && substr($header, 0, 4) === 'RIFF' && substr($header, 8, 4) === 'WEBP') {
        return ['kind' => 'webp', 'mime' => 'image/webp', 'family' => 'image', 'recognized' => true];
    }
    if (strlen($header) >= 2 && substr($header, 0, 2) === 'BM') {
        return ['kind' => 'bmp', 'mime' => 'image/bmp', 'family' => 'image', 'recognized' => true];
    }
    if (strlen($header) >= 4) {
        $prefix = substr($header, 0, 2);
        $marker = substr($header, 2, 2);
        if (($prefix === 'II' || $prefix === 'MM') && ($marker === "*\x00" || $marker === "\x00*")) {
            return ['kind' => 'tiff', 'mime' => 'image/tiff', 'family' => 'image', 'recognized' => true];
        }
    }

    return $signature;
}

function buildUploadSecuritySummary(array $file): array
{
    $allowedExtensions = parseAllowedUploadExtensions(getenv('GROM_OCR_ALLOWED_INPUT_EXTENSIONS') ?: '');
    $maxBytes = getUploadMaxBytes();
    $name = (string) ($file['name'] ?? '');
    $tmpPath = (string) ($file['tmp_name'] ?? '');
    $ext = strtolower((string) pathinfo($name, PATHINFO_EXTENSION));
    $ext = $ext !== '' ? '.' . $ext : '';
    $sizeBytes = (int) ($file['size'] ?? 0);
    $contentType = strtolower(trim((string) ($file['type'] ?? '')));
    $signature = detectUploadSignature($tmpPath);

    $allowed = false;
    $error = '';
    $warnings = [];

    if ($tmpPath === '' || !is_file($tmpPath)) {
        $error = 'Arquivo temporário não encontrado';
    } elseif ($sizeBytes <= 0) {
        $error = 'Arquivo enviado esta vazio';
    } elseif (!in_array($ext, $allowedExtensions, true)) {
        $error = 'Extensão não permitida para análise';
    } elseif ($sizeBytes > $maxBytes) {
        $error = 'Arquivo enviado excede o limite configurado';
    } elseif (empty($signature['recognized'])) {
        $error = 'Assinatura do arquivo não reconhecida';
    } elseif ($ext === '.pdf' && ($signature['kind'] ?? '') !== 'pdf') {
        $error = 'Arquivo PDF invalido ou corrompido';
    } elseif ($ext !== '.pdf' && ($signature['family'] ?? '') !== 'image') {
        $error = 'Arquivo de imagem invalido ou corrompido';
    } else {
        $allowed = true;
        if ($contentType !== '' && !in_array($contentType, ['application/octet-stream', (string) ($signature['mime'] ?? '')], true)) {
            $warnings[] = 'content_type_divergente';
        }
        if ($sizeBytes >= (int) floor($maxBytes * 0.8)) {
            $warnings[] = 'arquivo_proximo_do_limite';
        }
    }

    return [
        'status' => $allowed ? 'ok' : 'blocked',
        'allowed' => $allowed,
        'error' => $error,
        'warnings' => $warnings,
        'original_filename' => basename($name),
        'extension' => $ext,
        'input_type' => $ext === '.pdf' ? 'pdf' : (($ext !== '' && in_array($ext, ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'], true)) ? 'image' : 'unsupported'),
        'content_type' => $contentType,
        'detected_signature' => (string) ($signature['kind'] ?? 'unknown'),
        'detected_mime' => (string) ($signature['mime'] ?? ''),
        'signature_ok' => $allowed && $error === '',
        'file_size_bytes' => $sizeBytes,
        'file_size_mb' => round($sizeBytes / (1024 * 1024), 2),
        'max_upload_bytes' => $maxBytes,
        'max_upload_mb' => round($maxBytes / (1024 * 1024), 2),
        'allowed_extensions' => $allowedExtensions,
        'policy' => 'allowlist_extension+signature+size',
    ];
}

function normalizeApiBase(string $url): string
{
    return rtrim(trim($url), '/');
}

function buildApiCandidates(string $primaryUrl): array
{
    $primaryNormalized = normalizeApiBase($primaryUrl);
    $candidates = [$primaryNormalized];

    $parts = parse_url($primaryNormalized);
    if (is_array($parts)) {
        $host = strtolower((string) ($parts['host'] ?? ''));
        if ($host === '127.0.0.1' || $host === 'localhost') {
            $scheme = (string) ($parts['scheme'] ?? 'http');
            array_unshift($candidates, normalizeApiBase($scheme . '://127.0.0.1:8001'));
        }
    }

    if (strpos($primaryUrl, ':5000') !== false) {
        $candidates[] = normalizeApiBase(str_replace(':5000', ':8000', $primaryUrl));
        $candidates[] = normalizeApiBase(str_replace(':5000', ':8001', $primaryUrl));
    } elseif (strpos($primaryUrl, ':8000') !== false) {
        $candidates[] = normalizeApiBase(str_replace(':8000', ':5000', $primaryUrl));
        $candidates[] = normalizeApiBase(str_replace(':8000', ':8001', $primaryUrl));
    } elseif (strpos($primaryUrl, ':8001') !== false) {
        $candidates[] = normalizeApiBase(str_replace(':8001', ':8000', $primaryUrl));
        $candidates[] = normalizeApiBase(str_replace(':8001', ':5000', $primaryUrl));
    }

    if (strpos($primaryUrl, '127.0.0.1') !== false) {
        $candidates[] = normalizeApiBase(str_replace('127.0.0.1', 'localhost', $primaryUrl));
    } elseif (strpos($primaryUrl, 'localhost') !== false) {
        $candidates[] = normalizeApiBase(str_replace('localhost', '127.0.0.1', $primaryUrl));
    }

    $fallbacksRaw = getenv('GROM_OCR_PYTHON_API_FALLBACK_URLS') ?: '';
    if ($fallbacksRaw !== '') {
        foreach (explode(',', $fallbacksRaw) as $item) {
            $item = trim($item);
            if ($item !== '') {
                $candidates[] = normalizeApiBase($item);
            }
        }
    }

    return array_values(array_unique(array_filter($candidates)));
}

function normalizePlateValue(string $value): string
{
    return strtoupper((string) preg_replace('/[^A-Z0-9]/', '', $value));
}

function normalizePlatePatternLabel(string $pattern): string
{
    $normalized = trim($pattern);
    if ($normalized === 'Antiga (cinza)') {
        return 'Antigo';
    }
    if ($normalized === '') {
        return 'Indefinido';
    }
    return $normalized;
}

function normalizePericialLabelKey(string $value): string
{
    $text = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $value);
    if ($text === false || $text === null) {
        $text = $value;
    }
    $text = strtoupper(trim((string) $text));
    $text = preg_replace('/[^A-Z0-9]+/', '_', $text) ?? '';
    return trim(preg_replace('/_+/', '_', $text) ?? '', '_');
}

function accentuatePortugueseText(string $value): string
{
    $map = [
        'acuracia' => 'acurácia',
        'analise' => 'análise',
        'analises' => 'análises',
        'aprovacao' => 'aprovação',
        'avancada' => 'avançada',
        'avaliacao' => 'avaliação',
        'calibracao' => 'calibração',
        'classificacao' => 'classificação',
        'compativel' => 'compatível',
        'compativeis' => 'compatíveis',
        'conferencia' => 'conferência',
        'conferencias' => 'conferências',
        'consolidacao' => 'consolidação',
        'correlacao' => 'correlação',
        'correcao' => 'correção',
        'custodia' => 'custódia',
        'decisao' => 'decisão',
        'descricao' => 'descrição',
        'deteccao' => 'detecção',
        'divergencia' => 'divergência',
        'divergencias' => 'divergências',
        'documentacao' => 'documentação',
        'documental' => 'documental',
        'evidencia' => 'evidência',
        'evidencias' => 'evidências',
        'estrategia' => 'estratégia',
        'factors' => 'factors',
        'geracao' => 'geração',
        'historico' => 'histórico',
        'hipotese' => 'hipótese',
        'hipoteses' => 'hipóteses',
        'identificacao' => 'identificação',
        'impressao' => 'impressão',
        'inferencia' => 'inferência',
        'integridade' => 'integridade',
        'interpretacao' => 'interpretação',
        'notas' => 'notas',
        'observacao' => 'observação',
        'observacoes' => 'observações',
        'operacao' => 'operação',
        'padrao' => 'padrão',
        'padroes' => 'padrões',
        'pos' => 'pós',
        'pre' => 'pré',
        'probatoria' => 'probatória',
        'probatorio' => 'probatório',
        'processamento' => 'processamento',
        'protocolo' => 'protocolo',
        'qualificacao' => 'qualificação',
        'qualidade' => 'qualidade',
        'confianca' => 'confiança',
        'conclusao' => 'conclusão',
        'correcao' => 'correção',
        'revisao' => 'revisão',
        'seguranca' => 'segurança',
        'situacao' => 'situação',
        'sintese' => 'síntese',
        'tecnica' => 'técnica',
        'tecnicas' => 'técnicas',
        'tecnico' => 'técnico',
        'tecnicos' => 'técnicos',
        'validacao' => 'validação',
        'veiculo' => 'veículo',
        'veiculos' => 'veículos',
    ];

    $parts = preg_split('/(\W+)/u', $value, -1, PREG_SPLIT_DELIM_CAPTURE);
    if ($parts === false) {
        return $value;
    }

    foreach ($parts as $index => $part) {
        if ($part === '' || !preg_match('/^[\p{L}]+$/u', $part)) {
            continue;
        }

        $normalized = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $part);
        if ($normalized === false || $normalized === null) {
            $normalized = $part;
        }
        $key = strtolower((string) $normalized);
        if (!isset($map[$key])) {
            continue;
        }

        $replacement = $map[$key];
        if (function_exists('mb_substr') && function_exists('mb_strtoupper')) {
            if (mb_strtoupper($part, 'UTF-8') === $part) {
                $replacement = mb_strtoupper($replacement, 'UTF-8');
            } elseif (mb_strtoupper(mb_substr($part, 0, 1, 'UTF-8'), 'UTF-8') === mb_substr($part, 0, 1, 'UTF-8')) {
                $replacement = mb_strtoupper(mb_substr($replacement, 0, 1, 'UTF-8'), 'UTF-8') . mb_substr($replacement, 1, null, 'UTF-8');
            }
        } elseif (strtoupper($part) === $part) {
            $replacement = strtoupper($replacement);
        } elseif (ctype_upper(substr($part, 0, 1))) {
            $replacement = ucfirst($replacement);
        }

        $parts[$index] = $replacement;
    }

    return implode('', $parts);
}

function humanizePericialLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'A' => 'Boa',
        'ALTA' => 'Alta',
        'ATENCAO' => 'Atenção',
        'BAIXA' => 'Baixa',
        'B' => 'Razoável',
        'BALANCED' => 'Balanceado',
        'BACKLIT' => 'Contraluz',
        'BLURRED' => 'Borrado',
        'BRIGHT' => 'Muito claro',
        'BOA' => 'Boa',
        'BLOCKED' => 'Bloqueado',
        'C' => 'Ruim',
        'COMPATIVEL' => 'Compatível',
        'CONCLUSIVO' => 'Conclusivo',
        'CONFIRMADO_MANUAL' => 'Ratificada manualmente',
        'CORRIGIDO_MANUAL' => 'Ratificada com ajuste',
        'REGISTRADO' => 'Registrado em conferência',
        'CONFERENCIA_HUMANA' => 'Conferência técnico-pericial',
        'CONFERENCIA_TECNICO_PERICIAL' => 'Conferência técnico-pericial',
        'DARK' => 'Escuro',
        'EMPTY_SCENE' => 'Cena vazia',
        'GLARE' => 'Reflexo intenso',
        'LOW_CONTRAST' => 'Baixo contraste',
        'MOTION_BLUR' => 'Borrado por movimento',
        'NOISY' => 'Ruidoso',
        'OVEREXPOSED' => 'Estourado',
        'PARTIAL' => 'Parcial',
        'READY' => 'Pronto',
        'UNDEREXPOSED' => 'Subexposto',
        'CRITICA' => 'Crítica',
        'D' => 'Imprópria',
        'EXCELENTE' => 'Excelente',
        'DISABLED' => 'Desabilitado',
        'AVAILABLE' => 'Disponível',
        'CONFIGURED' => 'Configurado',
        'FORTEMENTE_COMPATIVEL' => 'Fortemente compatível',
        'FALLBACK_FULL_SCENE' => 'Imagem completa',
        'IMPROPRIA' => 'Imprópria',
        'INCOMPATIVEL' => 'Incompatível',
        'INCONCLUSIVO' => 'Inconclusivo',
        'INDEFINIDO' => 'Indefinido',
        'INDEFINIDA' => 'Indefinida',
        'MEDIA' => 'Média',
        'MUITO_PROVAVELMENTE_CORRESPONDENTE' => 'Muito provavelmente correspondente',
        'OK' => 'Ok',
        'POUCO_COMPATIVEL' => 'Pouco compatível',
        'RAZOAVEL' => 'Razoável',
        'REGULAR' => 'Regular',
        'RESULTADO_CACHE' => 'Resultado em cache',
        'EXECUTED' => 'Executado',
        'FAILED' => 'Falhou',
        'SKIPPED' => 'Ignorado',
        'PENDING' => 'Pendente',
        'PENDING_ASYNC' => 'Pendente',
        'PENDENTE_WEBHOOK' => 'Pendente de webhook',
        'PENDENTE_WEBHOOK_USEZAPAY' => 'Pendente de webhook',
        'PENDENTE_NO_PHP' => 'Pendente no PHP',
        'UNAVAILABLE' => 'Indisponível',
        'NAO_DISPONIVEL' => 'Não disponível',
        'REVISAO_OBRIGATORIA' => 'Revisão obrigatória',
        'ROI_DETECTADO' => 'ROI detectado',
        'SEM_CANDIDATO' => 'Sem candidato',
        'SEM_ROI_CONFIAVEL' => 'Sem ROI confiável',
        'VALIDADO' => 'Validado',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    $fallback = preg_replace('/\s+/', ' ', str_replace(['_', '-'], ' ', $raw));
    $fallback = trim((string) $fallback);
    if ($fallback === '') {
        return 'Indefinido';
    }

    $lower = function_exists('mb_strtolower') ? mb_strtolower($fallback, 'UTF-8') : strtolower($fallback);
    return accentuatePortugueseText(ucfirst($lower));
}

function humanizeSceneLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'BALANCED' => 'Balanceado',
        'BLURRED' => 'Borrado',
        'BRIGHT' => 'Muito claro',
        'DARK' => 'Escuro',
        'DISABLED' => 'Desabilitado',
        'EMPTY_SCENE' => 'Cena vazia',
        'GLARE' => 'Reflexo intenso',
        'LOW_CONTRAST' => 'Baixo contraste',
        'MOTION_BLUR' => 'Borrado por movimento',
        'NOISY' => 'Ruidoso',
        'OVEREXPOSED' => 'Estourado',
        'UNDEREXPOSED' => 'Subexposto',
        'BACKLIT' => 'Contraluz',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    return humanizePericialLabel($raw);
}

function humanizeEngineHealthLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'AVAILABLE' => 'Disponivel',
        'CONFIGURED' => 'Configurado',
        'DISABLED' => 'Desabilitado',
        'EXECUTED' => 'Executado',
        'FAILED' => 'Falhou',
        'OK' => 'Ok',
        'PARTIAL' => 'Parcial',
        'READY' => 'Pronto',
        'SKIPPED' => 'Ignorado',
        'UNAVAILABLE' => 'Indisponivel',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    return humanizePericialLabel($raw);
}

function humanizeRoiQualityLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'A' => 'Boa',
        'BOA' => 'Boa',
        'B' => 'Razoável',
        'C' => 'Ruim',
        'D' => 'Imprópria',
        'EXCELENTE' => 'Excelente',
        'REGULAR' => 'Regular',
        'CRITICA' => 'Crítica',
        'IMPROPRIA' => 'Imprópria',
        'INDEFINIDA' => 'Indefinida',
        'INDEFINIDO' => 'Indefinido',
        'SEM_ROI_CONFIAVEL' => 'Sem ROI confiável',
        'ROI_DETECTADO' => 'ROI detectado',
        'FALLBACK_FULL_SCENE' => 'Imagem completa',
        'SEM_CANDIDATO' => 'Sem candidato',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    return humanizePericialLabel($raw);
}

function humanizeOfficialValidationLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'VALIDADO' => 'Validado',
        'OK' => 'Ok',
        'RESULTADO_CACHE' => 'Resultado em cache',
        'PENDENTE_WEBHOOK' => 'Pendente de webhook',
        'PENDENTE_WEBHOOK_USEZAPAY' => 'Pendente de webhook',
        'PENDING' => 'Pendente',
        'PENDING_ASYNC' => 'Pendente',
        'NAO_DISPONIVEL' => 'Não disponível',
        'NAO_CONFIGURADO' => 'Não configurado',
        'SEM_RETORNO' => 'Sem retorno',
        'SEM_HISTORICO' => 'Sem histórico',
        'ESTIMADO_FONTES_ABERTAS' => 'Estimado por fontes abertas',
        'REVISAO_OBRIGATORIA' => 'Revisão obrigatória',
        'ERRO' => 'Erro',
        'INDEFINIDO' => 'Indefinido',
        'INDEFINIDA' => 'Indefinida',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    return humanizePericialLabel($raw);
}

function humanizeOfficialValidationSourceKindLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinido';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'OFFICIAL_SENATRAN' => 'Fonte oficial Senatran',
        'OFFICIAL_SERPRO' => 'Fonte oficial Serpro',
        'OFFICIAL_SINESP' => 'Fonte oficial Sinesp',
        'USEZAPAY' => 'UseZapay',
        'OPEN_VISUAL_FALLBACK' => 'Análise visual local',
        'ESTIMADO_FONTES_ABERTAS' => 'Fontes abertas',
        'OPEN_DATA_FIPE' => 'FIPE aberta',
        'FIPE' => 'FIPE',
        'INDEFINIDO' => 'Indefinido',
    ];

    if (isset($map[$key])) {
        return accentuatePortugueseText($map[$key]);
    }

    return humanizePericialLabel($raw);
}

function humanizeOfficialValidationSourceLabel($value): string
{
    $raw = trim((string) ($value ?? ''));
    if ($raw === '') {
        return 'Indefinida';
    }

    $key = normalizePericialLabelKey($raw);
    $map = [
        'ANALISE_VISUAL_LOCAL_HEURISTICA' => 'Análise visual local heurística',
        'ANALISE_VISUAL_LOCAL' => 'Análise visual local',
        'SENATRAN' => 'Senatran',
        'SERPRO' => 'Serpro',
        'SINESP' => 'Sinesp Cidadão',
        'SINESP_CIDADAO' => 'Sinesp Cidadão',
        'USEZAPAY' => 'UseZapay',
        'FIPE' => 'FIPE',
        'FIPE_PARALELUM' => 'FIPE aberta',
        'OPEN_DATA' => 'Dados abertos',
        'OPEN_VISUAL_FALLBACK' => 'Análise visual local',
        'ESTIMADO_FONTES_ABERTAS' => 'Fontes abertas',
        'INDEFINIDA' => 'Indefinida',
    ];

    if (isset($map[$key])) {
        return $map[$key];
    }

    return humanizePericialLabel($raw);
}

function extractPlatePatternLabel(array $result): string
{
    $patternInfo = is_array($result['plate_pattern_info'] ?? null) ? $result['plate_pattern_info'] : [];
    $fromInfo = trim((string) ($patternInfo['padrao_placa'] ?? ''));
    if ($fromInfo !== '') {
        return normalizePlatePatternLabel($fromInfo);
    }

    $colorInfo = is_array($result['color_info'] ?? null) ? $result['color_info'] : [];
    $fromColorInfo = trim((string) ($colorInfo['padrao_placa'] ?? $colorInfo['detected_pattern'] ?? ''));
    if ($fromColorInfo !== '') {
        return normalizePlatePatternLabel($fromColorInfo);
    }

    $best = is_array($result['best'] ?? null) ? $result['best'] : [];
    $fromBest = trim((string) ($best['pattern'] ?? ''));
    if ($fromBest !== '') {
        return normalizePlatePatternLabel($fromBest);
    }

    $pericial = is_array($result['pericial'] ?? null) ? $result['pericial'] : [];
    $legal = is_array($pericial['legal_validation'] ?? null) ? $pericial['legal_validation'] : [];
    $fromLegal = trim((string) ($legal['detected_pattern'] ?? $legal['best_fit_pattern'] ?? ''));
    return $fromLegal !== '' ? normalizePlatePatternLabel($fromLegal) : 'Indefinido';
}

function buildLocalHistoryCrossCheck(array $historyMatches): array
{
    if (!$historyMatches) {
        return [
            'status' => 'sem_historico',
            'previous_occurrences' => 0,
        ];
    }

    $engines = [];
    $lastSeen = '';
    $confidenceSamples = [];
    foreach ($historyMatches as $row) {
        $engine = (string) ($row['engine'] ?? '');
        if ($engine !== '') {
            $engines[$engine] = true;
        }
        if ($lastSeen === '' && !empty($row['datahora'])) {
            $lastSeen = (string) $row['datahora'];
        }
        if (isset($row['avg_conf'])) {
            $confidenceSamples[] = (float) $row['avg_conf'];
        }
    }

    $avgConf = 0.0;
    if ($confidenceSamples) {
        $avgConf = array_sum($confidenceSamples) / count($confidenceSamples);
    }

    return [
        'status' => 'ok',
        'previous_occurrences' => count($historyMatches),
        'last_seen' => $lastSeen !== '' ? $lastSeen : null,
        'engines_seen' => array_keys($engines),
        'historical_avg_confidence' => round($avgConf, 2),
    ];
}

function buildOpenSourceVisualVehicleFallback(array $result): array
{
    $visualProfile = is_array($result['visual_profile'] ?? null) ? $result['visual_profile'] : [];
    $principal = is_array($visualProfile['hipotese_principal'] ?? null) ? $visualProfile['hipotese_principal'] : [];
    if (!$principal) {
        return [];
    }

    $fabricante = trim((string) ($principal['fabricante'] ?? ''));
    $modelo = trim((string) ($principal['modelo'] ?? ''));
    $anoFaixa = trim((string) ($principal['faixa_ano_modelo'] ?? ''));
    $confianca = (float) ($principal['confianca'] ?? 0);
    if ($fabricante === '' || $modelo === '' || $confianca < 35.0) {
        return [];
    }

    $best = is_array($result['best'] ?? null) ? $result['best'] : [];
    $plate = normalizePlateValue((string) ($best['text'] ?? ''));

    $comparison = is_array($visualProfile['comparativo_fontes_abertas'] ?? null) ? $visualProfile['comparativo_fontes_abertas'] : [];
    $sourceLinks = is_array($comparison['fontes'] ?? null) ? $comparison['fontes'] : [];
    $sourceNames = [];
    foreach ($sourceLinks as $item) {
        if (!is_array($item)) {
            continue;
        }
        $name = trim((string) ($item['fonte'] ?? ''));
        if ($name !== '') {
            $sourceNames[] = $name;
        }
    }
    $sourceNames = array_values(array_unique($sourceNames));

    $fallback = [
        'placa' => $plate !== '' ? $plate : 'indisponivel',
        'fabricante' => $fabricante,
        'marca_modelo' => trim((string) ($fabricante !== '' || $modelo !== '' ? ($fabricante . ' / ' . $modelo) : '')),
        'modelo' => $modelo,
        'ano' => $anoFaixa !== '' ? $anoFaixa : 'estimado_por_heuristica_visual',
        'cor' => trim((string) ($visualProfile['cor_probavel'] ?? '')) !== '' ? (string) $visualProfile['cor_probavel'] : 'indefinida',
        'chassi' => 'indisponivel_em_fonte_aberta_sem_provedor_por_placa',
        'fonte' => 'analise_visual_local_heuristica',
        'fonte_complementar' => 'consultas_abertas_multiplas_fontes',
        'fontes_utilizadas' => !empty($sourceNames) ? implode(' | ', $sourceNames) : 'fontes_abertas_nao_estruturadas',
        'observacao' => 'Dados estimados por fontes abertas e heuristica visual; exige validacao humana.',
    ];

    $fallback['consulta_multifonte_status'] = 'estimado_fontes_abertas';
    $fallback['consulta_multifonte_candidatos'] = max(1, count($sourceNames));
    $fallback['consulta_multifonte_oficiais'] = 'nenhuma';
    $fallback['consulta_multifonte_fontes'] = !empty($sourceNames) ? implode(' | ', $sourceNames) : 'fontes_abertas_nao_estruturadas';
    $fallback['consulta_multifonte_confianca'] = number_format($confianca, 1, '.', '');
    $fallback['consulta_multifonte_taxa_consenso'] = number_format($confianca, 1, '.', '');
    $fallback['consulta_multifonte_consenso'] = 'fabricante, modelo, ano';
    $fallback['consulta_multifonte_divergencias'] = 'sem_divergencias_em_fontes_estruturadas';
    $fallback['consulta_multifonte_resumo'] = 'Hipótese visual consolidada com apoio de fontes abertas e heurística local.';
    $fallback['consulta_multifonte_score'] = number_format($confianca, 1, '.', '');
    $fallback['consulta_multifonte_fonte_principal'] = 'analise_visual_local_heuristica';
    $fallback['consulta_multifonte_fonte_tipo'] = 'open_visual_fallback';
    $fallback['consulta_multifonte_alertas'] = 'validacao_manual_obrigatoria';
    $fallback['consulta_multifonte_limite'] = max(1, count($sourceNames));
    $fallback['consulta_multifonte_limite_aplicado'] = 'Não';

    if (is_array($comparison['sinal_lanterna_traseira'] ?? null)) {
        $rear = $comparison['sinal_lanterna_traseira'];
        $fallback['sinal_lanterna_traseira'] = json_encode($rear, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    $fallback['official_validation'] = [
        'status' => 'estimado_fontes_abertas',
        'is_official' => false,
        'source_kind' => 'open_visual_fallback',
        'source_label' => 'analise_visual_local_heuristica',
        'source_url' => '',
        'lookup_plate' => $plate !== '' ? $plate : 'indisponivel',
        'public_fields' => ['placa', 'fabricante', 'modelo', 'ano', 'cor'],
        'public_fields_found' => array_values(array_filter([
            $plate !== '' ? 'placa' : '',
            $fabricante !== '' ? 'fabricante' : '',
            $modelo !== '' ? 'modelo' : '',
            $anoFaixa !== '' ? 'ano' : '',
            trim((string) ($visualProfile['cor_probavel'] ?? '')) !== '' ? 'cor' : '',
        ])),
        'public_fields_missing' => array_values(array_filter([
            $plate === '' ? 'placa' : '',
            $fabricante === '' ? 'fabricante' : '',
            $modelo === '' ? 'modelo' : '',
            $anoFaixa === '' ? 'ano' : '',
            trim((string) ($visualProfile['cor_probavel'] ?? '')) === '' ? 'cor' : '',
        ])),
        'sensitive_fields' => ['chassi', 'renavam', 'proprietario', 'cpf_cnpj', 'endereco'],
        'sensitive_fields_found' => [],
        'sensitive_fields_masked' => true,
        'sensitive_policy' => 'indisponivel_sem_provedor_oficial',
        'public_fields_count' => $fabricante !== '' && $modelo !== '' ? 4 : 2,
        'sensitive_fields_count' => 0,
        'notes' => [
            'fallback_visual_sem_provedor_oficial',
            'validacao_manual_obrigatoria',
        ],
    ];

    return $fallback;
}

function maskVehicleSensitiveValue(string $value, int $visibleTail = 4): string
{
    $clean = trim($value);
    if ($clean === '') {
        return '';
    }

    $compact = preg_replace('/\s+/', '', $clean);
    if (!is_string($compact) || $compact === '') {
        return $clean;
    }

    $length = strlen($compact);
    if ($visibleTail <= 0) {
        return str_repeat('*', max(1, $length));
    }

    if ($length <= $visibleTail) {
        return str_repeat('*', max(1, $length));
    }

    return str_repeat('*', max(1, $length - $visibleTail)) . substr($compact, -$visibleTail);
}

function buildVehicleDisplayInfo(array $vehicle): array
{
    if (!$vehicle) {
        return [];
    }

    $display = $vehicle;
    $fieldsToMask = [
        'chassi' => 4,
        'renavam' => 4,
        'proprietario' => 0,
        'cpf_cnpj' => 0,
        'endereco' => 0,
        'estampador' => 0,
        'codigo_seguranca_crv' => 3,
        'serial_qrcode' => 4,
    ];

    foreach ($fieldsToMask as $field => $visibleTail) {
        if (!isset($display[$field]) || trim((string) $display[$field]) === '') {
            continue;
        }

        $display[$field] = $visibleTail > 0
            ? maskVehicleSensitiveValue((string) $display[$field], $visibleTail)
            : '[restrito]';
    }

    return $display;
}

function buildOfficialVehicleValidationSummary(array $vehicle): array
{
    $validation = is_array($vehicle['official_validation'] ?? null) ? $vehicle['official_validation'] : [];
    if (!$validation) {
        return [
            'status' => 'nao_disponivel',
        ];
    }

    return [
        'status' => (string) ($validation['status'] ?? 'indefinido'),
        'is_official' => !empty($validation['is_official']),
        'source_kind' => (string) ($validation['source_kind'] ?? 'indefinido'),
        'source_label' => (string) ($validation['source_label'] ?? 'indefinida'),
        'source_url' => (string) ($validation['source_url'] ?? ''),
        'lookup_plate' => (string) ($validation['lookup_plate'] ?? ''),
        'public_fields_found' => is_array($validation['public_fields_found'] ?? null) ? $validation['public_fields_found'] : [],
        'public_fields_missing' => is_array($validation['public_fields_missing'] ?? null) ? $validation['public_fields_missing'] : [],
        'sensitive_fields_found' => is_array($validation['sensitive_fields_found'] ?? null) ? $validation['sensitive_fields_found'] : [],
        'sensitive_policy' => (string) ($validation['sensitive_policy'] ?? ''),
        'notes' => is_array($validation['notes'] ?? null) ? $validation['notes'] : [],
    ];
}

function storePendingPreviewResult(array $result): void
{
    if (session_status() !== PHP_SESSION_ACTIVE) {
        session_start();
    }

    $analysisId = trim((string) (($result['forensic']['analysis_id'] ?? $result['report_context']['analysis_id'] ?? '') ?? ''));
    if ($analysisId === '') {
        $analysisId = 'analysis_' . bin2hex(random_bytes(6));
    }

    $_SESSION['grom_ocr_pending_preview'] = [
        'analysis_id' => $analysisId,
        'created_at_utc' => gmdate('c'),
        'result_json' => json_encode($result, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE),
    ];
}

function loadPendingPreviewResult(): array
{
    if (session_status() !== PHP_SESSION_ACTIVE) {
        session_start();
    }

    $payload = $_SESSION['grom_ocr_pending_preview'] ?? null;
    if (!is_array($payload)) {
        return [];
    }

    $resultJson = trim((string) ($payload['result_json'] ?? ''));
    if ($resultJson === '') {
        return [];
    }

    $decoded = json_decode($resultJson, true);
    return is_array($decoded) ? $decoded : [];
}

function clearPendingPreviewResult(): void
{
    if (session_status() !== PHP_SESSION_ACTIVE) {
        session_start();
    }

    unset($_SESSION['grom_ocr_pending_preview']);
}

function normalizeReviewDecision(string $value): string
{
    $value = strtolower(trim($value));
    $aliases = [
        'confirmado' => 'confirmado_manual',
        'confirmado_manual' => 'confirmado_manual',
        'corrigido' => 'corrigido_manual',
        'corrigido_manual' => 'corrigido_manual',
        'inconclusivo' => 'inconclusivo',
        'sem_candidato' => 'inconclusivo',
        'nao_confirmado' => 'inconclusivo',
        'nao_conclusivo' => 'inconclusivo',
    ];

    return $aliases[$value] ?? 'confirmado_manual';
}

function extractPreviewCandidate(array $topCandidates, int $index): array
{
    $normalized = array_values(array_filter($topCandidates, 'is_array'));
    if ($index < 0 || $index >= count($normalized)) {
        return [];
    }

    $candidate = $normalized[$index];
    return is_array($candidate) ? $candidate : [];
}

function buildHumanReviewPayload(array $previewResult, array $postData, string $responsavelAnalise): array
{
    $topCandidates = is_array($previewResult['top_candidates'] ?? null) ? $previewResult['top_candidates'] : [];
    $selectedIndexRaw = trim((string) ($postData['selected_candidate_index'] ?? '0'));
    $selectedIndex = is_numeric($selectedIndexRaw) ? (int) $selectedIndexRaw : 0;
    if ($selectedIndex < 0) {
        $selectedIndex = 0;
    }

    $selectedCandidate = extractPreviewCandidate($topCandidates, $selectedIndex);
    $decision = normalizeReviewDecision((string) ($postData['review_decision'] ?? $postData['decision'] ?? 'confirmado_manual'));
    $confirmedText = normalizePlateValue((string) ($postData['confirmed_text'] ?? $postData['final_text'] ?? ''));
    $selectedText = normalizePlateValue((string) ($selectedCandidate['text'] ?? $previewResult['best']['text'] ?? ''));
    $notes = trim((string) ($postData['review_notes'] ?? $postData['notes'] ?? ''));
    $previewAnalysisId = trim((string) ($postData['preview_analysis_id'] ?? ($previewResult['forensic']['analysis_id'] ?? $previewResult['report_context']['analysis_id'] ?? '')));

    if ($decision === 'inconclusivo') {
        $confirmedText = '';
    } elseif ($confirmedText === '' && $selectedText !== '') {
        $confirmedText = $selectedText;
    }

    return [
        'status' => 'registrado',
        'source' => 'conferencia_humana',
        'operator' => $responsavelAnalise,
        'responsavel' => $responsavelAnalise,
        'decision' => $decision,
        'decision_label' => humanizePericialLabel($decision),
        'selected_candidate_index' => $selectedIndex,
        'selected_candidate' => $selectedText,
        'selected_candidate_engine' => (string) ($selectedCandidate['engine'] ?? 'ensemble'),
        'selected_candidate_score' => round((float) ($selectedCandidate['score'] ?? 0), 2),
        'selected_candidate_confidence' => round((float) ($selectedCandidate['avg_conf'] ?? 0), 2),
        'selected_candidate_weighted_support' => round((float) ($selectedCandidate['weighted_support'] ?? 0), 2),
        'selected_candidate_support_count' => (int) ($selectedCandidate['support_count'] ?? 0),
        'selected_candidate_agreement_ratio' => round((float) ($selectedCandidate['agreement_ratio'] ?? 0), 1),
        'selected_candidate_region' => (string) ($selectedCandidate['region'] ?? '-'),
        'confirmed_text' => $confirmedText,
        'notes' => $notes,
        'preview_analysis_id' => $previewAnalysisId,
        'reviewed_at_utc' => gmdate('c'),
    ];
}

function persistAnalysisRecord(array $result, string $filename, $db, int $userId): array
{
    $dbWarning = '';
    $savedId = null;

    try {
        $pdo = null;
        try {
            $pdo = DatabaseConnection::create($db);
        } catch (Throwable $databaseException) {
            $dbWarning = 'Banco indisponível no momento; análise será salva no fallback local.';
        }

        $caseController = new CaseController($pdo);
        $savedId = $caseController->saveAnalysis(
            $userId,
            $filename,
            $result,
            $result['pdf_report'] ?? '',
            'web',
            $result['color_info'] ?? [],
            $result['adulteracao'] ?? 0
        );

        $auditPlate = trim((string) ($result['human_review']['confirmed_text'] ?? ''));
        if ($auditPlate === '') {
            $auditPlate = trim((string) ($result['best']['text'] ?? ''));
        }

        AuditLogger::logEvent('analysis_saved', [
            'analysis_row_id' => $savedId,
            'analysis_id' => (string) (($result['forensic']['analysis_id'] ?? '')),
            'user_id' => (int) $userId,
            'filename' => (string) $filename,
            'plate' => (string) $auditPlate,
            'engine' => (string) (($result['best']['engine'] ?? '')),
            'evidence_level' => (string) (($result['assessment']['evidence_level'] ?? 'BAIXA')),
            'manual_review_required' => !empty($result['assessment']['manual_review_required']),
            'consensus_ratio' => (float) (($result['consensus']['agreement_ratio'] ?? 0)),
            'pericial_status' => (string) (($result['pericial']['status'] ?? 'INDEFINIDO')),
            'law_score' => (float) (($result['pericial']['legal_validation']['law_score'] ?? 0)),
            'quality_score' => (float) (($result['pericial']['quality']['score'] ?? 0)),
            'forensic_signature' => (string) (($result['forensic']['signature'] ?? '')),
        ]);
    } catch (Throwable $exception) {
        $dbWarning = 'Análise concluída, mas o registro não foi salvo: ' . $exception->getMessage();
    }

    return [$savedId, $dbWarning];
}

function callOcrApi(array $apiCandidates, string $tmpPath, string $mimeType, string $filename, array $extraFields = []): array
{
    $lastResponse = false;
    $lastError = 'Falha ao conectar na API OCR.';
    $lastStatus = 0;
    $usedUrl = '';

    foreach ($apiCandidates as $baseUrl) {
        for ($attempt = 1; $attempt <= 2; $attempt++) {
            $ch = curl_init($baseUrl . '/process');
            $cfile = new CURLFile($tmpPath, $mimeType ?: 'application/octet-stream', $filename);
            $data = array_merge(['image' => $cfile], $extraFields);

            curl_setopt($ch, CURLOPT_POST, 1);
            curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
            curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 4);
            curl_setopt($ch, CURLOPT_TIMEOUT, 420);
            if (defined('CURL_IPRESOLVE_V4')) {
                curl_setopt($ch, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
            }

            $response = curl_exec($ch);
            $curlError = curl_error($ch);
            $statusCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
            curl_close($ch);

            if ($curlError === '' && $statusCode > 0 && $statusCode < 500) {
                return [$response, '', $statusCode, $baseUrl];
            }

            $lastResponse = $response;
            $lastError = $curlError !== '' ? $curlError : ('HTTP ' . $statusCode);
            $lastStatus = $statusCode;
            $usedUrl = $baseUrl;

            if ($curlError !== '') {
                usleep(250000);
            }
        }
    }

    return [$lastResponse, $lastError, $lastStatus, $usedUrl];
}

function callReportEnrichmentApi(
    array $apiCandidates,
    array $reportContext,
    array $vehicleInfo,
    string $ocrText,
    array $forensic = [],
    array $consensus = [],
    array $assessment = [],
    array $pericial = [],
    array $ocrEngines = [],
    array $ocrEngineStatus = [],
    array $ocrEngineSummary = [],
    array $visualProfile = [],
    array $externalSystemsComparison = [],
    array $humanReview = [],
    array $warnings = []
): array {
    $payload = json_encode([
        'report_context' => $reportContext,
        'vehicle_info' => $vehicleInfo,
        'ocr_text' => $ocrText,
        'origem' => 'web',
        'forensic' => $forensic,
        'consensus' => $consensus,
        'assessment' => $assessment,
        'pericial' => $pericial,
        'ocr_engines' => $ocrEngines,
        'ocr_engine_status' => $ocrEngineStatus,
        'ocr_engine_summary' => $ocrEngineSummary,
        'visual_profile' => $visualProfile,
        'external_systems_comparison' => $externalSystemsComparison,
        'human_review' => $humanReview,
        'warnings' => $warnings,
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);

    if (!is_string($payload) || $payload === '') {
        return [null, 'Falha ao serializar dados de enriquecimento do relatorio.', 0, ''];
    }

    $lastError = 'Falha ao enriquecer o relatorio PDF.';
    $lastStatus = 0;
    $usedUrl = '';
    $lastDecoded = null;

    foreach ($apiCandidates as $baseUrl) {
        $ch = curl_init($baseUrl . '/enrich_report');
        curl_setopt($ch, CURLOPT_POST, 1);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 4);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        if (defined('CURL_IPRESOLVE_V4')) {
            curl_setopt($ch, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
        }

        $response = curl_exec($ch);
        $curlError = curl_error($ch);
        $statusCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        $decoded = is_string($response) ? json_decode($response, true) : null;
        if ($curlError === '' && $statusCode >= 200 && $statusCode < 400 && is_array($decoded) && !isset($decoded['error'])) {
            return [$decoded, '', $statusCode, $baseUrl];
        }

        $lastDecoded = is_array($decoded) ? $decoded : null;
        $lastError = $curlError !== '' ? $curlError : ('HTTP ' . $statusCode);
        if (is_array($decoded) && isset($decoded['error'])) {
            $lastError = (string) $decoded['error'];
        }
        $lastStatus = $statusCode;
        $usedUrl = $baseUrl;
    }

    return [$lastDecoded, $lastError, $lastStatus, $usedUrl];
}

$apiCandidates = buildApiCandidates($pythonApiUrl);

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    if ($finalizeReviewRequested) {
        require_once __DIR__ . '/../app/controllers/CaseController.php';
        require_once __DIR__ . '/../app/models/Case.php';
        require_once __DIR__ . '/../app/services/DatabaseConnection.php';
        require_once __DIR__ . '/../app/services/AuditLogger.php';

        $previewResult = loadPendingPreviewResult();
        if (empty($previewResult)) {
            $errorMessage = 'Não existe pré-análise pendente para finalização.';
        } else {
            $previewAnalysisId = trim((string) ($previewResult['forensic']['analysis_id'] ?? $previewResult['report_context']['analysis_id'] ?? ''));
            $postedPreviewAnalysisId = trim((string) ($_POST['preview_analysis_id'] ?? ''));
            if ($previewAnalysisId !== '' && $postedPreviewAnalysisId !== '' && $previewAnalysisId !== $postedPreviewAnalysisId) {
                $errorMessage = 'A pré-análise informada não corresponde ao rascunho armazenado.';
            } else {
                $result = $previewResult;
                $result['analysis_stage'] = 'preview';
                $result['report_ready'] = false;

                $humanReview = buildHumanReviewPayload($previewResult, $_POST, $responsavelAnalise);
                $result['human_review'] = $humanReview;
                if (!isset($result['report_context']) || !is_array($result['report_context'])) {
                    $result['report_context'] = [];
                }
                $result['report_context']['human_review'] = $humanReview;
                $result['report_context']['analysis_stage'] = 'preview';
                if (!isset($result['input_meta']) || !is_array($result['input_meta'])) {
                    $result['input_meta'] = [];
                }
                $result['input_meta']['human_review'] = $humanReview;

                $finalText = trim((string) ($humanReview['confirmed_text'] ?? ''));
                if (($humanReview['decision'] ?? '') === 'inconclusivo') {
                    $finalText = '';
                } elseif ($finalText === '') {
                    $finalText = trim((string) ($result['best']['text'] ?? ''));
                }

                $veiculo = is_array($result['vehicle_info'] ?? null) ? $result['vehicle_info'] : $veiculo;
                $veiculoExibicao = buildVehicleDisplayInfo(is_array($veiculo) ? $veiculo : []);
                $officialVehicleValidation = buildOfficialVehicleValidationSummary(is_array($veiculo) ? $veiculo : []);
                $analysisWarnings = is_array($result['warnings'] ?? null) ? $result['warnings'] : [];

                [$enriched, $enrichError, $enrichStatus, $enrichApiUrl] = callReportEnrichmentApi(
                    $apiCandidates,
                    $result['report_context'],
                    $veiculoExibicao ?: [],
                    $finalText,
                    is_array($result['forensic'] ?? null) ? $result['forensic'] : [],
                    is_array($result['consensus'] ?? null) ? $result['consensus'] : [],
                    is_array($result['assessment'] ?? null) ? $result['assessment'] : [],
                    is_array($result['pericial'] ?? null) ? $result['pericial'] : [],
                    is_array($result['ocr'] ?? null) ? $result['ocr'] : [],
                    is_array($result['ocr_engine_status'] ?? null) ? $result['ocr_engine_status'] : [],
                    is_array($result['ocr_engine_summary'] ?? null) ? $result['ocr_engine_summary'] : [],
                    is_array($result['visual_profile'] ?? null) ? $result['visual_profile'] : [],
                    is_array($result['external_systems_comparison'] ?? null) ? $result['external_systems_comparison'] : [],
                    $humanReview,
                    $analysisWarnings
                );

                $enrichmentSucceeded = false;
                if ($enrichError === '' && is_array($enriched) && !empty($enriched['pdf_report'])) {
                    $result['pdf_report'] = (string) $enriched['pdf_report'];
                    $enrichmentSucceeded = true;
                } else {
                    if (!isset($result['warnings']) || !is_array($result['warnings'])) {
                        $result['warnings'] = [];
                    }
                    $warningText = 'Falha ao atualizar relatorio PDF pericial: ' . $enrichError;
                    if ($enrichApiUrl !== '') {
                        $warningText .= ' (API: ' . $enrichApiUrl . ')';
                    }
                    if ($enrichStatus >= 400) {
                        $warningText .= ' [HTTP ' . $enrichStatus . ']';
                    }
                    $result['warnings'][] = $warningText;
                }

                $filename = (string) ($previewResult['input_meta']['source_filename'] ?? $previewResult['report_context']['photo_filename'] ?? $previewResult['forensic']['source_filename'] ?? 'analise_finalizada');
                if ($filename === '') {
                    $filename = 'analise_finalizada';
                }

                if ($enrichmentSucceeded) {
                    $result['human_review'] = $humanReview;
                    $result['report_context']['human_review'] = $humanReview;
                    $result['report_context']['analysis_stage'] = 'final';
                    $result['analysis_stage'] = 'final';
                    $result['report_ready'] = true;
                    [$savedId, $dbWarning] = persistAnalysisRecord($result, $filename, $db, (int) $_SESSION['user_id']);
                    clearPendingPreviewResult();
                } else {
                    if ($errorMessage === null || trim((string) $errorMessage) === '') {
                        $errorMessage = 'Não foi possível gerar o relatório final. A pré-análise permanece disponível para nova tentativa.';
                    }
                }
            }
        }
    } elseif (!isset($_FILES['image']) || $_FILES['image']['error'] !== UPLOAD_ERR_OK) {
        $errorMessage = 'Não foi possível receber a imagem enviada.';
    } else {
        require_once __DIR__ . '/../app/controllers/CaseController.php';
        require_once __DIR__ . '/../app/models/Case.php';
        require_once __DIR__ . '/../app/services/DatabaseConnection.php';
        require_once __DIR__ . '/../app/services/AuditLogger.php';

        $file = $_FILES['image'];
        $uploadSecurity = buildUploadSecuritySummary($file);
        if (empty($uploadSecurity['allowed'])) {
            $errorMessage = 'Arquivo rejeitado: ' . (string) ($uploadSecurity['error'] ?? 'nao suportado');
            if (!empty($uploadSecurity['extension'])) {
                $errorMessage .= ' | Extensao: ' . strtoupper(ltrim((string) $uploadSecurity['extension'], '.'));
            }
            if (!empty($uploadSecurity['detected_signature'])) {
                $errorMessage .= ' | Assinatura: ' . (string) $uploadSecurity['detected_signature'];
            }
            if (!empty($uploadSecurity['max_upload_mb'])) {
                $errorMessage .= ' | Limite: ' . number_format((float) $uploadSecurity['max_upload_mb'], 0, ',', '.') . ' MB';
            }
        } else {
            $tmpPath = $file['tmp_name'];
            $filename = basename($file['name']);
            $apiCandidates = buildApiCandidates($pythonApiUrl);
            [$response, $curlError, $statusCode, $usedApiUrl] = callOcrApi(
                $apiCandidates,
                $tmpPath,
                (string) ($file['type'] ?? ''),
                $filename,
                ['analysis_stage' => 'preview']
            );

            if ($curlError !== '') {
                $errorMessage = 'Erro ao processar imagem: ' . $curlError;
                if ($usedApiUrl !== '') {
                    $errorMessage .= ' (API: ' . $usedApiUrl . ')';
                }
                if (
                    stripos($curlError, 'Could not connect') !== false
                    || stripos($curlError, 'Failed to connect') !== false
                ) {
                    $errorMessage .= ' | API OCR offline. Execute: C:\\Grom_OCR\\tools\\start_grom_ocr.cmd';
                }
            } elseif ($statusCode >= 400) {
                $errorMessage = 'Servico OCR retornou HTTP ' . $statusCode . '.';
                if ($usedApiUrl !== '') {
                    $errorMessage .= ' (API: ' . $usedApiUrl . ')';
                }
            } else {
                $decoded = json_decode($response, true);
                if (!is_array($decoded)) {
                    $errorMessage = 'Servico OCR retornou uma resposta invalida.';
                } elseif (isset($decoded['error'])) {
                    $errorMessage = 'Servico OCR: ' . $decoded['error'];
                } else {
                    $result = $decoded;
                    if ($usedApiUrl !== '') {
                        $result['api_url_used'] = (string) $usedApiUrl;
                    }
                    if (!isset($result['pericial']) || !is_array($result['pericial'])) {
                        $result['pericial'] = [];
                    }
                    if (!isset($result['pericial']['cross_checks']) || !is_array($result['pericial']['cross_checks'])) {
                        $result['pericial']['cross_checks'] = [];
                    }
                    if (!isset($result['report_context']) || !is_array($result['report_context'])) {
                        $result['report_context'] = [];
                    }
                    $result['report_context']['responsavel'] = $responsavelAnalise;
                    if (!isset($result['report_context']['cargo_funcao']) || trim((string) $result['report_context']['cargo_funcao']) === '') {
                        $result['report_context']['cargo_funcao'] = 'Perícia / análise técnica';
                    }
                    if (!isset($result['input_meta']) || !is_array($result['input_meta'])) {
                        $result['input_meta'] = [];
                    }
                    $result['input_meta']['responsavel'] = $responsavelAnalise;

                    if (isset($result['best']['text'])) {
                        $ocrPlate = normalizePlateValue((string) ($result['best']['text'] ?? ''));

                        try {
                            $historyPdo = null;
                            try {
                                $historyPdo = DatabaseConnection::create($db);
                            } catch (Throwable $historyDbException) {
                                // fallback silencioso para pesquisa local
                            }
                            $historyModel = new CaseModel($historyPdo);
                            $historyMatches = $historyModel->findByPlate($_SESSION['user_id'], $ocrPlate, 20);
                            $result['pericial']['cross_checks']['local_history'] = buildLocalHistoryCrossCheck($historyMatches);
                        } catch (Throwable $historyException) {
                            $result['pericial']['cross_checks']['local_history'] = [
                                'status' => 'erro',
                                'message' => $historyException->getMessage(),
                                'previous_occurrences' => 0,
                            ];
                        }

                        require_once __DIR__ . '/../app/services/ExternalVehicleLookup.php';
                        $veiculo = ExternalVehicleLookup::searchByPlate($result['best']['text']);
                        $consultaStatusLookup = strtolower(trim((string) ($veiculo['consulta_status'] ?? '')));
                        $needsVisualFallback = !$veiculo
                            || in_array($consultaStatusLookup, ['pending_async', 'pendente_webhook', 'aguardando_webhook'], true)
                            || trim((string) ($veiculo['fabricante'] ?? '')) === ''
                            || trim((string) ($veiculo['modelo'] ?? '')) === '';
                        if ($needsVisualFallback) {
                            $fallbackVehicle = buildOpenSourceVisualVehicleFallback($result);
                            if ($fallbackVehicle) {
                                $veiculo = array_replace($fallbackVehicle, is_array($veiculo) ? $veiculo : []);
                            }
                        }
                        if ($veiculo) {
                            $result['vehicle_info'] = $veiculo;
                        }

                        $veiculoExibicao = buildVehicleDisplayInfo($veiculo);
                        $officialVehicleValidation = buildOfficialVehicleValidationSummary($veiculo);

                        if ($veiculo) {
                            $externalPlate = normalizePlateValue((string) ($veiculo['placa'] ?? ''));
                            $plateMatch = ($externalPlate !== '' && $ocrPlate !== '' && $externalPlate === $ocrPlate);
                            $sourceParts = [];
                            $primarySource = trim((string) ($veiculo['fonte'] ?? ''));
                            $complementarySource = trim((string) ($veiculo['fonte_complementar'] ?? ''));
                            if ($primarySource !== '') {
                                $sourceParts[] = $primarySource;
                            }
                            if ($complementarySource !== '') {
                                $sourceParts[] = $complementarySource;
                            }
                            $sourceText = !empty($sourceParts) ? implode(' | ', $sourceParts) : 'provedor_externo';
                            $officialStatus = (string) ($officialVehicleValidation['status'] ?? 'indefinido');
                            $result['pericial']['cross_checks']['external_source'] = [
                                'status' => in_array($consultaStatusLookup, ['pending_async', 'pendente_webhook', 'aguardando_webhook'], true)
                                    ? 'pendente_webhook_usezapay'
                                    : ($officialStatus !== 'nao_disponivel' ? $officialStatus : ((strpos((string) ($veiculo['fonte'] ?? ''), 'analise_visual_local_heuristica') !== false) ? 'estimado_fontes_abertas' : 'ok')),
                                'source' => $sourceText,
                                'source_primary' => $primarySource !== '' ? $primarySource : 'provedor_externo',
                                'source_complementary' => $complementarySource !== '' ? $complementarySource : null,
                                'source_kind' => (string) ($officialVehicleValidation['source_kind'] ?? 'indefinido'),
                                'source_label' => (string) ($officialVehicleValidation['source_label'] ?? 'indefinida'),
                                'official' => (bool) ($officialVehicleValidation['is_official'] ?? false),
                                'plate_returned' => $externalPlate,
                                'matches_ocr' => $externalPlate !== '' ? $plateMatch : null,
                                'sensitive_fields_found' => $officialVehicleValidation['sensitive_fields_found'] ?? [],
                                'multifonte_status' => (string) ($veiculoExibicao['consulta_multifonte_status'] ?? '-'),
                                'multifonte_candidatos' => (int) ($veiculoExibicao['consulta_multifonte_candidatos'] ?? 0),
                                'multifonte_confianca' => (string) ($veiculoExibicao['consulta_multifonte_confianca'] ?? '0.0'),
                                'multifonte_taxa_consenso' => (string) ($veiculoExibicao['consulta_multifonte_taxa_consenso'] ?? '0.0'),
                                'multifonte_score' => (string) ($veiculoExibicao['consulta_multifonte_score'] ?? '0.0'),
                                'multifonte_limite' => (int) ($veiculoExibicao['consulta_multifonte_limite'] ?? 0),
                                'multifonte_limite_aplicado' => (string) ($veiculoExibicao['consulta_multifonte_limite_aplicado'] ?? 'Não'),
                                'multifonte_consenso' => (string) ($veiculoExibicao['consulta_multifonte_consenso'] ?? '-'),
                                'multifonte_divergencias' => (string) ($veiculoExibicao['consulta_multifonte_divergencias'] ?? '-'),
                                'multifonte_resumo' => (string) ($veiculoExibicao['consulta_multifonte_resumo'] ?? '-'),
                                'multifonte_alertas' => (string) ($veiculoExibicao['consulta_multifonte_alertas'] ?? '-'),
                            ];
                            $result['pericial']['cross_checks']['official_vehicle_validation'] = $officialVehicleValidation;
                            if (!$plateMatch && $externalPlate !== '') {
                                if (!isset($result['warnings']) || !is_array($result['warnings'])) {
                                    $result['warnings'] = [];
                                }
                                $result['warnings'][] = 'inconsistencia_placa_fonte_externa';
                            }
                        } else {
                            $result['pericial']['cross_checks']['external_source'] = [
                                'status' => $vehicleLookupConfigured ? 'sem_retorno' : 'nao_configurado',
                                'source' => $vehicleLookupConfigured ? 'provedor_externo_ou_fontes_abertas' : 'nenhum',
                                'matches_ocr' => null,
                                'multifonte_status' => $vehicleLookupConfigured ? 'sem_retorno' : 'nao_configurado',
                                'multifonte_candidatos' => 0,
                                'multifonte_confianca' => '0.0',
                                'multifonte_taxa_consenso' => '0.0',
                                'multifonte_score' => '0.0',
                                'multifonte_limite' => 0,
                                'multifonte_limite_aplicado' => 'Não',
                                'multifonte_consenso' => '-',
                                'multifonte_divergencias' => '-',
                                'multifonte_resumo' => 'Consulta veicular não disponível nesta tentativa.',
                                'multifonte_alertas' => $vehicleLookupConfigured ? 'sem_retorno_do_provedor' : 'integracao_desativada',
                            ];
                            $result['pericial']['cross_checks']['official_vehicle_validation'] = [
                                'status' => 'nao_disponivel',
                            ];
                        }

                        if (isset($result['report_context']) && is_array($result['report_context'])) {
                            [$enriched, $enrichError, $enrichStatus, $enrichApiUrl] = callReportEnrichmentApi(
                                $apiCandidates,
                                $result['report_context'],
                                $veiculoExibicao ?: [],
                                (string) ($result['best']['text'] ?? ''),
                                is_array($result['forensic'] ?? null) ? $result['forensic'] : [],
                                is_array($result['consensus'] ?? null) ? $result['consensus'] : [],
                                is_array($result['assessment'] ?? null) ? $result['assessment'] : [],
                                is_array($result['pericial'] ?? null) ? $result['pericial'] : [],
                                is_array($result['ocr'] ?? null) ? $result['ocr'] : [],
                                is_array($result['ocr_engine_status'] ?? null) ? $result['ocr_engine_status'] : [],
                                is_array($result['ocr_engine_summary'] ?? null) ? $result['ocr_engine_summary'] : [],
                                is_array($result['visual_profile'] ?? null) ? $result['visual_profile'] : [],
                                is_array($result['external_systems_comparison'] ?? null) ? $result['external_systems_comparison'] : [],
                                is_array($result['human_review'] ?? null) ? $result['human_review'] : [],
                                is_array($result['warnings'] ?? null) ? $result['warnings'] : []
                            );

                            if ($enrichError === '' && is_array($enriched)) {
                                if (!empty($enriched['pdf_report'])) {
                                    $result['pdf_report'] = (string) $enriched['pdf_report'];
                                }
                            } else {
                                if (!isset($result['warnings']) || !is_array($result['warnings'])) {
                                    $result['warnings'] = [];
                                }
                                $warningText = 'Falha ao atualizar relatorio PDF pericial: ' . $enrichError;
                                if ($enrichApiUrl !== '') {
                                    $warningText .= ' (API: ' . $enrichApiUrl . ')';
                                }
                                if ($enrichStatus >= 400) {
                                    $warningText .= ' [HTTP ' . $enrichStatus . ']';
                                }
                                $result['warnings'][] = $warningText;
                            }
                        }
                    }

                    if ($analysisPreviewRequested) {
                        $result['analysis_stage'] = 'preview';
                        $result['report_ready'] = !empty($result['pdf_report']);
                        storePendingPreviewResult($result);
                    } else {
                        [$savedId, $dbWarning] = persistAnalysisRecord($result, $filename, $db, (int) $_SESSION['user_id']);
                    }
                }
            }
        }
    }
}
?>
<!DOCTYPE html>
<html lang="pt-br">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nova Análise - Grom_OCR</title>
    <link rel="stylesheet" href="/assets/app.css">
    <link rel="icon" type="image/png" href="/assets/grom-favicon.png">
</head>

<body>
    <?php
    $best = is_array($result) ? ($result['best'] ?? null) : null;
    $ocrEngines = is_array($result) && isset($result['ocr']) && is_array($result['ocr']) ? $result['ocr'] : [];
    $topCandidates = is_array($result) && isset($result['top_candidates']) && is_array($result['top_candidates']) ? $result['top_candidates'] : [];
    $charOptions = is_array($result) && isset($result['char_options']) && is_array($result['char_options']) ? $result['char_options'] : [];
    $regionsTested = is_array($result) && isset($result['regions_tested']) && is_array($result['regions_tested']) ? $result['regions_tested'] : [];
    $analysisStage = is_array($result) ? strtolower((string) ($result['analysis_stage'] ?? '')) : '';
    $analysisStageLabel = $analysisStage === 'preview'
        ? 'Pré-análise técnico-pericial'
        : ($analysisStage === 'final'
            ? 'Resultado final'
            : (!empty($result['human_review']) ? 'Conferência técnico-pericial' : 'Análise técnico-pericial'));
    $humanReview = is_array($result) && isset($result['human_review']) && is_array($result['human_review']) ? $result['human_review'] : [];
    $warningsList = is_array($result) && isset($result['warnings']) && is_array($result['warnings']) ? $result['warnings'] : [];
    $forensic = is_array($result) && isset($result['forensic']) && is_array($result['forensic']) ? $result['forensic'] : [];
    $consensus = is_array($result) && isset($result['consensus']) && is_array($result['consensus']) ? $result['consensus'] : [];
    $assessment = is_array($result) && isset($result['assessment']) && is_array($result['assessment']) ? $result['assessment'] : [];
    $pericial = is_array($result) && isset($result['pericial']) && is_array($result['pericial']) ? $result['pericial'] : [];
    $operationalProtocol = is_array($pericial['operational_protocol'] ?? null)
        ? $pericial['operational_protocol']
        : (is_array($result['operational_protocol'] ?? null) ? $result['operational_protocol'] : []);
    $vehicleConfrontationForm = is_array($pericial['vehicle_confrontation_form'] ?? null)
        ? $pericial['vehicle_confrontation_form']
        : (is_array($result['vehicle_confrontation_form'] ?? null) ? $result['vehicle_confrontation_form'] : []);
    $visualProfile = is_array($result) && isset($result['visual_profile']) && is_array($result['visual_profile']) ? $result['visual_profile'] : [];
    $assistedVehicleIdentification = is_array($result) && isset($result['assisted_vehicle_identification']) && is_array($result['assisted_vehicle_identification'])
        ? $result['assisted_vehicle_identification']
        : [];
    $platePatternLabel = is_array($result) ? extractPlatePatternLabel($result) : 'Indefinido';
    $externalSystemsComparison = is_array($result) && isset($result['external_systems_comparison']) && is_array($result['external_systems_comparison']) ? $result['external_systems_comparison'] : [];
    $externalSystemsSummary = is_array($externalSystemsComparison['sumario'] ?? null) ? $externalSystemsComparison['sumario'] : [];
    $externalSystemsRuns = is_array($externalSystemsComparison['execucoes'] ?? null) ? $externalSystemsComparison['execucoes'] : [];
    $externalSystemsCatalog = is_array($externalSystemsComparison['catalogo'] ?? null) ? $externalSystemsComparison['catalogo'] : [];
    $ocrEngineStatus = is_array($result) && isset($result['ocr_engine_status']) && is_array($result['ocr_engine_status']) ? $result['ocr_engine_status'] : [];
    $ocrEngineSummary = is_array($result) && isset($result['ocr_engine_summary']) && is_array($result['ocr_engine_summary']) ? $result['ocr_engine_summary'] : [];
    $engineRuntime = is_array($result) && isset($result['engine_runtime']) && is_array($result['engine_runtime']) ? $result['engine_runtime'] : [];
    $veiculoExibicao = buildVehicleDisplayInfo(is_array($veiculo) ? $veiculo : []);
    $officialVehicleValidation = buildOfficialVehicleValidationSummary(is_array($veiculo) ? $veiculo : []);
    $zapayLookupStatus = strtolower(trim((string) ($veiculoExibicao['consulta_status'] ?? $veiculo['consulta_status'] ?? $officialVehicleValidation['status'] ?? '')));
    $zapayLookupEvent = trim((string) ($veiculoExibicao['consulta_evento'] ?? $veiculo['consulta_evento'] ?? ''));
    $zapayLookupRequestId = trim((string) ($veiculoExibicao['consulta_request_id'] ?? $veiculo['consulta_request_id'] ?? ''));
    $zapayLookupPlate = trim((string) ($veiculoExibicao['placa'] ?? $officialVehicleValidation['lookup_plate'] ?? ''));
    $zapayLookupDetail = trim((string) ($veiculoExibicao['consulta_detalhe'] ?? $veiculo['consulta_detalhe'] ?? ''));
    $zapayLookupSummaryStatus = trim((string) ($veiculoExibicao['consulta_multifonte_status'] ?? ''));
    $zapayLookupSummaryText = trim((string) ($veiculoExibicao['consulta_multifonte_resumo'] ?? ''));
    $zapayLookupHistoryCount = (int) (is_array($veiculo['history'] ?? null) ? count($veiculo['history']) : 0);
    $zapayLookupShouldShow = $zapayLookupRequestId !== ''
        || $zapayLookupPlate !== ''
        || in_array($zapayLookupStatus, ['pending_async', 'pendente_webhook', 'aguardando_webhook', 'resultado_cache'], true)
        || strpos(strtolower((string) ($veiculoExibicao['fonte'] ?? '')), 'zapay') !== false;
    $zapayLookupPending = in_array($zapayLookupStatus, ['pending_async', 'pendente_webhook', 'aguardando_webhook'], true)
        || $officialVehicleValidation['status'] === 'pendente_webhook';
    $zapayLookupStateLabel = 'Indefinido';
    $zapayLookupStateClass = 'status-chip--neutral';
    if ($zapayLookupPending) {
        $zapayLookupStateLabel = 'Pendente';
        $zapayLookupStateClass = 'status-chip--pending';
    } elseif (in_array($zapayLookupStatus, ['resultado_cache', 'cache_hit', 'ok', 'vehicle_debt_found', 'concluido'], true)) {
        $zapayLookupStateLabel = 'Concluido';
        $zapayLookupStateClass = 'status-chip--ok';
    } elseif (in_array($zapayLookupStatus, ['sem_retorno', 'nao_disponivel', 'not_found', 'vehicle_not_found', 'vehicle_debt_not_found'], true)) {
        $zapayLookupStateLabel = 'Sem retorno';
        $zapayLookupStateClass = 'status-chip--warning';
    } elseif ($zapayLookupStatus === '') {
        if ($useZapayConfigured) {
            $zapayLookupStateLabel = 'Aguardando';
            $zapayLookupStateClass = 'status-chip--pending';
        } else {
            $zapayLookupStateLabel = 'Não configurado';
            $zapayLookupStateClass = 'status-chip--neutral';
        }
    } elseif ($zapayLookupStatus !== '') {
        $zapayLookupStateLabel = ucfirst(str_replace('_', ' ', $zapayLookupStatus));
        $zapayLookupStateClass = 'status-chip--neutral';
    }
    $zapayTopbarDetail = '';
    if ($zapayLookupShouldShow) {
        $details = [];
        if ($zapayLookupPlate !== '') {
            $details[] = 'Placa ' . $zapayLookupPlate;
        }
        if ($zapayLookupRequestId !== '') {
            $details[] = 'Request ' . $zapayLookupRequestId;
        }
        if ($zapayLookupSummaryText !== '') {
            $details[] = $zapayLookupSummaryText;
        } elseif ($zapayLookupDetail !== '') {
            $details[] = $zapayLookupDetail;
        }
        $zapayTopbarDetail = !empty($details) ? implode(' | ', $details) : 'Monitoramento Zapay ativo.';
    } elseif ($useZapayConfigured) {
        $zapayTopbarDetail = 'Monitoramento Zapay ativo e aguardando a primeira consulta.';
    } else {
        $zapayTopbarDetail = 'Monitoramento Zapay desativado.';
    }
    $engineRuntimeWarnings = [];
    foreach ($engineRuntime as $engineName => $runtimeData) {
        if (!is_array($runtimeData)) {
            continue;
        }
        $runtimeError = trim((string) ($runtimeData['error'] ?? ''));
        if ($runtimeError === '') {
            continue;
        }
        $engineLabel = ucwords(str_replace('_', ' ', (string) $engineName));
        $engineRuntimeWarnings[] = $engineLabel . ': ' . $runtimeError;
    }
    $inputMeta = is_array($result) && isset($result['input_meta']) && is_array($result['input_meta']) ? $result['input_meta'] : [];
    $scenePreprocess = is_array($inputMeta['scene_preprocess'] ?? null) ? $inputMeta['scene_preprocess'] : [];
    $sceneProfile = is_array($scenePreprocess['scene_profile'] ?? null) ? $scenePreprocess['scene_profile'] : [];
    $scenePreBefore = is_array($scenePreprocess['quality_before'] ?? null) ? $scenePreprocess['quality_before'] : [];
    $scenePreAfter = is_array($scenePreprocess['quality_after'] ?? null) ? $scenePreprocess['quality_after'] : [];
    $inputSecurity = is_array($inputMeta['input_security'] ?? null) ? $inputMeta['input_security'] : [];
    $plateDetection = is_array($inputMeta['plate_detection'] ?? null) ? $inputMeta['plate_detection'] : [];
    $captureIntegrity = is_array($pericial['capture_integrity'] ?? null)
        ? $pericial['capture_integrity']
        : (is_array($result['capture_integrity'] ?? null) ? $result['capture_integrity'] : []);
    $manifestUrl = trim((string) ($result['manifest_url'] ?? $result['evidence_manifest_url'] ?? ''));
    $previewAnalysisId = trim((string) ($forensic['analysis_id'] ?? ($result['report_context']['analysis_id'] ?? '')));
    $reviewDefaultCandidate = is_array($topCandidates[0] ?? null) ? $topCandidates[0] : (is_array($best) ? $best : []);
    $reviewDefaultText = normalizePlateValue((string) ($reviewDefaultCandidate['text'] ?? ($best['text'] ?? '')));
    $finalReportReady = is_array($result) && !empty($result['pdf_report']);
    $analysisReportTopics = [
        'Identificação da captura',
        'Tratamento técnico da imagem',
        'OCR, consenso e ambiguidade',
        'Correção e conferência humana',
        'Conclusão',
    ];
    $analysisReportOutline = is_array($result['analysis_report_outline'] ?? null) ? $result['analysis_report_outline'] : [
        [
            'number' => '1',
            'title' => 'Identificação da captura',
            'summary' => 'Apresenta a imagem original, o recorte bruto, o recorte tratado, a cadeia de custódia digital, a integridade de entrada, os metadados e a descrição técnica da cena.',
            'subitems' => [
                [
                    'number' => '1.1',
                    'title' => 'Imagem original, recorte bruto e recorte tratado',
                    'summary' => 'Exibe a fonte documental em escala reduzida, o recorte bruto extraído e o recorte tratado, com comparação visual para conferência pericial.',
                ],
                [
                    'number' => '1.2',
                    'title' => 'Cadeia de custódia digital',
                    'summary' => 'Registra origem, preservação, encadeamento da prova digital e rastreabilidade da análise.',
                ],
                [
                    'number' => '1.3',
                    'title' => 'Integridade de entrada',
                    'summary' => 'Confere assinatura, formato, consistência do arquivo e alertas de segurança na entrada.',
                ],
                [
                    'number' => '1.4',
                    'title' => 'Metadados da imagem',
                    'summary' => 'Resume EXIF, resolução, data, dispositivo de captura e parâmetros técnicos disponíveis.',
                ],
                [
                    'number' => '1.5',
                    'title' => 'Descrição técnica da imagem',
                    'summary' => 'Descreve o contexto visual observado, como baixa luminosidade, excesso de luz, chuva, cena externa ou outras condições relevantes.',
                ],
            ],
        ],
        [
            'number' => '2',
            'title' => 'Tratamento técnico da imagem',
            'summary' => 'Explica o modelo de tratamento, os procedimentos de pré-processamento, a calibração aplicada e os refinamentos usados para maximizar repetibilidade e acurácia.',
            'subitems' => [
                [
                    'number' => '2.1',
                    'title' => 'Modelo e estratégia de tratamento',
                    'summary' => 'Descreve a família de software, a estratégia de seleção do ROI e a linha pericial adotada para preservar a evidência.',
                ],
                [
                    'number' => '2.2',
                    'title' => 'Pré-processamento e recorte',
                    'summary' => 'Documenta equalização, contraste, nitidez, alinhamento e demais ajustes visuais utilizados.',
                ],
                [
                    'number' => '2.3',
                    'title' => 'Calibração e parâmetros técnicos',
                    'summary' => 'Registra versões, parâmetros e critérios empregados no tratamento automatizado.',
                ],
            ],
        ],
        [
            'number' => '3',
            'title' => 'OCR, consenso e ambiguidade',
            'summary' => 'Consolida os motores utilizados, as probabilidades de acerto, os percentuais apresentados e os pontos de ambiguidade entre leituras.',
            'subitems' => [
                [
                    'number' => '3.1',
                    'title' => 'Motores empregados',
                    'summary' => 'Lista os motores OCR acionados e o papel de cada um no ensemble.',
                ],
                [
                    'number' => '3.2',
                    'title' => 'Percentuais e confiança',
                    'summary' => 'Resume as pontuações, confidências e índices de concordância obtidos.',
                ],
                [
                    'number' => '3.3',
                    'title' => 'Ambiguidades e hipótese aceita',
                    'summary' => 'Expõe leituras conflitantes e a hipótese final escolhida pelo consenso.',
                ],
            ],
        ],
        [
            'number' => '4',
            'title' => 'Correção e conferência humana',
            'summary' => 'Registra correções eventuais e a conferência humana obrigatória antes da consolidação final.',
            'subitems' => [
                [
                    'number' => '4.1',
                    'title' => 'Revisão das hipóteses',
                    'summary' => 'Aponta se houve ajuste manual na leitura e quais hipóteses foram confrontadas.',
                ],
                [
                    'number' => '4.2',
                    'title' => 'Conferência humana obrigatória',
                    'summary' => 'Declara a conferência humana como etapa de validação antes da aprovação do relatório.',
                ],
                [
                    'number' => '4.3',
                    'title' => 'Aprovação final',
                    'summary' => 'Indica se o resultado foi consolidado para impressão documental ou mantido em correção em tela.',
                ],
            ],
        ],
        [
            'number' => '5',
            'title' => 'Conclusão',
            'summary' => 'Fecha o documento com síntese técnica, em linguagem clara e credível, sobre as tecnologias usadas no tratamento, na captura da tela e no processamento da imagem.',
            'subitems' => [
                [
                    'number' => '5.1',
                    'title' => 'Síntese documental',
                    'summary' => 'Resume o caminho percorrido entre a fonte, o tratamento, o OCR e a validação humana.',
                ],
                [
                    'number' => '5.2',
                    'title' => 'Resultado consolidado',
                    'summary' => 'Apresenta o resultado final com o nível de confiabilidade alcançado.',
                ],
                [
                    'number' => '5.3',
                    'title' => 'Observações finais',
                    'summary' => 'Mantém o tom técnico, mas acessível, para leitura por operadores e interessados leigos.',
                ],
            ],
        ],
    ];
    $analysisReportOverview = [];
    if (is_array($result)) {
        $analysisReportOverview = [
            'title' => 'Relatório de apoio à investigação',
            'subtitle' => $analysisStage === 'preview'
                ? 'Pré-análise automática apresentada em tela para correção antes da consolidação documental.'
                : 'Relatório consolidado e pronto para impressão documental.',
            'status_label' => $analysisStage === 'preview' ? 'Pré-análise' : 'Consolidado',
            'status_class' => $analysisStage === 'preview' ? 'status-chip--pending' : 'status-chip--ok',
            'analysis_id' => trim((string) ($forensic['analysis_id'] ?? ($result['report_context']['analysis_id'] ?? '-'))) ?: '-',
            'analysis_stage' => $analysisStageLabel,
            'plate_text' => trim((string) (($humanReview['confirmed_text'] ?? '') ?: ($best['text'] ?? ''))) ?: '-',
            'plate_pattern' => $platePatternLabel,
            'capture_status' => humanizePericialLabel($captureIntegrity['status'] ?? 'indefinido'),
            'capture_score' => number_format((float) ($captureIntegrity['integrity_score'] ?? 0), 1, ',', '.'),
            'consensus' => number_format((float) ($consensus['agreement_ratio'] ?? 0), 1, ',', '.'),
            'consensus_count' => (int) ($consensus['agreement_count'] ?? 0),
            'engines_considered' => (int) ($consensus['engines_considered'] ?? 0),
            'review_status' => !empty($humanReview)
                ? humanizePericialLabel($humanReview['decision_label'] ?? $humanReview['decision'] ?? 'registrado')
                : 'Pendente',
            'document_state' => $finalReportReady ? 'Disponível para impressão documental' : 'Aguardando correção em tela',
            'document_hint' => $finalReportReady
                ? 'O PDF consolidado já pode ser aberto para arquivamento e impressão.'
                : 'Corrija a leitura e finalize a conferência para liberar o documento final.',
        ];
    }
    ?>

    <main class="page-shell">
        <header class="topbar">
            <div class="brand">
                <div class="brand-mark">
                    <img src="/assets/grom-report-logo.png" alt="Grom OCR">
                </div>
                <div>
                    <h1 class="brand-title">Nova Análise OCR</h1>
                    <p class="brand-subtitle">Apoio técnico à investigação, OCR e validação documental</p>
                    <div class="analysis-topbar-status">
                        <div id="analysisTopStatusChip" class="status-chip <?php echo htmlspecialchars($zapayLookupStateClass); ?> status-chip--compact">
                            <?php echo htmlspecialchars($zapayLookupStateLabel); ?>
                        </div>
                        <p id="analysisTopStatusText" class="analysis-topbar-status-text"><?php echo htmlspecialchars($zapayTopbarDetail); ?></p>
                    </div>
                    <div class="analysis-topbar-identity">
                        <span class="analysis-topbar-identity-label">Operador</span>
                        <strong class="analysis-topbar-identity-value"><?php echo htmlspecialchars($operatorLabel); ?></strong>
                    </div>
                </div>
            </div>
            <nav class="nav-links">
                <a class="nav-link" href="/">Dashboard</a>
                <a class="nav-link active" href="/upload.php">Nova análise</a>
                <a class="nav-link" href="/video.php">Vídeo</a>
                <a class="nav-link" href="/historico.php">Histórico</a>
                <a class="nav-link" href="/logout.php">Sair</a>
            </nav>
        </header>

        <section class="card no-print analysis-intake-card">
            <div class="analysis-intake-panel">
                <div class="analysis-intake-copy">
                    <p class="analysis-report-eyebrow">Entrada documental</p>
                    <h2 class="analysis-intake-title">Enviar imagem para análise</h2>
                    <p class="analysis-intake-text">
                        A imagem-fonte é preservada, o recorte bruto é documentado e o recorte tratado é comparado antes da conferência humana e da consolidação documental.
                    </p>
                    <ul class="analysis-intake-points">
                        <li>Fonte original preservada para comparação pericial.</li>
                        <li>Recorte bruto e recorte tratado disponíveis na mesma leitura.</li>
                        <li>OCR com consenso, ambiguidade e revisão humana obrigatória.</li>
                    </ul>
                    <div class="analysis-intake-steps" aria-label="Fluxo de análise">
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">01</span>
                            <div>
                                <strong>Preservação</strong>
                                <p>Imagem original e integridade documental.</p>
                            </div>
                        </article>
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">02</span>
                            <div>
                                <strong>Tratamento</strong>
                                <p>Recorte bruto, recorte tratado e comparação visual.</p>
                            </div>
                        </article>
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">03</span>
                            <div>
                                <strong>Conferência</strong>
                                <p>Consenso OCR e revisão humana antes da impressão.</p>
                            </div>
                        </article>
                    </div>
                    <p class="analysis-intake-note">
                        O sistema aplica correção automática de contraste e brilho para aumentar a consistência sem sacrificar a prova original.
                    </p>
                </div>

                <div class="analysis-upload-panel">
                    <div class="analysis-upload-header">
                        <div class="analysis-upload-header-copy">
                            <p class="analysis-report-eyebrow">Arquivo de entrada</p>
                            <h3 class="card-title">Selecionar imagem-fonte</h3>
                            <p class="analysis-upload-header-note">A imagem original segue para preservação, comparação e conferência humana antes da emissão documental.</p>
                        </div>
                        <span class="status-chip status-chip--neutral status-chip--compact">Pré-análise</span>
                    </div>

                    <form id="ocrUploadForm" method="POST" enctype="multipart/form-data">
                        <input type="hidden" name="analysis_stage" value="preview">
                        <label class="field" for="image">
                            <span class="field-label">Arquivo da placa (JPG, PNG, WEBP, TIFF, BMP, PDF)</span>
                            <input id="image" type="file" name="image" accept="image/*,.pdf,.tif,.tiff,.webp,.bmp" required>
                            <span class="upload-hint">Selecione a imagem original. O sistema gera recorte bruto, recorte tratado e mantém a conferência humana antes da impressão documental.</span>
                        </label>
                        <div class="btn-row">
                            <button id="ocrSubmitButton" class="btn btn-primary" type="submit">Processar imagem</button>
                            <a class="btn btn-secondary" href="/historico.php">Ver histórico</a>
                        </div>
                    </form>

                    <div class="upload-meta-row">
                        <article class="upload-meta">
                            <p class="upload-meta-label">Entrada</p>
                            <p class="upload-meta-value">Imagem original preservada</p>
                        </article>
                        <article class="upload-meta">
                            <p class="upload-meta-label">Processamento</p>
                            <p class="upload-meta-value">Recorte bruto e recorte tratado</p>
                        </article>
                        <article class="upload-meta">
                            <p class="upload-meta-label">Saída</p>
                            <p class="upload-meta-value">Relatório formal pronto para revisão</p>
                        </article>
                    </div>
                </div>
            </div>

            <?php if ($errorMessage) { ?>
                <div class="alert alert-danger"><?php echo htmlspecialchars($errorMessage); ?></div>
            <?php } ?>

            <?php if ($dbWarning) { ?>
                <div class="alert alert-warning"><?php echo htmlspecialchars($dbWarning); ?></div>
            <?php } ?>

            <?php if ($warningsList) { ?>
                <div class="alert alert-warning"><?php echo htmlspecialchars(implode(' | ', array_map('strval', $warningsList))); ?></div>
            <?php } ?>

            <?php if ($engineRuntimeWarnings) { ?>
                <div class="alert alert-warning">
                    Estado operacional dos motores: <?php echo htmlspecialchars(implode(' | ', $engineRuntimeWarnings)); ?>
                </div>
            <?php } ?>
        </section>

        <?php if (!isset($result) || !is_array($result)) { ?>
            <section class="card analysis-bridge-card no-print">
                <div class="analysis-bridge-header">
                    <div>
                        <p class="analysis-report-eyebrow">Fluxo documental</p>
                        <h2 class="analysis-bridge-title">Acompanhamento técnico em três movimentos</h2>
                        <p class="analysis-bridge-text">
                            A interface preserva a imagem-fonte, documenta o recorte bruto e o recorte tratado, e mantém a conferência humana antes de qualquer impressão documental.
                        </p>
                    </div>
                    <div class="analysis-bridge-badge">Apoio técnico</div>
                </div>

                <div class="analysis-bridge-grid">
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">01</span>
                        <div>
                            <h3>Preservação da fonte</h3>
                            <p>A imagem original permanece intacta, com integridade e rastreabilidade preservadas para comparação pericial.</p>
                        </div>
                    </article>
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">02</span>
                        <div>
                            <h3>Tratamento técnico</h3>
                            <p>O recorte bruto, o recorte tratado e os metadados são exibidos de forma comparativa e consistente.</p>
                        </div>
                    </article>
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">03</span>
                        <div>
                            <h3>Conferência humana</h3>
                            <p>O consenso OCR é revisado antes da consolidação, reduzindo ruído e fortalecendo a credibilidade documental.</p>
                        </div>
                    </article>
                </div>
            </section>
        <?php } ?>

        <?php if (isset($result) && is_array($result)) { ?>
            <?php if ($analysisReportOverview) { ?>
                <section class="card analysis-report-card" id="analysisReport">
                    <div class="analysis-report-watermark" aria-hidden="true">
                        <img src="/assets/grom-report-logo.png" alt="">
                    </div>

                    <div class="analysis-report-cover">
                        <div class="analysis-report-cover-brand">
                            <div class="analysis-report-cover-logo">
                                <img src="/assets/grom-report-logo.png" alt="Grom OCR">
                            </div>
                            <div class="analysis-report-cover-copy">
                                <p class="analysis-report-eyebrow">Relatório automático</p>
                                <h2 class="analysis-report-cover-title">Relatório de apoio à investigação</h2>
                                <p class="analysis-report-cover-subtitle">
                                    <?php echo htmlspecialchars($analysisStage === 'preview'
                                        ? 'Pré-análise em tela para correção antes da consolidação documental.'
                                        : 'Documento consolidado e pronto para impressão documental.'); ?>
                                </p>
                            </div>
                        </div>

                        <div class="analysis-report-cover-status">
                            <span class="status-chip <?php echo htmlspecialchars((string) $analysisReportOverview['status_class']); ?> status-chip--compact">
                                <?php echo htmlspecialchars($analysisStage === 'preview' ? 'Pré-análise' : 'Consolidado'); ?>
                            </span>
                            <span class="analysis-report-cover-tag">
                                <?php echo htmlspecialchars($analysisStage === 'preview' ? 'Aguardando correção em tela' : 'Disponível para impressão documental'); ?>
                            </span>
                        </div>

                        <div class="analysis-report-cover-meta">
                            <article class="analysis-report-item">
                                <span class="analysis-report-item-label">Identificação</span>
                                <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['analysis_id']); ?></strong>
                                <span class="analysis-report-item-note"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Pré-análise' : 'Consolidado'); ?></span>
                            </article>
                            <article class="analysis-report-item">
                                <span class="analysis-report-item-label">Placa principal</span>
                                <strong class="analysis-report-item-value mono"><?php echo htmlspecialchars((string) $analysisReportOverview['plate_text']); ?></strong>
                                <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['plate_pattern']); ?></span>
                            </article>
                            <article class="analysis-report-item">
                                <span class="analysis-report-item-label">Captura</span>
                                <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['capture_status']); ?></strong>
                                <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['capture_score']); ?>/100</span>
                            </article>
                            <article class="analysis-report-item">
                                <span class="analysis-report-item-label">Consenso OCR</span>
                                <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['consensus']); ?>%</strong>
                                <span class="analysis-report-item-note"><?php echo (int) $analysisReportOverview['consensus_count']; ?> de <?php echo (int) $analysisReportOverview['engines_considered']; ?> motores</span>
                            </article>
                        </div>

                        <p class="analysis-report-cover-note">
                            <?php echo htmlspecialchars($analysisStage === 'preview'
                                ? 'Corrija a leitura para liberar o documento final.'
                                : 'O PDF consolidado já pode ser aberto para arquivamento e impressão.'); ?>
                        </p>
                    </div>

                    <div class="analysis-report-summary-grid">
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Revisão humana</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['review_status']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Ajuste a hipótese antes de consolidar.' : 'Correção registrada no laudo final.'); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Estado documental</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Aguardando correção em tela' : 'Disponível para impressão documental'); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Corrija a leitura para liberar o documento final.' : 'O PDF consolidado já pode ser aberto para arquivamento e impressão.'); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Padrão visual</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['plate_pattern']); ?></strong>
                            <span class="analysis-report-item-note">Alinhado ao estilo e ao consenso do caso.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Status do laudo</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Em correção' : 'Pronto para impressão'); ?></strong>
                            <span class="analysis-report-item-note">Fluxo documental controlado e rastreável.</span>
                        </article>
                    </div>

                    <div class="analysis-report-topics-panel">
                        <p class="analysis-report-section-label">Procedimentos efetuados na análise</p>
                        <div class="analysis-report-outline">
                            <?php foreach ($analysisReportOutline as $outlineSection) { ?>
                                <?php if (!is_array($outlineSection)) {
                                    continue;
                                } ?>
                                <article class="analysis-report-outline-item">
                                    <div class="analysis-report-outline-header">
                                        <div class="analysis-report-outline-number">
                                            <?php echo htmlspecialchars((string) ($outlineSection['number'] ?? '')); ?>
                                        </div>
                                        <div class="analysis-report-outline-copy">
                                            <h3 class="analysis-report-outline-title"><?php echo htmlspecialchars((string) ($outlineSection['title'] ?? '')); ?></h3>
                                            <?php if (!empty($outlineSection['summary'])) { ?>
                                                <p class="analysis-report-outline-summary"><?php echo htmlspecialchars((string) $outlineSection['summary']); ?></p>
                                            <?php } ?>
                                        </div>
                                    </div>
                                    <?php $outlineSubitems = is_array($outlineSection['subitems'] ?? null) ? $outlineSection['subitems'] : []; ?>
                                    <?php if ($outlineSubitems) { ?>
                                        <ul class="analysis-report-outline-sublist">
                                            <?php foreach ($outlineSubitems as $outlineSubitem) { ?>
                                                <?php if (!is_array($outlineSubitem)) {
                                                    continue;
                                                } ?>
                                                <li>
                                                    <strong><?php echo htmlspecialchars(trim((string) ($outlineSubitem['number'] ?? '') . ' - ' . (string) ($outlineSubitem['title'] ?? ''))); ?></strong>
                                                    <?php if (!empty($outlineSubitem['summary'])) { ?>
                                                        <span><?php echo htmlspecialchars((string) $outlineSubitem['summary']); ?></span>
                                                    <?php } ?>
                                                </li>
                                            <?php } ?>
                                        </ul>
                                    <?php } ?>
                                </article>
                            <?php } ?>
                        </div>
                    </div>

                    <div class="btn-row analysis-report-actions-panel">
                        <?php if ($analysisStage === 'preview') { ?>
                            <a class="btn btn-primary" href="#humanReviewForm">Ir para correção</a>
                            <?php if (!empty($result['pdf_report'])) { ?>
                                <a class="btn btn-primary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . '/pdf/' . urlencode((string) $result['pdf_report'])); ?>">Abrir PDF documental (prévia)</a>
                            <?php } ?>
                            <?php if ($manifestUrl !== '') { ?>
                                <a class="btn btn-secondary analysis-report-manifest-link" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $manifestUrl); ?>">Abrir manifesto pericial</a>
                            <?php } ?>
                            <span class="muted">Corrija os campos da conferência antes de liberar o documento final.</span>
                        <?php } else { ?>
                            <?php if (!empty($result['pdf_report'])) { ?>
                                <a class="btn btn-primary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . '/pdf/' . urlencode((string) $result['pdf_report'])); ?>">Abrir PDF documental</a>
                            <?php } ?>
                            <?php if ($manifestUrl !== '') { ?>
                                <a class="btn btn-secondary analysis-report-manifest-link" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $manifestUrl); ?>">Abrir manifesto pericial</a>
                            <?php } ?>
                            <button id="analysisReportPrintBtn" class="btn btn-secondary" type="button">Imprimir página (não é o laudo documental)</button>
                        <?php } ?>
                    </div>
                    <?php if (!empty($result['api_url_used'])) { ?>
                        <p class="muted" style="margin: 8px 0 0;">API utilizada nesta análise: <?php echo htmlspecialchars((string) $result['api_url_used']); ?></p>
                    <?php } ?>
                    <?php if (!empty($result['pdf_report'])) { ?>
                        <p class="muted" style="margin: 4px 0 0;">Para laudo pericial oficial, use sempre o botão "Abrir PDF documental".</p>
                    <?php } ?>
                    <div class="analysis-report-header">
                        <div>
                            <p class="analysis-report-eyebrow">Relatório automático</p>
                            <h2 class="card-title"><?php echo htmlspecialchars((string) $analysisReportOverview['title']); ?></h2>
                            <p class="card-subtitle"><?php echo htmlspecialchars((string) $analysisReportOverview['subtitle']); ?></p>
                        </div>
                        <div class="analysis-report-status">
                            <span class="status-chip <?php echo htmlspecialchars((string) $analysisReportOverview['status_class']); ?> status-chip--compact">
                                <?php echo htmlspecialchars((string) $analysisReportOverview['status_label']); ?>
                            </span>
                        </div>
                    </div>

                    <div class="analysis-report-grid">
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Identificação</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['analysis_id']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['analysis_stage']); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Placa principal</span>
                            <strong class="analysis-report-item-value mono"><?php echo htmlspecialchars((string) $analysisReportOverview['plate_text']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['plate_pattern']); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Integridade</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['capture_status']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['capture_score']); ?>/100</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Consenso OCR</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['consensus']); ?>%</strong>
                            <span class="analysis-report-item-note"><?php echo (int) $analysisReportOverview['consensus_count']; ?> de <?php echo (int) $analysisReportOverview['engines_considered']; ?> motores</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Revisão humana</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['review_status']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo $analysisStage === 'preview' ? 'Ajuste a hipótese antes de consolidar.' : 'Correção registrada no laudo final.'; ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Impressão documental</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars((string) $analysisReportOverview['document_state']); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars((string) $analysisReportOverview['document_hint']); ?></span>
                        </article>
                    </div>

                    <div class="analysis-report-topics">
                        <p class="analysis-report-section-label">Tópicos definidos do relatório</p>
                        <ul class="analysis-report-topic-list">
                            <?php foreach ($analysisReportTopics as $topic) { ?>
                                <li><?php echo htmlspecialchars((string) $topic); ?></li>
                            <?php } ?>
                        </ul>
                    </div>

                    <div class="btn-row analysis-report-actions">
                        <?php if ($analysisStage === 'preview') { ?>
                            <a class="btn btn-primary" href="#humanReviewForm">Ir para correção</a>
                            <?php if ($manifestUrl !== '') { ?>
                                <a class="btn btn-secondary analysis-report-manifest-link" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $manifestUrl); ?>">Abrir manifesto pericial</a>
                            <?php } ?>
                            <span class="muted">Corrija os campos da conferência antes de liberar o documento final.</span>
                        <?php } else { ?>
                            <?php if (!empty($result['pdf_report'])) { ?>
                                <a class="btn btn-primary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . '/pdf/' . urlencode((string) $result['pdf_report'])); ?>">Abrir PDF documental</a>
                            <?php } ?>
                            <?php if ($manifestUrl !== '') { ?>
                                <a class="btn btn-secondary analysis-report-manifest-link" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $manifestUrl); ?>">Abrir manifesto pericial</a>
                            <?php } ?>
                            <button id="analysisReportPrintBtn" class="btn btn-secondary" type="button">Imprimir relatório</button>
                        <?php } ?>
                    </div>
                </section>
            <?php } ?>

            <section class="card">
                <h2 class="card-title">Resultado principal</h2>
                <?php if ($best) { ?>
                    <p class="card-subtitle">
                        Estágio: <strong><?php echo htmlspecialchars($analysisStageLabel); ?></strong> |
                        Motor: <strong><?php echo htmlspecialchars((string) ($best['engine'] ?? '-')); ?></strong> |
                        Confiança média: <strong><?php echo number_format((float) ($best['avg_conf'] ?? 0), 1, ',', '.'); ?>%</strong> |
                        Padrão: <strong><?php echo htmlspecialchars((string) ($best['pattern'] ?? 'Indefinido')); ?></strong> |
                        Acordo entre motores: <strong><?php echo number_format((float) ($best['agreement_ratio'] ?? 0), 1, ',', '.'); ?>%</strong>
                    </p>
                    <p class="plate-highlight"><?php echo htmlspecialchars((string) ($best['text'] ?? '-')); ?></p>
                    <?php if (!empty($best['region'])) { ?>
                        <p class="muted">Região selecionada: <?php echo htmlspecialchars((string) $best['region']); ?></p>
                    <?php } ?>
                    <?php if (!empty($best['support_engines']) && is_array($best['support_engines'])) { ?>
                        <p class="muted">Motores que sustentam a leitura: <?php echo htmlspecialchars(implode(', ', array_map('strval', $best['support_engines']))); ?></p>
                    <?php } ?>
                    <?php if ($scenePreprocess) { ?>
                        <p class="muted">
                            Pré-processamento global: <?php echo htmlspecialchars((string) ($scenePreprocess['selected'] ?? 'original')); ?> |
                            Variante: <?php echo htmlspecialchars((string) ($scenePreprocess['selected_variant'] ?? 'original')); ?> |
                            Família: <?php echo htmlspecialchars((string) ($scenePreprocess['selected_family'] ?? 'opencv')); ?> |
                            Cenário: <?php echo htmlspecialchars((string) ($scenePreprocess['scenario_display_label'] ?? ($sceneProfile['display_label'] ?? humanizeSceneLabel($scenePreprocess['scenario_label'] ?? ($sceneProfile['label'] ?? 'balanced'))))); ?> |
                            Calibração: <?php echo htmlspecialchars((string) ($scenePreprocess['calibration_source'] ?? ($sceneProfile['calibration_source'] ?? 'builtin_default'))); ?> |
                            Motivo: <?php echo htmlspecialchars((string) ($scenePreprocess['selection_reason'] ?? 'n/a')); ?> |
                            Mix: <?php echo htmlspecialchars(implode(', ', array_map('strval', is_array($scenePreprocess['software_families'] ?? null) ? $scenePreprocess['software_families'] : []))); ?> |
                            qualidade antes/depois:
                            <?php echo number_format((float) ($scenePreBefore['quality_score'] ?? 0), 1, ',', '.'); ?> /
                            <?php echo number_format((float) ($scenePreAfter['quality_score'] ?? 0), 1, ',', '.'); ?> |
                            melhoria: <?php echo number_format((float) ($scenePreprocess['improvement'] ?? 0), 1, ',', '.'); ?> |
                            candidatos: <?php echo (int) ($scenePreprocess['candidate_count'] ?? 0); ?>
                            <?php if (!empty($scenePreprocess['scenario_tags']) && is_array($scenePreprocess['scenario_tags'])) { ?>
                                | Tags: <?php echo htmlspecialchars(implode(', ', array_map('strval', $scenePreprocess['scenario_tags']))); ?>
                            <?php } ?>
                        </p>
                    <?php } ?>
                    <?php if ($inputSecurity) { ?>
                        <p class="muted">
                            Segurança da entrada: <?php echo htmlspecialchars(humanizePericialLabel($inputSecurity['status'] ?? 'indefinido')); ?> |
                            Tipo: <?php echo htmlspecialchars((string) ($inputSecurity['input_type'] ?? 'indefinido')); ?> |
                            Extensão: <?php echo htmlspecialchars((string) ($inputSecurity['extension'] ?? '-')); ?> |
                            Assinatura: <?php echo htmlspecialchars((string) ($inputSecurity['detected_signature'] ?? '-')); ?> |
                            Compatível: <?php echo !empty($inputSecurity['signature_ok']) ? 'Sim' : 'Não'; ?> |
                            Tamanho: <?php echo number_format((float) ($inputSecurity['file_size_mb'] ?? 0), 2, ',', '.'); ?> MB |
                            Limite: <?php echo number_format((float) ($inputSecurity['max_upload_mb'] ?? 0), 0, ',', '.'); ?> MB
                        </p>
                    <?php } ?>
                    <?php if ($captureIntegrity) { ?>
                        <p class="muted">
                            Integridade da captura: <?php echo htmlspecialchars(humanizePericialLabel($captureIntegrity['status'] ?? 'indefinido')); ?> |
                            Nota: <?php echo number_format((float) ($captureIntegrity['integrity_score'] ?? 0), 1, ',', '.'); ?> |
                            Faixa: <?php echo htmlspecialchars(humanizePericialLabel($captureIntegrity['integrity_grade'] ?? '-')); ?> |
                            Revisão manual: <?php echo !empty($captureIntegrity['manual_review_recommended']) ? 'Sim' : 'Não'; ?>
                        </p>
                    <?php } ?>
                    <?php if ($plateDetection) { ?>
                        <p class="muted">
                            Detecção da placa: <?php echo htmlspecialchars(humanizePericialLabel($plateDetection['status'] ?? 'indefinido')); ?> |
                            ROI canonica: <?php echo htmlspecialchars((string) ($plateDetection['selected_region'] ?? '-')); ?> |
                            ROI OCR: <?php echo htmlspecialchars((string) ($plateDetection['ocr_selected_region'] ?? ($plateDetection['selected_region'] ?? '-'))); ?> |
                            Fonte: <?php echo htmlspecialchars((string) ($plateDetection['selected_source'] ?? '-')); ?> |
                            Calibracao: <?php echo htmlspecialchars((string) ($plateDetection['calibration_source'] ?? 'builtin_default')); ?> |
                            Candidatos: <?php echo (int) ($plateDetection['candidate_count'] ?? 0); ?> |
                            Aspecto: <?php echo number_format((float) ($plateDetection['selected_aspect_ratio'] ?? 0), 3, ',', '.'); ?> |
                            Faixa ROI: <?php echo htmlspecialchars(humanizeRoiQualityLabel($plateDetection['selected_quality_label'] ?? 'indefinida')); ?> |
                            Qualidade: <?php echo number_format((float) ($plateDetection['selected_quality_score'] ?? 0), 1, ',', '.'); ?> |
                            Score: <?php echo number_format((float) ($plateDetection['selected_score'] ?? 0), 1, ',', '.'); ?>
                            <?php if (!empty($plateDetection['selected_shape_hint'])) { ?>
                                | Forma: <?php echo htmlspecialchars((string) $plateDetection['selected_shape_hint']); ?>
                            <?php } ?>
                        </p>
                    <?php } ?>
                <?php } else { ?>
                    <div class="alert alert-warning">
                        Nenhum resultado atingiu o limiar atual de confiança (<?php echo number_format($ocrMinConfidence, 1, ',', '.'); ?>%).
                    </div>
                <?php } ?>

                <div class="grid" style="margin-top:10px;">
                    <div class="col-4 kpi">
                        <p class="kpi-label">Top candidates</p>
                        <p class="kpi-value"><?php echo count($topCandidates); ?></p>
                    </div>
                    <div class="col-4 kpi">
                        <p class="kpi-label">Motores executados</p>
                        <p class="kpi-value"><?php echo (int) ($ocrEngineSummary['engines_executed'] ?? count($ocrEngines)); ?></p>
                    </div>
                    <div class="col-4 kpi">
                        <p class="kpi-label">Motores prontos</p>
                        <p class="kpi-value"><?php echo (int) ($ocrEngineSummary['engines_ready'] ?? $ocrEngineSummary['engines_available'] ?? count($ocrEngines)); ?></p>
                    </div>
                </div>
                <?php if ($ocrEngineSummary) { ?>
                    <p class="muted" style="margin-top:8px;">
                        Registrados: <strong><?php echo (int) ($ocrEngineSummary['engines_registered'] ?? 0); ?></strong> |
                        Prontos: <strong><?php echo (int) ($ocrEngineSummary['engines_ready'] ?? 0); ?></strong> |
                        Com texto: <strong><?php echo (int) ($ocrEngineSummary['engines_with_text'] ?? 0); ?></strong> |
                        Sem texto: <strong><?php echo (int) ($ocrEngineSummary['engines_without_text'] ?? 0); ?></strong> |
                        Pulados: <strong><?php echo (int) ($ocrEngineSummary['engines_skipped'] ?? 0); ?></strong> |
                        Desabilitados: <strong><?php echo (int) ($ocrEngineSummary['engines_disabled'] ?? 0); ?></strong> |
                        Indisponiveis: <strong><?php echo (int) ($ocrEngineSummary['engines_unavailable'] ?? 0); ?></strong> |
                        Falhos: <strong><?php echo (int) ($ocrEngineSummary['engines_failed'] ?? 0); ?></strong> |
                        Calibracao reranking: <strong><?php echo htmlspecialchars((string) ($ocrEngineSummary['reranking_calibration_source'] ?? 'builtin_default')); ?></strong> |
                        Arquivo: <strong><?php echo htmlspecialchars((string) ($ocrEngineSummary['reranking_calibration_path'] ?? '-')); ?></strong>
                    </p>
                <?php } ?>
            </section>

            <section class="card">
                <h2 class="card-title">Correção e conferência técnico-pericial</h2>
                <p class="card-subtitle">
                    <?php if ($analysisStage === 'preview') { ?>
                        A pré-análise técnico-pericial está disponível para correção humana. Selecione a hipótese mais consistente antes de consolidar o laudo final.
                    <?php } elseif (!empty($humanReview) && $finalReportReady) { ?>
                        A conferência técnico-pericial foi registrada e o laudo final já está disponível para impressão documental.
                    <?php } elseif (!empty($humanReview)) { ?>
                        A conferência técnico-pericial foi registrada, mas o laudo final ainda não foi liberado.
                    <?php } else { ?>
                        Aguardando conferência técnico-pericial.
                    <?php } ?>
                </p>

                <?php if ($analysisStage === 'preview') { ?>
                    <div class="grid">
                        <div class="col-7">
                            <div class="table-wrap">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>#</th>
                                            <th>Hipótese</th>
                                            <th>Motor OCR</th>
                                            <th>Confiança (%)</th>
                                            <th>Pontuação pericial</th>
                                            <th>Apoio entre motores</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <?php if (!empty($topCandidates) && is_array($topCandidates)) { ?>
                                            <?php foreach (array_values($topCandidates) as $candidateIndex => $candidate) { ?>
                                                <?php if (!is_array($candidate)) {
                                                    continue;
                                                } ?>
                                                <tr>
                                                    <td><?php echo (int) ($candidateIndex + 1); ?></td>
                                                    <td class="mono"><?php echo htmlspecialchars((string) ($candidate['text'] ?? '-')); ?></td>
                                                    <td><?php echo htmlspecialchars((string) ($candidate['engine'] ?? '-')); ?></td>
                                                    <td><?php echo number_format((float) ($candidate['avg_conf'] ?? 0), 1, ',', '.'); ?>%</td>
                                                    <td><?php echo number_format((float) ($candidate['score'] ?? 0), 1, ',', '.'); ?></td>
                                                    <td><?php echo htmlspecialchars(is_array($candidate['support_engines'] ?? null) ? implode(', ', array_map('strval', $candidate['support_engines'])) : '-'); ?></td>
                                                </tr>
                                            <?php } ?>
                                        <?php } else { ?>
                                            <tr>
                                                <td colspan="6">Nenhuma hipótese consistente retornou nesta pré-análise técnico-pericial.</td>
                                            </tr>
                                        <?php } ?>
                                    </tbody>
                                </table>
                            </div>
                            <?php if ($charOptions) { ?>
                                <div class="table-wrap" style="margin-top:12px;">
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>Alternativa</th>
                                                <th>Confiança</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <?php foreach ($charOptions as $option) { ?>
                                                <tr>
                                                    <td class="mono"><?php echo htmlspecialchars((string) ($option[0] ?? '-')); ?></td>
                                                    <td><?php echo number_format((float) ($option[1] ?? 0), 1, ',', '.'); ?>%</td>
                                                </tr>
                                            <?php } ?>
                                        </tbody>
                                    </table>
                                </div>
                            <?php } ?>
                        </div>
                        <div class="col-5">
                            <form id="humanReviewForm" method="POST" class="review-form">
                                <input type="hidden" name="finalize_review" value="1">
                                <input type="hidden" name="preview_analysis_id" value="<?php echo htmlspecialchars($previewAnalysisId); ?>">
                                <label class="field" for="humanReviewCandidateSelect">
                                    <span class="field-label">Hipótese ratificada</span>
                                    <select id="humanReviewCandidateSelect" name="selected_candidate_index">
                                        <?php if (empty($topCandidates)) { ?>
                                            <option value="">Sem hipótese forte</option>
                                        <?php } else { ?>
                                            <?php foreach (array_values($topCandidates) as $candidateIndex => $candidate) { ?>
                                                <?php if (!is_array($candidate)) {
                                                    continue;
                                                } ?>
                                                <option
                                                    value="<?php echo (int) $candidateIndex; ?>"
                                                    data-text="<?php echo htmlspecialchars((string) ($candidate['text'] ?? '')); ?>"
                                                    <?php echo $candidateIndex === 0 ? 'selected' : ''; ?>>
                                                    #<?php echo (int) ($candidateIndex + 1); ?> |
                                                    <?php echo htmlspecialchars((string) ($candidate['text'] ?? '-')); ?> |
                                                    <?php echo htmlspecialchars((string) ($candidate['engine'] ?? '-')); ?>
                                                </option>
                                            <?php } ?>
                                        <?php } ?>
                                    </select>
                                </label>
                                <label class="field" for="humanReviewDecision">
                                    <span class="field-label">Deliberacao pericial</span>
                                    <select id="humanReviewDecision" name="review_decision">
                                        <option value="confirmado_manual" selected>Ratificada manualmente</option>
                                        <option value="corrigido_manual">Ratificada com ajuste</option>
                                        <option value="inconclusivo">Inconclusivo</option>
                                    </select>
                                </label>
                                <label class="field" for="humanReviewConfirmedText">
                                    <span class="field-label">Texto ratificado</span>
                                    <input id="humanReviewConfirmedText" type="text" name="confirmed_text" value="<?php echo htmlspecialchars($reviewDefaultText); ?>">
                                </label>
                                <label class="field" for="humanReviewNotes">
                                    <span class="field-label">Observacoes tecnicas</span>
                                    <textarea id="humanReviewNotes" name="review_notes" rows="4" placeholder="Anote a conferência, divergências, fundamentos ou observações técnicas."></textarea>
                                </label>
                                <div class="btn-row">
                                    <button class="btn btn-primary" type="submit">Consolidar laudo final</button>
                                    <a class="btn btn-secondary" href="/historico.php">Ver historico</a>
                                </div>
                            </form>
                            <p class="muted" style="margin-top:10px;">O laudo final só será consolidado após a conferência técnico-pericial e a ratificação da hipótese.</p>
                        </div>
                    </div>
                <?php } elseif (!empty($humanReview)) { ?>
                    <div class="alert <?php echo $finalReportReady ? 'alert-success' : 'alert-warning'; ?>">
                        <?php echo $finalReportReady
                            ? 'Conferência técnico-pericial registrada com sucesso. O laudo final foi consolidado.'
                            : 'Conferência técnico-pericial registrada, mas o laudo final ainda não foi consolidado.'; ?>
                    </div>
                    <div class="table-wrap">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Status técnico-pericial</th>
                                    <td><?php echo htmlspecialchars(humanizePericialLabel($humanReview['status'] ?? 'REGISTRADO')); ?></td>
                                </tr>
                                <tr>
                                    <th>Responsável</th>
                                    <td><?php echo htmlspecialchars((string) ($humanReview['operator'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Deliberação pericial</th>
                                    <td><?php echo htmlspecialchars((string) ($humanReview['decision_label'] ?? humanizePericialLabel($humanReview['decision'] ?? 'confirmado_manual'))); ?></td>
                                </tr>
                                <tr>
                                    <th>Hipótese ratificada</th>
                                    <td class="mono"><?php echo htmlspecialchars((string) ($humanReview['selected_candidate'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Texto ratificado</th>
                                    <td class="mono"><?php echo htmlspecialchars((string) ($humanReview['confirmed_text'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Observacoes tecnicas</th>
                                    <td><?php echo htmlspecialchars((string) ($humanReview['notes'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Revisado em UTC</th>
                                    <td><?php echo htmlspecialchars((string) ($humanReview['reviewed_at_utc'] ?? '-')); ?></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                <?php } else { ?>
                    <div class="alert alert-warning">Nenhuma conferência técnico-pericial foi registrada nesta análise.</div>
                <?php } ?>
            </section>

            <section class="card">
                <h2 class="card-title">Classificação técnico-probatória</h2>
                <p class="card-subtitle">
                    Nível técnico-probatório: <strong><?php echo htmlspecialchars(humanizePericialLabel($assessment['evidence_level'] ?? 'BAIXA')); ?></strong> |
                    Confiança da inferência: <strong><?php echo number_format((float) ($assessment['confidence_percent'] ?? 0), 1, ',', '.'); ?>%</strong> |
                    Consenso entre motores: <strong><?php echo number_format((float) ($consensus['agreement_ratio'] ?? 0), 1, ',', '.'); ?>%</strong>
                </p>
                <p class="muted">
                    Ratificacao manual obrigatoria:
                    <strong><?php echo !empty($assessment['manual_review_required']) ? 'Sim' : 'Não'; ?></strong>
                </p>
                <?php if (!empty($assessment['reasons']) && is_array($assessment['reasons'])) { ?>
                    <p class="muted">Fundamentos técnicos: <?php echo htmlspecialchars(implode(', ', array_map('strval', $assessment['reasons']))); ?></p>
                <?php } ?>
            </section>

            <section class="card">
                <h2 class="card-title">Cadeia de custódia técnico-digital</h2>
                <div class="table-wrap">
                    <table>
                        <tbody>
                            <tr>
                                <th>Identificador da análise</th>
                                <td><?php echo htmlspecialchars((string) ($forensic['analysis_id'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Início da custódia (UTC)</th>
                                <td><?php echo htmlspecialchars((string) ($forensic['started_at_utc'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Encerramento da custódia (UTC)</th>
                                <td><?php echo htmlspecialchars((string) ($forensic['finished_at_utc'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Hash SHA-256 do arquivo fonte</th>
                                <td class="mono"><?php echo htmlspecialchars((string) ($forensic['source_sha256'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Hash SHA-256 do recorte da placa</th>
                                <td class="mono"><?php echo htmlspecialchars((string) ($forensic['plate_sha256'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Assinatura digital</th>
                                <td class="mono"><?php echo htmlspecialchars((string) ($forensic['signature'] ?? '-')); ?></td>
                            </tr>
                            <tr>
                                <th>Algoritmo de assinatura</th>
                                <td><?php echo htmlspecialchars((string) ($forensic['signature_algorithm'] ?? '-')); ?></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <section class="card">
                <h2 class="card-title">Validação pericial automatizada</h2>
                <?php
                $pericialQuality = is_array($pericial['quality'] ?? null) ? $pericial['quality'] : [];
                $pericialLegal = is_array($pericial['legal_validation'] ?? null) ? $pericial['legal_validation'] : [];
                $pericialAmbiguity = is_array($pericial['character_ambiguity'] ?? null) ? $pericial['character_ambiguity'] : [];
                $pericialCross = is_array($pericial['cross_checks'] ?? null) ? $pericial['cross_checks'] : [];
                $localCross = is_array($pericialCross['local_history'] ?? null) ? $pericialCross['local_history'] : [];
                $captureIntegrity = is_array($pericialCross['capture_integrity'] ?? null) ? $pericialCross['capture_integrity'] : [];
                $externalCross = is_array($pericialCross['external_source'] ?? null) ? $pericialCross['external_source'] : [];
                $externalSystemsCross = is_array($pericialCross['external_systems'] ?? null) ? $pericialCross['external_systems'] : [];
                $visualCross = is_array($pericialCross['visual_profile'] ?? null) ? $pericialCross['visual_profile'] : [];
                $visualCrossSearchEngines = is_array($visualCross['motores_busca_utilizados'] ?? null) ? $visualCross['motores_busca_utilizados'] : [];
                $visualCrossAnalysisEngines = is_array($visualCross['motores_analise_utilizados'] ?? null) ? $visualCross['motores_analise_utilizados'] : [];
                ?>
                <div class="grid">
                    <div class="col-4 kpi">
                        <p class="kpi-label">Status Pericial</p>
                        <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($pericial['status'] ?? 'INDEFINIDO')); ?></p>
                    </div>
                    <div class="col-4 kpi">
                        <p class="kpi-label">Qualidade da Imagem</p>
                        <p class="kpi-value"><?php echo number_format((float) ($pericialQuality['score'] ?? 0), 1, ',', '.'); ?></p>
                    </div>
                    <div class="col-4 kpi">
                        <p class="kpi-label">Conformidade Legal</p>
                        <p class="kpi-value"><?php echo number_format((float) ($pericialLegal['law_score'] ?? 0), 1, ',', '.'); ?></p>
                    </div>
                </div>

                <div class="table-wrap" style="margin-top:12px;">
                    <table>
                        <tbody>
                            <tr>
                                <th>Padrão detectado (lei)</th>
                                <td><?php echo htmlspecialchars((string) ($pericialLegal['detected_pattern'] ?? 'Indefinido')); ?></td>
                            </tr>
                            <tr>
                                <th>Válida nos padrões brasileiros</th>
                                <td><?php echo !empty($pericialLegal['is_valid']) ? 'Sim' : 'Não'; ?></td>
                            </tr>
                            <tr>
                                <th>Melhor encaixe legal</th>
                                <td><?php echo htmlspecialchars((string) ($pericialLegal['best_fit_pattern'] ?? 'Indefinido')); ?></td>
                            </tr>
                            <tr>
                                <th>Posições ambíguas</th>
                                <td><?php echo htmlspecialchars((string) ($pericialAmbiguity['ambiguity_count'] ?? 0)); ?></td>
                            </tr>
                            <tr>
                                <th>Detalhes de ambiguidade</th>
                                <td>
                                    <?php
                                    $ambiguousDetails = [];
                                    if (isset($pericialAmbiguity['ambiguous_positions']) && is_array($pericialAmbiguity['ambiguous_positions'])) {
                                        foreach ($pericialAmbiguity['ambiguous_positions'] as $entry) {
                                            if (!is_array($entry)) {
                                                continue;
                                            }
                                            $position = (string) ($entry['position'] ?? '?');
                                            $slot = (string) ($entry['expected_slot'] ?? '?');
                                            $ambiguousDetails[] = 'P' . $position . '[' . $slot . ']';
                                        }
                                    }
                                    echo htmlspecialchars($ambiguousDetails ? implode('; ', $ambiguousDetails) : '-');
                                    ?>
                                </td>
                            </tr>
                            <tr>
                                <th>Histórico local da placa</th>
                                <td>
                                    Status: <?php echo htmlspecialchars(humanizePericialLabel($localCross['status'] ?? 'indefinido')); ?> |
                                    Ocorrencias anteriores: <?php echo htmlspecialchars((string) ($localCross['previous_occurrences'] ?? 0)); ?>
                                </td>
                            </tr>
                            <tr>
                                <th>Integridade da captura</th>
                                <td>
                                    Status: <?php echo htmlspecialchars(humanizePericialLabel($captureIntegrity['status'] ?? 'indefinido')); ?> |
                                    Nota: <?php echo number_format((float) ($captureIntegrity['integrity_score'] ?? 0), 1, ',', '.'); ?> |
                                    Faixa: <?php echo htmlspecialchars(humanizePericialLabel($captureIntegrity['integrity_grade'] ?? '-')); ?> |
                                    Entrada: <?php echo htmlspecialchars(humanizePericialLabel($captureIntegrity['input_status'] ?? 'indefinido')); ?> |
                                    Assinatura: <?php echo htmlspecialchars((string) ($captureIntegrity['input_signature'] ?? '-')); ?> |
                                    Compatível: <?php echo !empty($captureIntegrity['input_signature_ok']) ? 'Sim' : 'Não'; ?> |
                                    ROI placa: <?php echo htmlspecialchars((string) ($captureIntegrity['plate_detection_selected_region'] ?? '-')); ?> |
                                    ROI OCR: <?php echo htmlspecialchars((string) ($captureIntegrity['plate_detection_ocr_selected_region'] ?? '-')); ?> |
                                    Calibracao ROI: <?php echo htmlspecialchars((string) ($captureIntegrity['plate_detection_calibration_source'] ?? 'builtin_default')); ?> |
                                    Aspecto ROI: <?php echo number_format((float) ($captureIntegrity['plate_detection_selected_aspect_ratio'] ?? 0), 3, ',', '.'); ?> |
                                    Faixa ROI: <?php echo htmlspecialchars(humanizeRoiQualityLabel($captureIntegrity['plate_detection_selected_quality_label'] ?? 'indefinida')); ?> |
                                    Qualidade ROI: <?php echo number_format((float) ($captureIntegrity['plate_detection_selected_quality_score'] ?? 0), 1, ',', '.'); ?> |
                                    Candidatos: <?php echo (int) ($captureIntegrity['plate_detection_candidate_count'] ?? 0); ?> |
                                    Revisão manual: <?php echo !empty($captureIntegrity['manual_review_recommended']) ? 'Sim' : 'Não'; ?>
                                </td>
                            </tr>
                            <?php if (!empty($captureIntegrity['score_breakdown_text']) && $captureIntegrity['score_breakdown_text'] !== '-') { ?>
                                <tr>
                                    <th>Fatores da nota</th>
                                    <td><?php echo htmlspecialchars((string) $captureIntegrity['score_breakdown_text']); ?></td>
                                </tr>
                            <?php } ?>
                            <tr>
                                <th>Fonte externa</th>
                                <td>
                                    Status: <?php echo htmlspecialchars(humanizePericialLabel($externalCross['status'] ?? 'indefinido')); ?> |
                                    Fonte: <?php echo htmlspecialchars((string) ($externalCross['source'] ?? '-')); ?> |
                                    Compatibilidade OCR: <?php
                                                            if (array_key_exists('matches_ocr', $externalCross)) {
                                                                if ($externalCross['matches_ocr'] === true) {
                                                                    echo 'Sim';
                                                                } elseif ($externalCross['matches_ocr'] === false) {
                                                                    echo 'Não';
                                                                } else {
                                                                    echo 'N/A';
                                                                }
                                                            } else {
                                                                echo 'N/A';
                                                            }
                                                            ?>
                                    | Consulta multicamada: <?php echo htmlspecialchars(humanizePericialLabel($externalCross['multifonte_status'] ?? 'indefinido')); ?> |
                                    Fontes: <?php echo htmlspecialchars((string) ($externalCross['multifonte_candidatos'] ?? 0)); ?> |
                                    Confiança: <?php echo htmlspecialchars((string) ($externalCross['multifonte_confianca'] ?? '0.0')); ?>% |
                                    Taxa consenso: <?php echo htmlspecialchars((string) ($externalCross['multifonte_taxa_consenso'] ?? '0.0')); ?>% |
                                    Score: <?php echo htmlspecialchars((string) ($externalCross['multifonte_score'] ?? '0.0')); ?> |
                                    Limite: <?php echo htmlspecialchars((string) ($externalCross['multifonte_limite'] ?? 0)); ?> |
                                    Limite aplicado: <?php echo htmlspecialchars((string) ($externalCross['multifonte_limite_aplicado'] ?? 'Não')); ?> |
                                    Consenso: <?php echo htmlspecialchars((string) ($externalCross['multifonte_consenso'] ?? '-')); ?> |
                                    Divergencias: <?php echo htmlspecialchars((string) ($externalCross['multifonte_divergencias'] ?? '-')); ?> |
                                    Resumo: <?php echo htmlspecialchars((string) ($externalCross['multifonte_resumo'] ?? '-')); ?> |
                                    Alertas: <?php echo htmlspecialchars((string) ($externalCross['multifonte_alertas'] ?? '-')); ?>
                                </td>
                            </tr>
                            <tr>
                                <th>Comparativo de sistemas externos</th>
                                <td>
                                    Status: <?php echo htmlspecialchars(humanizePericialLabel($externalSystemsCross['status'] ?? 'indefinido')); ?> |
                                    Catalogados: <?php echo htmlspecialchars((string) ($externalSystemsCross['systems_cataloged'] ?? 0)); ?> |
                                    Executados: <?php echo htmlspecialchars((string) ($externalSystemsCross['systems_executed'] ?? 0)); ?> |
                                    OK: <?php echo htmlspecialchars((string) ($externalSystemsCross['systems_ok'] ?? 0)); ?> |
                                    Placa compativel: <?php echo htmlspecialchars((string) ($externalSystemsCross['plate_compatible_count'] ?? 0)); ?> |
                                    Veículo compatível: <?php echo htmlspecialchars((string) ($externalSystemsCross['vehicle_compatible_count'] ?? 0)); ?> |
                                    Taxa placa/veículo:
                                    <?php echo number_format((float) ($externalSystemsCross['plate_match_ratio'] ?? 0), 1, ',', '.'); ?>%
                                    /
                                    <?php echo number_format((float) ($externalSystemsCross['vehicle_match_ratio'] ?? 0), 1, ',', '.'); ?>%
                                </td>
                            </tr>
                            <tr>
                                <th>Perfil visual</th>
                                <td>
                                    Status: <?php echo htmlspecialchars(humanizePericialLabel($visualCross['status'] ?? 'indefinido')); ?> |
                                    Fabricante: <?php echo htmlspecialchars((string) ($visualCross['fabricante'] ?? '-')); ?> |
                                    Modelo: <?php echo htmlspecialchars((string) ($visualCross['modelo'] ?? '-')); ?> |
                                    Modelo bruto: <?php echo htmlspecialchars((string) ($visualCross['modelo_bruto'] ?? '-')); ?> |
                                    Modelo abstido: <?php echo !empty($visualCross['modelo_abstido']) ? 'Sim' : 'Não'; ?> |
                                    Motivo abstencao: <?php echo htmlspecialchars((string) ($visualCross['modelo_abstencao_motivos'] ?? '-')); ?> |
                                    Confiança: <?php echo number_format((float) ($visualCross['confianca'] ?? 0), 1, ',', '.'); ?>% |
                                    Confiança bruta modelo: <?php echo number_format((float) ($visualCross['confianca_modelo_bruta'] ?? 0), 1, ',', '.'); ?>% |
                                    Margem top2: <?php echo number_format((float) ($visualCross['margem_top2_modelo'] ?? 0), 1, ',', '.'); ?> |
                                    Evidencias discriminativas: <?php echo htmlspecialchars((string) ($visualCross['evidencias_discriminativas'] ?? 0)); ?> |
                                    Vista: <?php echo htmlspecialchars((string) ($visualCross['vista_detectada'] ?? 'indefinida')); ?> |
                                    Lanterna vertical: <?php echo !empty($visualCross['lanterna_traseira_vertical']) ? 'Sim' : 'Não'; ?> |
                                    Fontes abertas: <?php echo htmlspecialchars((string) ($visualCross['fontes_abertas_count'] ?? 0)); ?> |
                                    Componentes: <?php echo htmlspecialchars((string) ($visualCross['componentes_detectados'] ?? 0)); ?>/<?php echo htmlspecialchars((string) ($visualCross['componentes_avaliados'] ?? 0)); ?> |
                                    Cobertura: <?php echo number_format((float) ($visualCross['componentes_cobertura'] ?? 0), 1, ',', '.'); ?>% |
                                    Forense: <?php echo htmlspecialchars(humanizePericialLabel($visualCross['caracteristicas_forenses_status'] ?? 'indefinido')); ?> |
                                    Achados: <?php echo htmlspecialchars((string) ($visualCross['caracteristicas_forenses_detectadas'] ?? 0)); ?> |
                                    Busca: <?php echo htmlspecialchars($visualCrossSearchEngines ? implode(', ', array_map('strval', $visualCrossSearchEngines)) : '-'); ?> |
                                    Análise: <?php echo htmlspecialchars($visualCrossAnalysisEngines ? implode(', ', array_map('strval', $visualCrossAnalysisEngines)) : '-'); ?>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p class="muted" style="margin-top:10px;">
                    Linguagem técnico-pericial preliminar: este relatório possui finalidade de apoio investigativo e exige revisão humana obrigatória,
                    confrontação documental e correlação com outros elementos probatórios.
                </p>

                <?php if (!empty($pericialLegal['violations']) && is_array($pericialLegal['violations'])) { ?>
                    <p class="muted">Violacoes legais detectadas: <?php echo htmlspecialchars(implode(', ', array_map('strval', $pericialLegal['violations']))); ?></p>
                <?php } ?>
                <?php if (!empty($pericial['critical_findings']) && is_array($pericial['critical_findings'])) { ?>
                    <p class="muted">Achados criticos: <?php echo htmlspecialchars(implode(', ', array_map('strval', $pericial['critical_findings']))); ?></p>
                <?php } ?>
            </section>

            <?php if ($operationalProtocol) { ?>
                <section class="card">
                    <h2 class="card-title">Protocolo operacional de análise</h2>
                    <?php
                    $opEvidence = is_array($operationalProtocol['evidence_preservation'] ?? null) ? $operationalProtocol['evidence_preservation'] : [];
                    $opTriage = is_array($operationalProtocol['quality_triage'] ?? null) ? $operationalProtocol['quality_triage'] : [];
                    $opOcr = is_array($operationalProtocol['ocr_record'] ?? null) ? $operationalProtocol['ocr_record'] : [];
                    $opVehicle = is_array($operationalProtocol['vehicle_basics'] ?? null) ? $operationalProtocol['vehicle_basics'] : [];
                    $opMatrix = is_array($operationalProtocol['compatibility_matrix'] ?? null) ? $operationalProtocol['compatibility_matrix'] : [];
                    $opExclusion = is_array($operationalProtocol['exclusion_checks'] ?? null) ? $operationalProtocol['exclusion_checks'] : [];
                    $opConclusion = is_array($operationalProtocol['conclusion'] ?? null) ? $operationalProtocol['conclusion'] : [];
                    $opChecklist = is_array($operationalProtocol['checklist_operacional'] ?? null) ? $operationalProtocol['checklist_operacional'] : [];
                    $opSourceResolution = is_array($opEvidence['source_resolution'] ?? null) ? $opEvidence['source_resolution'] : [];
                    $opPlateResolution = is_array($opEvidence['plate_resolution'] ?? null) ? $opEvidence['plate_resolution'] : [];
                    $opTransformations = is_array($opEvidence['transformations'] ?? null) ? $opEvidence['transformations'] : [];
                    $opCrops = is_array($opEvidence['available_crops'] ?? null) ? $opEvidence['available_crops'] : [];
                    ?>
                    <div class="grid">
                        <div class="col-4 kpi">
                            <p class="kpi-label">Status do protocolo</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($operationalProtocol['status'] ?? 'indefinido')); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Nível conclusivo</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($opConclusion['display_level'] ?? ($opConclusion['level'] ?? 'INDEFINIDO'))); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Pontuação</p>
                            <p class="kpi-value"><?php echo number_format((float) ($opConclusion['score'] ?? $opMatrix['score_total'] ?? 0), 1, ',', '.'); ?></p>
                        </div>
                    </div>
                    <div class="table-wrap" style="margin-top:12px;">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Decisao</th>
                                    <td><?php echo htmlspecialchars((string) ($opConclusion['decision'] ?? 'indefinida')); ?></td>
                                </tr>
                                <tr>
                                    <th>Resumo</th>
                                    <td><?php echo htmlspecialchars((string) ($operationalProtocol['summary'] ?? $opConclusion['summary'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Preservacao da evidencia</th>
                                    <td>
                                        ID: <?php echo htmlspecialchars((string) ($opEvidence['analysis_id'] ?? '-')); ?> |
                                        Origem: <?php echo htmlspecialchars((string) ($opEvidence['origem'] ?? '-')); ?> |
                                        Arquivo: <?php echo htmlspecialchars((string) ($opEvidence['source_filename'] ?? '-')); ?> |
                                        Placa: <?php echo htmlspecialchars((string) ($opEvidence['plate_filename'] ?? '-')); ?> |
                                        Original: <?php echo htmlspecialchars((string) ($opSourceResolution['width'] ?? '-')); ?>x<?php echo htmlspecialchars((string) ($opSourceResolution['height'] ?? '-')); ?> |
                                        Placa ROI: <?php echo htmlspecialchars((string) ($opPlateResolution['width'] ?? '-')); ?>x<?php echo htmlspecialchars((string) ($opPlateResolution['height'] ?? '-')); ?> |
                                        Transformacoes: <?php echo htmlspecialchars($opTransformations ? implode(', ', array_map('strval', $opTransformations)) : '-'); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Triagem de qualidade</th>
                                    <td>
                                        Classe: <?php echo htmlspecialchars(humanizePericialLabel($opTriage['class'] ?? 'D')); ?> |
                                        Faixa: <?php echo htmlspecialchars(humanizePericialLabel($opTriage['display_label'] ?? ($opTriage['label'] ?? '-'))); ?> |
                                        Nota: <?php echo number_format((float) ($opTriage['score'] ?? 0), 1, ',', '.'); ?> |
                                        Revisão manual: <?php echo !empty($opTriage['manual_review']) ? 'Sim' : 'Não'; ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>OCR operacional</th>
                                    <td>
                                        Principal: <?php echo htmlspecialchars((string) ($opOcr['leitura_principal'] ?? '-')); ?> |
                                        Não legíveis: <?php echo htmlspecialchars((string) ($opOcr['caracteres_incertos_resumo'] ?? '-')); ?> |
                                        Padrao: <?php echo htmlspecialchars((string) ($opOcr['padrao_placa'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Base primária do veículo</th>
                                    <td>
                                        Categoria: <?php echo htmlspecialchars((string) ($opVehicle['categoria_primaria'] ?? '-')); ?> |
                                        Porte: <?php echo htmlspecialchars((string) ($opVehicle['porte'] ?? '-')); ?> |
                                        Fabricante: <?php echo htmlspecialchars((string) ($opVehicle['fabricante_probavel'] ?? '-')); ?> |
                                        Modelo: <?php echo htmlspecialchars((string) ($opVehicle['modelo_probavel'] ?? '-')); ?> |
                                        Ano: <?php echo htmlspecialchars((string) ($opVehicle['faixa_ano_probavel'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Matriz de compatibilidade</th>
                                    <td>
                                        Score: <?php echo number_format((float) ($opMatrix['score_total'] ?? 0), 1, ',', '.'); ?> |
                                        Cobertura: <?php echo number_format((float) ($opMatrix['coverage_percent'] ?? 0), 1, ',', '.'); ?>% |
                                        Nível: <?php echo htmlspecialchars(humanizePericialLabel($opMatrix['display_level'] ?? ($opMatrix['level'] ?? 'INCOMPATIVEL'))); ?> |
                                        Taxa disponível: <?php echo number_format((float) ($opMatrix['available_ratio'] ?? 0), 1, ',', '.'); ?>%
                                    </td>
                                </tr>
                                <tr>
                                    <th>Exclusoes obrigatorias</th>
                                    <td>
                                        Gatilhos: <?php echo (int) ($opExclusion['triggered_count'] ?? 0); ?> |
                                        Fortes: <?php echo (int) ($opExclusion['strong_triggered_count'] ?? 0); ?> |
                                        Resumo: <?php echo htmlspecialchars(is_array($opExclusion['summary'] ?? null) ? implode(', ', array_map('strval', $opExclusion['summary'])) : '-'); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Conclusão pericial</th>
                                    <td>
                                        Nível: <?php echo htmlspecialchars(humanizePericialLabel($opConclusion['display_level'] ?? ($opConclusion['level'] ?? '-'))); ?> |
                                        Revisão manual: <?php echo !empty($opConclusion['manual_review_required']) ? 'Sim' : 'Não'; ?> |
                                        Resumo: <?php echo htmlspecialchars((string) ($opConclusion['summary'] ?? '-')); ?>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <?php if ($opChecklist) { ?>
                        <p class="muted" style="margin-top:10px;">
                            Checklist operacional: <?php echo htmlspecialchars(implode(' | ', array_map('strval', array_slice($opChecklist, 0, 8)))); ?>
                        </p>
                    <?php } ?>
                    <?php if ($opCrops) { ?>
                        <p class="muted">
                            Cortes preservados: <?php
                                                $cropLines = [];
                                                foreach ($opCrops as $crop) {
                                                    if (!is_array($crop)) {
                                                        continue;
                                                    }
                                                    $cropLines[] = (string) ($crop['name'] ?? '-') . '=' . (!empty($crop['available']) ? 'sim' : 'nao');
                                                }
                                                echo htmlspecialchars($cropLines ? implode(' | ', $cropLines) : '-');
                                                ?>
                        </p>
                    <?php } ?>
                </section>
            <?php } ?>

            <?php if ($vehicleConfrontationForm) { ?>
                <section class="card">
                    <h2 class="card-title">Formulário de confrontação visual de veículo</h2>
                    <?php
                    $formIdentification = is_array($vehicleConfrontationForm['identificacao'] ?? null) ? $vehicleConfrontationForm['identificacao'] : [];
                    $formMaterial = is_array($vehicleConfrontationForm['material_examined'] ?? null) ? $vehicleConfrontationForm['material_examined'] : [];
                    $formQuality = is_array($vehicleConfrontationForm['quality'] ?? null) ? $vehicleConfrontationForm['quality'] : [];
                    $formOcr = is_array($vehicleConfrontationForm['ocr'] ?? null) ? $vehicleConfrontationForm['ocr'] : [];
                    $formClassification = is_array($vehicleConfrontationForm['vehicle_classification'] ?? null) ? $vehicleConfrontationForm['vehicle_classification'] : [];
                    $formFront = is_array($vehicleConfrontationForm['confrontacao_externa']['frente'] ?? null) ? $vehicleConfrontationForm['confrontacao_externa']['frente'] : [];
                    $formRear = is_array($vehicleConfrontationForm['confrontacao_externa']['traseira'] ?? null) ? $vehicleConfrontationForm['confrontacao_externa']['traseira'] : [];
                    $formSide = is_array($vehicleConfrontationForm['confrontacao_externa']['lateral'] ?? null) ? $vehicleConfrontationForm['confrontacao_externa']['lateral'] : [];
                    $formWheels = is_array($vehicleConfrontationForm['confrontacao_externa']['rodas'] ?? null) ? $vehicleConfrontationForm['confrontacao_externa']['rodas'] : [];
                    $formInternal = is_array($vehicleConfrontationForm['confrontacao_interna'] ?? null) ? $vehicleConfrontationForm['confrontacao_interna'] : [];
                    $formHypothesis = is_array($vehicleConfrontationForm['hipotese_principal'] ?? null) ? $vehicleConfrontationForm['hipotese_principal'] : [];
                    $formAlternatives = is_array($vehicleConfrontationForm['hipoteses_alternativas'] ?? null) ? $vehicleConfrontationForm['hipoteses_alternativas'] : [];
                    $formFavorable = is_array($vehicleConfrontationForm['elementos_favoraveis'] ?? null) ? $vehicleConfrontationForm['elementos_favoraveis'] : [];
                    $formExclusion = is_array($vehicleConfrontationForm['elementos_excludentes'] ?? null) ? $vehicleConfrontationForm['elementos_excludentes'] : [];
                    $formCross = is_array($vehicleConfrontationForm['cruzamento_ocr'] ?? null) ? $vehicleConfrontationForm['cruzamento_ocr'] : [];
                    $formMatrix = is_array($vehicleConfrontationForm['matriz'] ?? null) ? $vehicleConfrontationForm['matriz'] : [];
                    $formConclusion = is_array($vehicleConfrontationForm['conclusao'] ?? null) ? $vehicleConfrontationForm['conclusao'] : [];
                    $formClosing = is_array($vehicleConfrontationForm['encerramento'] ?? null) ? $vehicleConfrontationForm['encerramento'] : [];
                    $formChecklist = is_array($vehicleConfrontationForm['checklist_rapido']['items'] ?? null) ? $vehicleConfrontationForm['checklist_rapido']['items'] : [];
                    $formScore = (float) ($formMatrix['pontuacao_final'] ?? 0);
                    ?>
                    <div class="grid">
                        <div class="col-4 kpi">
                            <p class="kpi-label">Resultado</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($formConclusion['resultado'] ?? 'inconclusivo')); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Nível</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($formConclusion['nivel'] ?? 'INDEFINIDO')); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Pontuação</p>
                            <p class="kpi-value"><?php echo number_format($formScore, 1, ',', '.'); ?>/100</p>
                        </div>
                    </div>
                    <div class="table-wrap" style="margin-top:12px;">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Identificacao</th>
                                    <td>
                                        Análise: <?php echo htmlspecialchars((string) ($formIdentification['numero_analise'] ?? '-')); ?> |
                                        Data/Hora: <?php echo htmlspecialchars(trim((string) (($formIdentification['data'] ?? '-') . ' ' . ($formIdentification['hora'] ?? '-')))); ?> |
                                        Responsavel: <?php echo htmlspecialchars((string) ($formIdentification['responsavel'] ?? '-')); ?> |
                                        Origem: <?php echo htmlspecialchars((string) ($formIdentification['origem_imagem'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Material examinado</th>
                                    <td>
                                        Arquivos: <?php echo (int) ($formMaterial['count'] ?? 0); ?> |
                                        Itens: <?php echo htmlspecialchars(is_array($formMaterial['items'] ?? null) ? implode(', ', array_map(function ($item) {
                                                    return is_array($item) ? ((string) ($item['label'] ?? '-')) . '=' . (!empty($item['available']) ? 'Sim' : 'Não') : '';
                                                }, $formMaterial['items'])) : '-'); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Qualidade</th>
                                    <td>
                                        Classe: <?php echo htmlspecialchars(humanizePericialLabel($formQuality['class'] ?? 'D')); ?> |
                                        Faixa: <?php echo htmlspecialchars(humanizePericialLabel($formQuality['label'] ?? '-')); ?> |
                                        Condições: <?php echo htmlspecialchars(is_array($formQuality['conditions'] ?? null) ? implode('; ', array_map('strval', $formQuality['conditions'])) : '-'); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>OCR</th>
                                    <td>
                                        Principal: <?php echo htmlspecialchars((string) ($formOcr['main'] ?? '-')); ?> |
                                        Parcial: <?php echo htmlspecialchars((string) ($formOcr['plate_partial'] ?? '-')); ?> |
                                        Fragmentos: <?php echo (int) ($formOcr['partial_candidates_count'] ?? 0); ?> |
                                        Resumo: <?php echo htmlspecialchars((string) ($formOcr['partial_summary'] ?? '-')); ?> |
                                        Padrão: <?php echo htmlspecialchars((string) ($formOcr['pattern'] ?? '-')); ?> |
                                        Confiança: <?php echo number_format((float) ($formOcr['confidence'] ?? 0), 1, ',', '.'); ?>%
                                    </td>
                                </tr>
                                <tr>
                                    <th>Classificação</th>
                                    <td>
                                        Tipo: <?php echo htmlspecialchars((string) ($formClassification['tipo'] ?? '-')); ?> |
                                        Porte: <?php echo htmlspecialchars((string) ($formClassification['porte'] ?? '-')); ?> |
                                        Cor: <?php echo htmlspecialchars((string) ($formClassification['cor'] ?? '-')); ?> |
                                        Placa: <?php echo htmlspecialchars((string) ($formClassification['placa_posicao'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Hipótese principal</th>
                                    <td>
                                        <?php echo htmlspecialchars(trim((string) (($formHypothesis['fabricante'] ?? '-') . ' ' . ($formHypothesis['modelo'] ?? '-')))); ?> |
                                        Versão: <?php echo htmlspecialchars((string) ($formHypothesis['versao'] ?? '-')); ?> |
                                        Geração: <?php echo htmlspecialchars((string) ($formHypothesis['geracao'] ?? '-')); ?> |
                                        Faixa ano: <?php echo htmlspecialchars((string) ($formHypothesis['faixa_ano'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Cruzamento OCR</th>
                                    <td>
                                        Placa parcial: <?php echo htmlspecialchars((string) ($formCross['placa_parcial'] ?? '-')); ?> |
                                        Padrão: <?php echo htmlspecialchars((string) ($formCross['padrao'] ?? '-')); ?> |
                                        Compatibilidade: <?php echo htmlspecialchars(humanizePericialLabel($formCross['compatibility'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Matriz</th>
                                    <td>
                                        Score: <?php echo number_format((float) ($formMatrix['pontuacao_final'] ?? 0), 1, ',', '.'); ?>/100 |
                                        Interpretação: <?php echo htmlspecialchars(humanizePericialLabel($formMatrix['interpretacao'] ?? '-')); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Conclusão</th>
                                    <td><?php echo htmlspecialchars((string) ($formConclusion['texto'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Encerramento</th>
                                    <td>
                                        Responsável: <?php echo htmlspecialchars((string) ($formClosing['responsavel_preenchimento'] ?? '-')); ?> |
                                        Cargo: <?php echo htmlspecialchars((string) ($formClosing['cargo_funcao'] ?? '-')); ?>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <p class="muted" style="margin-top:10px;">
                        Frente: <?php echo htmlspecialchars(humanizePericialLabel($formFront['compatibility'] ?? '-')); ?> |
                        Traseira: <?php echo htmlspecialchars(humanizePericialLabel($formRear['compatibility'] ?? '-')); ?> |
                        Lateral: <?php echo htmlspecialchars(humanizePericialLabel($formSide['compatibility'] ?? '-')); ?> |
                        Rodas: <?php echo htmlspecialchars(humanizePericialLabel($formWheels['compatibility'] ?? '-')); ?> |
                        Interior: <?php echo htmlspecialchars(humanizePericialLabel($formInternal['compatibility'] ?? '-')); ?>
                    </p>
                    <?php if (!empty($formAlternatives) && is_array($formAlternatives)) { ?>
                        <p class="muted">Hipóteses alternativas: <?php echo htmlspecialchars(implode(' | ', array_map('strval', $formAlternatives))); ?></p>
                    <?php } ?>
                    <?php if (!empty($formFavorable) && is_array($formFavorable)) { ?>
                        <p class="muted">Elementos favoraveis: <?php echo htmlspecialchars(implode(' | ', array_map('strval', array_slice($formFavorable, 0, 6)))); ?></p>
                    <?php } ?>
                    <?php if (!empty($formExclusion) && is_array($formExclusion)) { ?>
                        <p class="muted">Elementos excludentes: <?php echo htmlspecialchars(implode(' | ', array_map('strval', array_slice($formExclusion, 0, 6)))); ?></p>
                    <?php } ?>
                    <?php if (!empty($formChecklist) && is_array($formChecklist)) { ?>
                        <p class="muted">Checklist rapido: <?php
                                                            $checkLines = [];
                                                            foreach ($formChecklist as $checkItem) {
                                                                if (!is_array($checkItem)) {
                                                                    continue;
                                                                }
                                                                $checkLines[] = (string) ($checkItem['label'] ?? '-') . '=' . humanizePericialLabel($checkItem['status'] ?? '-');
                                                            }
                                                            echo htmlspecialchars($checkLines ? implode(' | ', $checkLines) : '-');
                                                            ?></p>
                    <?php } ?>
                </section>
            <?php } ?>

            <?php if ($assistedVehicleIdentification) { ?>
                <?php
                $assistedStatus = (string) ($assistedVehicleIdentification['status'] ?? 'indefinido');
                $assistedLabel = trim((string) ($assistedVehicleIdentification['label'] ?? 'Indeterminado'));
                $assistedSystems = is_array($assistedVehicleIdentification['supporting_systems'] ?? null) ? $assistedVehicleIdentification['supporting_systems'] : [];
                $assistedAlternatives = is_array($assistedVehicleIdentification['alternatives'] ?? null) ? $assistedVehicleIdentification['alternatives'] : [];
                ?>
                <section class="card">
                    <h2 class="card-title">Identificação visual assistida</h2>
                    <p class="card-subtitle">
                        Camada complementar de apoio técnico, com revisão humana obrigatória e sem valor autônomo de conclusão.
                    </p>
                    <div class="grid">
                        <div class="col-4 kpi">
                            <p class="kpi-label">Hipótese principal</p>
                            <p class="kpi-value"><?php echo htmlspecialchars($assistedLabel !== '' ? $assistedLabel : 'Indeterminado'); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Status</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($assistedStatus)); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Confiança estimada</p>
                            <p class="kpi-value"><?php echo number_format((float) ($assistedVehicleIdentification['confidence'] ?? 0), 1, ',', '.'); ?>%</p>
                        </div>
                    </div>
                    <div class="table-wrap" style="margin-top:12px;">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Corroboração externa</th>
                                    <td><?php echo !empty($assistedVehicleIdentification['corroborated']) ? 'Sim' : 'Não'; ?></td>
                                </tr>
                                <tr>
                                    <th>Revisão humana</th>
                                    <td><?php echo !empty($assistedVehicleIdentification['manual_review_required']) ? 'Obrigatória' : 'Dispensável'; ?></td>
                                </tr>
                                <tr>
                                    <th>Cor inferida</th>
                                    <td><?php echo htmlspecialchars((string) ($assistedVehicleIdentification['cor'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Ano / faixa</th>
                                    <td><?php echo htmlspecialchars((string) ($assistedVehicleIdentification['ano'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Carroceria</th>
                                    <td><?php echo htmlspecialchars((string) ($assistedVehicleIdentification['tipo_carroceria'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Vista analisada</th>
                                    <td><?php echo htmlspecialchars((string) ($assistedVehicleIdentification['vista_detectada'] ?? 'indefinida')); ?></td>
                                </tr>
                                <tr>
                                    <th>Sistemas de apoio</th>
                                    <td><?php echo (int) ($assistedVehicleIdentification['supporting_systems_count'] ?? 0); ?></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <?php if (!empty($assistedVehicleIdentification['statement'])) { ?>
                        <p class="muted" style="margin-top:10px;"><?php echo htmlspecialchars((string) $assistedVehicleIdentification['statement']); ?></p>
                    <?php } ?>
                    <?php if ($assistedSystems) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Sistema</th>
                                        <th>Hipótese</th>
                                        <th>Confiança</th>
                                        <th>Corrobora local</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($assistedSystems, 0, 4) as $systemItem) { ?>
                                        <?php if (!is_array($systemItem)) {
                                            continue;
                                        } ?>
                                        <?php
                                        $systemVehicle = trim((string) (($systemItem['fabricante'] ?? '') . ' ' . ($systemItem['modelo'] ?? '')));
                                        if ($systemVehicle === '') {
                                            $systemVehicle = 'Indeterminado';
                                        }
                                        ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($systemItem['nome'] ?? $systemItem['id'] ?? 'sistema_externo')); ?></td>
                                            <td><?php echo htmlspecialchars($systemVehicle); ?></td>
                                            <td><?php echo number_format((float) ($systemItem['vehicle_confidence'] ?? 0), 1, ',', '.'); ?>%</td>
                                            <td><?php echo !empty($systemItem['matches_local_vehicle']) ? 'Sim' : 'Não'; ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if ($assistedAlternatives) { ?>
                        <p class="muted" style="margin-top:10px;">Hipóteses alternativas: <?php
                                                                                            $altLines = [];
                                                                                            foreach (array_slice($assistedAlternatives, 0, 3) as $altItem) {
                                                                                                if (!is_array($altItem)) {
                                                                                                    continue;
                                                                                                }
                                                                                                $altLabel = (string) ($altItem['label'] ?? '-');
                                                                                                $altConf = number_format((float) ($altItem['confidence'] ?? 0), 1, ',', '.');
                                                                                                $altYear = trim((string) ($altItem['year_range'] ?? ''));
                                                                                                $altLine = $altLabel . ' (' . $altConf . '%)';
                                                                                                if ($altYear !== '') {
                                                                                                    $altLine .= ' ano ' . $altYear;
                                                                                                }
                                                                                                $altLines[] = $altLine;
                                                                                            }
                                                                                            echo htmlspecialchars($altLines ? implode(' | ', $altLines) : '-');
                                                                                            ?></p>
                    <?php } ?>
                </section>
            <?php } ?>

            <?php if ($visualProfile) { ?>
                <section class="card">
                    <h2 class="card-title">Perfil visual do veículo (hipótese técnica)</h2>
                    <?php
                    $visualMain = is_array($visualProfile['hipotese_principal'] ?? null) ? $visualProfile['hipotese_principal'] : [];
                    $visualMainRaw = is_array($visualProfile['hipotese_principal_bruta'] ?? null) ? $visualProfile['hipotese_principal_bruta'] : [];
                    $visualModelQuality = is_array($visualProfile['qualidade_modelo'] ?? null) ? $visualProfile['qualidade_modelo'] : [];
                    $visualList = is_array($visualProfile['hipoteses'] ?? null) ? $visualProfile['hipoteses'] : [];
                    $visualSources = is_array($visualProfile['fontes'] ?? null) ? $visualProfile['fontes'] : [];
                    $visualAltColors = is_array($visualProfile['cores_alternativas'] ?? null) ? $visualProfile['cores_alternativas'] : [];
                    $visualRear = is_array($visualProfile['lanterna_traseira'] ?? null) ? $visualProfile['lanterna_traseira'] : [];
                    $visualComponentsProfile = is_array($visualProfile['assinaturas_componentes'] ?? null) ? $visualProfile['assinaturas_componentes'] : [];
                    $visualComponents = is_array($visualComponentsProfile['componentes'] ?? null) ? $visualComponentsProfile['componentes'] : [];
                    $visualComparison = is_array($visualProfile['comparativo_fontes_abertas'] ?? null) ? $visualProfile['comparativo_fontes_abertas'] : [];
                    $visualComparisonSources = is_array($visualComparison['fontes'] ?? null) ? $visualComparison['fontes'] : [];
                    $visualComparisonFamilies = is_array($visualComparison['familias_fontes'] ?? null) ? $visualComparison['familias_fontes'] : [];
                    $visualComponentQueries = is_array($visualComparison['consultas_componentes'] ?? null) ? $visualComparison['consultas_componentes'] : [];
                    $visualFeatureQueries = is_array($visualComparison['consultas_caracteristicas'] ?? null) ? $visualComparison['consultas_caracteristicas'] : [];
                    $visualSearchEngines = is_array($visualComparison['motores_busca_utilizados'] ?? null) ? $visualComparison['motores_busca_utilizados'] : [];
                    $visualAnalysisEngines = is_array($visualComparison['motores_analise_utilizados'] ?? null) ? $visualComparison['motores_analise_utilizados'] : [];
                    $visualReferenceSystems = is_array($visualComparison['sistemas_referencia'] ?? null) ? $visualComparison['sistemas_referencia'] : [];
                    $visualCriteria = is_array($visualComparison['criterios_individualizacao'] ?? null) ? $visualComparison['criterios_individualizacao'] : [];
                    $visualChecklist = is_array($visualComparison['checklist_pericial'] ?? null) ? $visualComparison['checklist_pericial'] : [];
                    $visualForensic = is_array($visualProfile['caracteristicas_forenses'] ?? null) ? $visualProfile['caracteristicas_forenses'] : [];
                    $visualForensicFindings = is_array($visualForensic['achados'] ?? null) ? $visualForensic['achados'] : [];
                    $visualEvidenceMatrix = is_array($visualProfile['matriz_evidencias'] ?? null) ? $visualProfile['matriz_evidencias'] : [];
                    $visualStatus = (string) ($visualProfile['status'] ?? 'indefinido');
                    ?>
                    <div class="grid">
                        <div class="col-4 kpi">
                            <p class="kpi-label">Status</p>
                            <p class="kpi-value"><?php echo htmlspecialchars(humanizePericialLabel($visualStatus)); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Cor provável</p>
                            <p class="kpi-value"><?php echo htmlspecialchars((string) ($visualProfile['cor_probavel'] ?? 'indefinida')); ?></p>
                        </div>
                        <div class="col-4 kpi">
                            <p class="kpi-label">Confiança da cor</p>
                            <p class="kpi-value"><?php echo number_format((float) ($visualProfile['confianca_cor'] ?? 0), 1, ',', '.'); ?>%</p>
                        </div>
                    </div>
                    <div class="table-wrap" style="margin-top:12px;">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Fabricante da hipótese</th>
                                    <td><?php echo htmlspecialchars((string) ($visualMain['fabricante'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Modelo da hipótese</th>
                                    <td><?php echo htmlspecialchars((string) ($visualMain['modelo'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Modelo bruto (pré-calibração)</th>
                                    <td><?php echo htmlspecialchars((string) ($visualMainRaw['modelo'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Qualidade da decisão de modelo</th>
                                    <td>
                                        Status: <?php echo htmlspecialchars(humanizePericialLabel($visualModelQuality['status'] ?? 'indefinido')); ?> |
                                        Abstenção: <?php echo !empty($visualModelQuality['model_abstained']) ? 'Sim' : 'Não'; ?> |
                                        Margem top2: <?php echo number_format((float) ($visualModelQuality['confidence_margin_top2'] ?? 0), 1, ',', '.'); ?> |
                                        Evidencias discriminativas: <?php echo htmlspecialchars((string) ($visualModelQuality['discriminative_evidence_count'] ?? 0)); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Faixa ano/modelo</th>
                                    <td><?php echo htmlspecialchars((string) ($visualMain['faixa_ano_modelo'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Vista detectada</th>
                                    <td><?php echo htmlspecialchars((string) ($visualProfile['vista_detectada'] ?? 'indefinida')); ?></td>
                                </tr>
                                <tr>
                                    <th>Lanterna traseira vertical</th>
                                    <td>
                                        <?php
                                        if (array_key_exists('vertical_pair', $visualRear)) {
                                            echo !empty($visualRear['vertical_pair']) ? 'Sim' : 'Não';
                                        } else {
                                            echo '-';
                                        }
                                        ?>
                                        | Confiança: <?php echo number_format((float) ($visualRear['confidence'] ?? 0), 1, ',', '.'); ?>%
                                    </td>
                                </tr>
                                <tr>
                                    <th>Assinaturas detectadas</th>
                                    <td>
                                        <?php
                                        $componentDetected = (int) ($visualComponentsProfile['itens_detectados'] ?? 0);
                                        $componentTotal = (int) ($visualComponentsProfile['itens_avaliados'] ?? 0);
                                        $componentCoverage = (float) ($visualComponentsProfile['cobertura_percentual'] ?? 0);
                                        echo htmlspecialchars((string) $componentDetected . '/' . (string) $componentTotal);
                                        ?>
                                        | Cobertura: <?php echo number_format($componentCoverage, 1, ',', '.'); ?>%
                                    </td>
                                </tr>
                                <tr>
                                    <th>Características forenses</th>
                                    <td>
                                        Status: <?php echo htmlspecialchars(humanizePericialLabel($visualForensic['status'] ?? 'indefinido')); ?> |
                                        Achados: <?php echo htmlspecialchars((string) ($visualForensic['total_achados'] ?? 0)); ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Cores alternativas</th>
                                    <td><?php
                                        $colorLines = [];
                                        foreach ($visualAltColors as $entry) {
                                            if (!is_array($entry)) {
                                                continue;
                                            }
                                            $colorLines[] = (string) ($entry['name'] ?? '-') . ': ' . number_format((float) ($entry['ratio'] ?? 0), 1, ',', '.') . '%';
                                        }
                                        echo htmlspecialchars($colorLines ? implode(' | ', $colorLines) : '-');
                                        ?></td>
                                </tr>
                                <tr>
                                    <th>Confiança da hipótese</th>
                                    <td><?php echo number_format((float) ($visualMain['confianca'] ?? 0), 1, ',', '.'); ?>%</td>
                                </tr>
                                <tr>
                                    <th>Fontes</th>
                                    <td><?php echo htmlspecialchars($visualSources ? implode(' | ', array_map('strval', $visualSources)) : '-'); ?></td>
                                </tr>
                                <tr>
                                    <th>Motores de busca</th>
                                    <td><?php echo htmlspecialchars($visualSearchEngines ? implode(' | ', array_map('strval', $visualSearchEngines)) : '-'); ?></td>
                                </tr>
                                <tr>
                                    <th>Motores de análise</th>
                                    <td><?php echo htmlspecialchars($visualAnalysisEngines ? implode(' | ', array_map('strval', $visualAnalysisEngines)) : '-'); ?></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <?php if ($visualList && empty($visualModelQuality['model_abstained']) && strtolower((string) ($visualMain['modelo'] ?? '')) !== 'nao conclusivo') { ?>
                        <p class="muted" style="margin-top:10px;">Top hipóteses:
                            <?php
                            $visualLines = [];
                            foreach ($visualList as $entry) {
                                if (!is_array($entry)) {
                                    continue;
                                }
                                $line = trim((string) (($entry['fabricante'] ?? '') . ' ' . ($entry['modelo'] ?? '')));
                                $line .= ' (' . number_format((float) ($entry['confianca'] ?? 0), 1, ',', '.') . '%)';
                                if (!empty($entry['faixa_ano_modelo'])) {
                                    $line .= ' ano ' . (string) $entry['faixa_ano_modelo'];
                                }
                                $visualLines[] = $line;
                            }
                            echo htmlspecialchars($visualLines ? implode(' ; ', $visualLines) : '-');
                            ?>
                        </p>
                    <?php } elseif (!empty($visualModelQuality['model_abstained'])) { ?>
                        <p class="muted" style="margin-top:10px;">Hipóteses visuais retidas por abstenção pericial.</p>
                    <?php } ?>
                    <?php if ($visualComponents) { ?>
                        <?php
                        $componentLabels = [
                            'emblema_frontal' => 'Emblema frontal',
                            'grade_dianteira' => 'Grade dianteira',
                            'farois_dianteiros' => 'Farois dianteiros',
                            'lanternas_traseiras' => 'Lanternas traseiras',
                            'linhas_portas' => 'Linhas de portas',
                            'capo_dianteiro' => 'Capo dianteiro',
                            'tampa_traseira' => 'Tampa traseira',
                            'design_carroceria' => 'Design de carroceria',
                        ];
                        ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Componente</th>
                                        <th>Status</th>
                                        <th>Confiança</th>
                                        <th>Detalhe técnico</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach ($componentLabels as $componentKey => $componentLabel) { ?>
                                        <?php
                                        $componentItem = is_array($visualComponents[$componentKey] ?? null) ? $visualComponents[$componentKey] : null;
                                        if (!$componentItem) {
                                            continue;
                                        }
                                        ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars($componentLabel); ?></td>
                                            <td><?php echo htmlspecialchars(humanizePericialLabel($componentItem['status'] ?? 'indefinido')); ?></td>
                                            <td><?php echo number_format((float) ($componentItem['confianca'] ?? 0), 1, ',', '.'); ?>%</td>
                                            <td><?php echo htmlspecialchars((string) ($componentItem['detalhe'] ?? '-')); ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if ($visualEvidenceMatrix && is_array($visualEvidenceMatrix['candidates'] ?? null)) { ?>
                        <?php $visualMatrixCandidates = $visualEvidenceMatrix['candidates']; ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Matriz de evidencias</th>
                                        <th>Conf.</th>
                                        <th>Ano</th>
                                        <th>Apoio principal</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualMatrixCandidates, 0, 3) as $matrixCandidate) { ?>
                                        <?php if (!is_array($matrixCandidate)) {
                                            continue;
                                        } ?>
                                        <?php
                                        $matrixRows = is_array($matrixCandidate['rows'] ?? null) ? $matrixCandidate['rows'] : [];
                                        $matrixTopEvidence = '-';
                                        if ($matrixRows) {
                                            $firstRow = $matrixRows[0];
                                            if (is_array($firstRow)) {
                                                $matrixTopEvidence = trim((string) ($firstRow['evidencia'] ?? $firstRow['descricao'] ?? '-'));
                                                $matrixTopWeight = number_format((float) ($firstRow['peso_nominal'] ?? 0), 1, ',', '.');
                                                $matrixTopEvidence .= ' (' . $matrixTopWeight . ')';
                                            }
                                        }
                                        ?>
                                        <tr>
                                            <td>
                                                <?php echo htmlspecialchars(trim((string) ($matrixCandidate['fabricante'] ?? '-')) . ' ' . trim((string) ($matrixCandidate['modelo'] ?? '-'))); ?>
                                                <div class="muted">
                                                    <?php echo htmlspecialchars(humanizePericialLabel($matrixCandidate['status'] ?? 'indefinido')); ?>
                                                </div>
                                            </td>
                                            <td><?php echo number_format((float) ($matrixCandidate['confianca'] ?? 0), 1, ',', '.'); ?>%</td>
                                            <td><?php echo htmlspecialchars((string) ($matrixCandidate['faixa_ano_modelo'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars($matrixTopEvidence); ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                        <?php if (!empty($visualEvidenceMatrix['summary']) && is_array($visualEvidenceMatrix['summary'])) { ?>
                            <p class="muted" style="margin-top:8px;"><?php echo htmlspecialchars(implode(' | ', array_map('strval', array_slice($visualEvidenceMatrix['summary'], 0, 3)))); ?></p>
                        <?php } ?>
                    <?php } ?>
                    <?php if ($visualForensicFindings) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Código</th>
                                        <th>Descrição</th>
                                        <th>Confiança</th>
                                        <th>Localizacao</th>
                                        <th>Evidencia</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualForensicFindings, 0, 8) as $findingItem) { ?>
                                        <?php if (!is_array($findingItem)) {
                                            continue;
                                        } ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($findingItem['codigo'] ?? 'achado_visual')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($findingItem['descricao'] ?? '-')); ?></td>
                                            <td><?php echo number_format((float) ($findingItem['confianca'] ?? 0), 1, ',', '.'); ?>%</td>
                                            <td><?php echo htmlspecialchars((string) ($findingItem['localizacao'] ?? 'indefinida')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($findingItem['evidencia'] ?? '-')); ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if (!empty($visualComparison['consulta_principal'])) { ?>
                        <p class="muted" style="margin-top:10px;">Consulta principal: <?php echo htmlspecialchars((string) $visualComparison['consulta_principal']); ?></p>
                    <?php } ?>
                    <?php if (!empty($visualComparison['modelo_alvo'])) { ?>
                        <p class="muted" style="margin-top:6px;">
                            Alvo comparativo aberto: <?php echo htmlspecialchars((string) $visualComparison['modelo_alvo']); ?>
                            <?php
                            $ajusteAtivo = !empty($visualComparison['modelo_alvo_ajustado']);
                            $ajusteMotivo = (string) ($visualComparison['modelo_alvo_ajuste_motivo'] ?? '');
                            if ($ajusteAtivo) {
                                echo ' | ajuste: ' . htmlspecialchars($ajusteMotivo ?: 'heuristica');
                            }
                            ?>
                        </p>
                    <?php } ?>
                    <?php if ($visualChecklist) { ?>
                        <p class="muted" style="margin-top:10px;">Checklist comparativo: <?php echo htmlspecialchars(implode(' | ', array_map('strval', $visualChecklist))); ?></p>
                    <?php } ?>
                    <?php if ($visualCriteria) { ?>
                        <p class="muted" style="margin-top:10px;">Critérios de individualização: <?php echo htmlspecialchars(implode(' | ', array_map('strval', $visualCriteria))); ?></p>
                    <?php } ?>
                    <?php if ($visualComponentQueries) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Componente</th>
                                        <th>Status</th>
                                        <th>Consulta</th>
                                        <th>Fontes sugeridas</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualComponentQueries, 0, 8) as $queryItem) { ?>
                                        <?php
                                        if (!is_array($queryItem)) {
                                            continue;
                                        }
                                        $querySources = is_array($queryItem['fontes'] ?? null) ? $queryItem['fontes'] : [];
                                        $queryLinks = [];
                                        foreach (array_slice($querySources, 0, 3) as $sourceRef) {
                                            if (!is_array($sourceRef)) {
                                                continue;
                                            }
                                            $sourceUrl = (string) ($sourceRef['url'] ?? '');
                                            $sourceName = (string) ($sourceRef['fonte'] ?? '-');
                                            if ($sourceUrl !== '') {
                                                $queryLinks[] = '<a href="' . htmlspecialchars($sourceUrl) . '" target="_blank" rel="noopener noreferrer">' . htmlspecialchars($sourceName) . '</a>';
                                            }
                                        }
                                        ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($queryItem['rotulo'] ?? $queryItem['componente'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars(humanizePericialLabel($queryItem['status'] ?? 'indefinido')); ?> (<?php echo number_format((float) ($queryItem['confianca'] ?? 0), 1, ',', '.'); ?>%)</td>
                                            <td><?php echo htmlspecialchars((string) ($queryItem['consulta'] ?? '-')); ?></td>
                                            <td><?php echo $queryLinks ? implode(' | ', $queryLinks) : '-'; ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if ($visualFeatureQueries) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Caracteristica</th>
                                        <th>Localizacao</th>
                                        <th>Consulta</th>
                                        <th>Fontes sugeridas</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualFeatureQueries, 0, 8) as $featureItem) { ?>
                                        <?php
                                        if (!is_array($featureItem)) {
                                            continue;
                                        }
                                        $featureSources = is_array($featureItem['fontes'] ?? null) ? $featureItem['fontes'] : [];
                                        $featureLinks = [];
                                        foreach (array_slice($featureSources, 0, 3) as $sourceRef) {
                                            if (!is_array($sourceRef)) {
                                                continue;
                                            }
                                            $sourceUrl = (string) ($sourceRef['url'] ?? '');
                                            $sourceName = (string) ($sourceRef['fonte'] ?? '-');
                                            if ($sourceUrl !== '') {
                                                $featureLinks[] = '<a href="' . htmlspecialchars($sourceUrl) . '" target="_blank" rel="noopener noreferrer">' . htmlspecialchars($sourceName) . '</a>';
                                            }
                                        }
                                        ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($featureItem['descricao'] ?? $featureItem['caracteristica'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($featureItem['localizacao'] ?? 'indefinida')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($featureItem['consulta'] ?? '-')); ?></td>
                                            <td><?php echo $featureLinks ? implode(' | ', $featureLinks) : '-'; ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if ($visualComparisonSources) { ?>
                        <p class="muted" style="margin-top:10px;">
                            Famílias consultadas: <?php
                                                    $familyLines = [];
                                                    foreach ($visualComparisonFamilies as $familyName => $familyCount) {
                                                        if (!is_scalar($familyName)) {
                                                            continue;
                                                        }
                                                        $familyLines[] = (string) $familyName . '=' . (int) $familyCount;
                                                    }
                                                    echo htmlspecialchars($familyLines ? implode(' | ', $familyLines) : '-');
                                                    ?>
                        </p>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Fonte aberta</th>
                                        <th>Objetivo</th>
                                        <th>Link</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualComparisonSources, 0, 12) as $sourceItem) { ?>
                                        <?php if (!is_array($sourceItem)) {
                                            continue;
                                        } ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($sourceItem['fonte'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($sourceItem['objetivo'] ?? '-')); ?></td>
                                            <td>
                                                <?php $srcUrl = (string) ($sourceItem['url'] ?? ''); ?>
                                                <?php if ($srcUrl !== '') { ?>
                                                    <a href="<?php echo htmlspecialchars($srcUrl); ?>" target="_blank" rel="noopener noreferrer"><?php echo htmlspecialchars($srcUrl); ?></a>
                                                <?php } else { ?>
                                                    -
                                                <?php } ?>
                                            </td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <?php if ($visualReferenceSystems) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Sistema de referencia</th>
                                        <th>Categoria</th>
                                        <th>Integracao local</th>
                                        <th>Link</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($visualReferenceSystems, 0, 8) as $refSystem) { ?>
                                        <?php if (!is_array($refSystem)) {
                                            continue;
                                        } ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($refSystem['sistema'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($refSystem['categoria'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($refSystem['integracao_local'] ?? '-')); ?></td>
                                            <td>
                                                <?php $refUrl = (string) ($refSystem['url'] ?? ''); ?>
                                                <?php if ($refUrl !== '') { ?>
                                                    <a href="<?php echo htmlspecialchars($refUrl); ?>" target="_blank" rel="noopener noreferrer"><?php echo htmlspecialchars($refUrl); ?></a>
                                                <?php } else { ?>
                                                    -
                                                <?php } ?>
                                            </td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                    <p class="muted">Observação: perfil visual e hipótese técnica de apoio; exige validação humana e cruzamento com outras provas.</p>
                </section>
            <?php } ?>

            <?php if ($externalSystemsComparison) { ?>
                <section class="card">
                    <h2 class="card-title">Comparativo com sistemas externos</h2>
                    <p class="card-subtitle">
                        Status: <strong><?php echo htmlspecialchars(humanizePericialLabel($externalSystemsComparison['status'] ?? 'indefinido')); ?></strong>
                        <?php if (!empty($externalSystemsComparison['message'])) { ?>
                            | <?php echo htmlspecialchars((string) $externalSystemsComparison['message']); ?>
                        <?php } ?>
                    </p>
                    <div class="kpi-grid">
                        <article class="kpi-card">
                            <span class="kpi-label">Catalogados</span>
                            <strong class="kpi-value"><?php echo (int) ($externalSystemsSummary['sistemas_catalogados'] ?? count($externalSystemsCatalog)); ?></strong>
                        </article>
                        <article class="kpi-card">
                            <span class="kpi-label">Executados</span>
                            <strong class="kpi-value"><?php echo (int) ($externalSystemsSummary['sistemas_executados'] ?? 0); ?></strong>
                        </article>
                        <article class="kpi-card">
                            <span class="kpi-label">Resultados validos</span>
                            <strong class="kpi-value"><?php echo (int) ($externalSystemsSummary['sistemas_ok'] ?? 0); ?></strong>
                        </article>
                        <article class="kpi-card">
                            <span class="kpi-label">Placa compativel</span>
                            <strong class="kpi-value"><?php echo (int) ($externalSystemsSummary['placa_compativel_ocr'] ?? 0); ?></strong>
                        </article>
                    </div>
                    <p class="muted" style="margin-top:8px;">
                        Concordância placa/veículo:
                        <?php echo number_format((float) ($externalSystemsSummary['taxa_concordancia_placa'] ?? 0), 1, ',', '.'); ?>%
                        /
                        <?php echo number_format((float) ($externalSystemsSummary['taxa_concordancia_veiculo'] ?? 0), 1, ',', '.'); ?>%
                    </p>

                    <?php if ($externalSystemsRuns) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Sistema</th>
                                        <th>Status</th>
                                        <th>Placa</th>
                                        <th>Confiança</th>
                                        <th>Compatível OCR</th>
                                        <th>Compatível Visual</th>
                                        <th>Veículo inferido</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach ($externalSystemsRuns as $systemRun) { ?>
                                        <?php
                                        if (!is_array($systemRun)) {
                                            continue;
                                        }
                                        $vehicleRun = is_array($systemRun['vehicle'] ?? null) ? $systemRun['vehicle'] : [];
                                        $makeRun = trim((string) ($vehicleRun['fabricante'] ?? ''));
                                        $modelRun = trim((string) ($vehicleRun['modelo'] ?? ''));
                                        $vehicleLabel = trim($makeRun . ' ' . $modelRun);
                                        if ($vehicleLabel === '') {
                                            $vehicleLabel = '-';
                                        }
                                        $plateMatchValue = $systemRun['matches_internal_plate'] ?? null;
                                        $vehicleMatchValue = $systemRun['matches_internal_vehicle'] ?? null;
                                        $plateMatchText = $plateMatchValue === true ? 'Sim' : ($plateMatchValue === false ? 'Não' : 'N/A');
                                        $vehicleMatchText = $vehicleMatchValue === true ? 'Sim' : ($vehicleMatchValue === false ? 'Não' : 'N/A');
                                        ?>
                                        <tr>
                                            <td>
                                                <?php echo htmlspecialchars((string) ($systemRun['nome'] ?? $systemRun['id'] ?? 'sistema_externo')); ?>
                                                <?php if (!empty($systemRun['source_url'])) { ?>
                                                    <div class="muted">
                                                        <a href="<?php echo htmlspecialchars((string) $systemRun['source_url']); ?>" target="_blank" rel="noopener noreferrer">fonte</a>
                                                    </div>
                                                <?php } ?>
                                            </td>
                                            <td><?php echo htmlspecialchars(humanizePericialLabel($systemRun['status'] ?? 'indefinido')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($systemRun['plate'] ?? '-')); ?></td>
                                            <td><?php echo number_format((float) ($systemRun['plate_confidence'] ?? 0), 1, ',', '.'); ?>%</td>
                                            <td><?php echo htmlspecialchars($plateMatchText); ?></td>
                                            <td><?php echo htmlspecialchars($vehicleMatchText); ?></td>
                                            <td><?php echo htmlspecialchars($vehicleLabel); ?></td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>

                    <?php if ($externalSystemsCatalog) { ?>
                        <div class="table-wrap" style="margin-top:12px;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Referência</th>
                                        <th>Categoria</th>
                                        <th>Modo local</th>
                                        <th>Link</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach (array_slice($externalSystemsCatalog, 0, 8) as $catalogItem) { ?>
                                        <?php if (!is_array($catalogItem)) {
                                            continue;
                                        } ?>
                                        <tr>
                                            <td><?php echo htmlspecialchars((string) ($catalogItem['nome'] ?? $catalogItem['id'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($catalogItem['categoria'] ?? '-')); ?></td>
                                            <td><?php echo htmlspecialchars((string) ($catalogItem['integracao_local'] ?? '-')); ?></td>
                                            <td>
                                                <?php $catalogUrl = (string) ($catalogItem['source_url'] ?? ''); ?>
                                                <?php if ($catalogUrl !== '') { ?>
                                                    <a href="<?php echo htmlspecialchars($catalogUrl); ?>" target="_blank" rel="noopener noreferrer"><?php echo htmlspecialchars($catalogUrl); ?></a>
                                                <?php } else { ?>
                                                    -
                                                <?php } ?>
                                            </td>
                                        </tr>
                                    <?php } ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>
                </section>
            <?php } ?>

            <?php if ($topCandidates) { ?>
                <section class="card">
                    <h2 class="card-title">Top candidatos da placa</h2>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Texto</th>
                                    <th>Score</th>
                                    <th>Confiança</th>
                                    <th>Padrao</th>
                                    <th>Regiao</th>
                                    <th>Engine</th>
                                </tr>
                            </thead>
                            <tbody>
                                <?php foreach ($topCandidates as $candidate) { ?>
                                    <tr>
                                        <td><?php echo htmlspecialchars((string) ($candidate['text'] ?? '-')); ?></td>
                                        <td><?php echo number_format((float) ($candidate['score'] ?? 0), 1, ',', '.'); ?></td>
                                        <td><?php echo number_format((float) ($candidate['avg_conf'] ?? 0), 1, ',', '.'); ?>%</td>
                                        <td><?php echo htmlspecialchars((string) ($candidate['pattern'] ?? 'Indefinido')); ?></td>
                                        <td><?php echo htmlspecialchars((string) ($candidate['region'] ?? '-')); ?></td>
                                        <td><?php echo htmlspecialchars((string) ($candidate['engine'] ?? '-')); ?></td>
                                    </tr>
                                <?php } ?>
                            </tbody>
                        </table>
                    </div>
                </section>
            <?php } ?>

            <?php if ($ocrEngines || $ocrEngineStatus) { ?>
                <section class="card">
                    <h2 class="card-title">Detalhamento por engine</h2>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Engine</th>
                                    <th>Status</th>
                                    <th>Motivo</th>
                                    <th>Texto</th>
                                    <th>Confiança</th>
                                    <th>Score</th>
                                    <th>Padrao</th>
                                </tr>
                            </thead>
                            <tbody>
                                <?php
                                $engineNames = array_values(array_unique(array_merge(array_keys($ocrEngines), array_keys($ocrEngineStatus))));
                                foreach ($engineNames as $engine) {
                                    $ocr = is_array($ocrEngines[$engine] ?? null) ? $ocrEngines[$engine] : [];
                                    $engineMeta = is_array($ocrEngineStatus[$engine] ?? null) ? $ocrEngineStatus[$engine] : [];
                                    $engineText = (string) ($ocr['text'] ?? '');
                                    $engineConf = (float) ($ocr['avg_conf'] ?? 0);
                                    $engineScore = (float) ($ocr['score'] ?? $engineConf);
                                    $enginePattern = (string) ($ocr['pattern'] ?? 'Indefinido');
                                    $engineState = humanizeEngineHealthLabel($engineMeta['status'] ?? ($engineText !== '' ? 'executed' : 'indefinido'));
                                    $engineReason = (string) ($engineMeta['reason'] ?? '-');
                                ?>
                                    <tr>
                                        <td><?php echo htmlspecialchars((string) $engine); ?></td>
                                        <td><?php echo htmlspecialchars($engineState); ?></td>
                                        <td><?php echo htmlspecialchars($engineReason); ?></td>
                                        <td><?php echo htmlspecialchars((string) $engineText); ?></td>
                                        <td><?php echo number_format($engineConf, 1, ',', '.'); ?>%</td>
                                        <td><?php echo number_format($engineScore, 1, ',', '.'); ?></td>
                                        <td><?php echo htmlspecialchars($enginePattern); ?></td>
                                    </tr>
                                <?php } ?>
                            </tbody>
                        </table>
                    </div>
                </section>
            <?php } ?>

            <?php if ($charOptions && !$best) { ?>
                <section class="card">
                    <h2 class="card-title">Caracteres com maior confianca</h2>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Caractere</th>
                                    <th>Confiança</th>
                                </tr>
                            </thead>
                            <tbody>
                                <?php foreach ($charOptions as $option) { ?>
                                    <tr>
                                        <td><?php echo htmlspecialchars((string) ($option[0] ?? '-')); ?></td>
                                        <td><?php echo number_format((float) ($option[1] ?? 0), 1, ',', '.'); ?>%</td>
                                    </tr>
                                <?php } ?>
                            </tbody>
                        </table>
                    </div>
                </section>
            <?php } ?>

            <section class="card">
                <h2 class="card-title">Situação documental</h2>
                <p class="card-subtitle">
                    Padrão da placa:
                    <strong><?php echo htmlspecialchars((string) $platePatternLabel); ?></strong>
                    | Adulteração:
                    <strong><?php echo !empty($result['adulteracao']) ? 'Sim' : 'Não'; ?></strong>
                </p>
                <div class="btn-row">
                    <?php if (!empty($result['pdf_report'])) { ?>
                        <a class="btn btn-primary" href="#analysisReport">Ver relatório</a>
                    <?php } ?>
                    <a class="btn btn-secondary" href="/">Voltar ao dashboard</a>
                </div>
            </section>

            <?php if ($veiculo) { ?>
                <section class="card">
                    <h2 class="card-title">Validação pós-placa e dados de veículo</h2>
                    <p class="card-subtitle">
                        Fonte principal:
                        <strong><?php echo htmlspecialchars((string) ($veiculoExibicao['fonte'] ?? 'provedor_externo')); ?></strong>
                        <?php if (!empty($officialVehicleValidation['status'])) { ?>
                            | Validação:
                            <strong><?php echo htmlspecialchars(humanizeOfficialValidationLabel($officialVehicleValidation['status'])); ?></strong>
                        <?php } ?>
                    </p>
                    <?php if ($zapayLookupShouldShow) { ?>
                        <div
                            id="zapayStatusPanel"
                            class="analysis-status-panel"
                            data-usezapay-panel="1"
                            data-usezapay-request-id="<?php echo htmlspecialchars($zapayLookupRequestId); ?>"
                            data-usezapay-plate="<?php echo htmlspecialchars($zapayLookupPlate); ?>"
                            data-usezapay-status="<?php echo htmlspecialchars($zapayLookupStatus); ?>">
                            <div class="analysis-status-header">
                                <div>
                                    <p class="muted" style="margin:0;">Monitoramento Zapay</p>
                                    <div id="zapayStatusChip" class="status-chip <?php echo htmlspecialchars($zapayLookupStateClass); ?>">
                                        <?php echo htmlspecialchars($zapayLookupStateLabel); ?>
                                    </div>
                                </div>
                                <button id="zapayRefreshBtn" class="btn btn-secondary" type="button">Atualizar status</button>
                            </div>
                            <div class="status-row">
                                <div class="status-box">
                                    <p class="status-box-label">Placa</p>
                                    <p id="zapayStatusPlate" class="status-box-value"><?php echo htmlspecialchars($zapayLookupPlate !== '' ? $zapayLookupPlate : '-'); ?></p>
                                </div>
                                <div class="status-box">
                                    <p class="status-box-label">Request ID</p>
                                    <p id="zapayStatusRequestId" class="status-box-value"><?php echo htmlspecialchars($zapayLookupRequestId !== '' ? $zapayLookupRequestId : '-'); ?></p>
                                </div>
                                <div class="status-box">
                                    <p class="status-box-label">Evento</p>
                                    <p id="zapayStatusEvent" class="status-box-value"><?php echo htmlspecialchars($zapayLookupEvent !== '' ? $zapayLookupEvent : '-'); ?></p>
                                </div>
                                <div class="status-box">
                                    <p class="status-box-label">Detalhe</p>
                                    <p id="zapayStatusDetail" class="status-box-value"><?php echo htmlspecialchars($zapayLookupDetail !== '' ? $zapayLookupDetail : '-'); ?></p>
                                </div>
                                <div class="status-box">
                                    <p class="status-box-label">Resumo</p>
                                    <p id="zapayStatusSummary" class="status-box-value"><?php echo htmlspecialchars($zapayLookupSummaryText !== '' ? $zapayLookupSummaryText : ($zapayLookupSummaryStatus !== '' ? $zapayLookupSummaryStatus : '-')); ?></p>
                                </div>
                                <div class="status-box">
                                    <p class="status-box-label">Histórico local</p>
                                    <p id="zapayStatusHistoryCount" class="status-box-value"><?php echo (int) $zapayLookupHistoryCount; ?> eventos</p>
                                </div>
                            </div>
                            <p id="zapayStatusUpdatedAt" class="muted" style="margin:12px 0 0;">
                                Atualizacao: aguardando sincronizacao do cache local.
                            </p>
                        </div>
                    <?php } ?>
                    <div class="table-wrap">
                        <table>
                            <tbody>
                                <?php
                                $vehicleDisplayOrder = [
                                    'placa' => 'Placa',
                                    'fabricante' => 'Fabricante',
                                    'marca_modelo' => 'Marca/Modelo bruto',
                                    'modelo' => 'Modelo',
                                    'ano' => 'Ano',
                                    'cor' => 'Cor',
                                    'categoria' => 'Categoria',
                                    'uf' => 'UF',
                                    'cidade' => 'Cidade',
                                    'municipio' => 'Municipio',
                                    'chassi' => 'Chassi',
                                    'renavam' => 'Renavam',
                                    'restricoes' => 'Restricoes',
                                    'estampador' => 'Estampador',
                                    'fipe_preco_medio' => 'FIPE preco medio',
                                    'fipe_codigo' => 'FIPE codigo',
                                    'fipe_ano_modelo' => 'FIPE ano/modelo',
                                    'fonte' => 'Fonte',
                                    'fonte_complementar' => 'Fonte complementar',
                                    'fontes_utilizadas' => 'Fontes utilizadas',
                                    'consulta_status' => 'Consulta status',
                                    'consulta_evento' => 'Consulta evento',
                                    'consulta_request_id' => 'Consulta request id',
                                    'consulta_detalhe' => 'Consulta detalhe',
                                    'consulta_multifonte_status' => 'Consulta multicamada',
                                    'consulta_multifonte_candidatos' => 'Fontes consultadas',
                                    'consulta_multifonte_confianca' => 'Confiança da consulta',
                                    'consulta_multifonte_taxa_consenso' => 'Taxa de consenso',
                                    'consulta_multifonte_score' => 'Score da melhor fonte',
                                    'consulta_multifonte_limite' => 'Limite de fontes',
                                    'consulta_multifonte_limite_aplicado' => 'Limite aplicado',
                                    'consulta_multifonte_fontes' => 'Fontes consolidadas',
                                    'consulta_multifonte_oficiais' => 'Fontes oficiais',
                                    'consulta_multifonte_consenso' => 'Campos em consenso',
                                    'consulta_multifonte_divergencias' => 'Divergencias',
                                    'consulta_multifonte_resumo' => 'Resumo da consulta',
                                    'consulta_multifonte_fonte_principal' => 'Fonte principal',
                                    'consulta_multifonte_fonte_tipo' => 'Tipo da fonte',
                                    'consulta_multifonte_alertas' => 'Alertas da consulta',
                                ];
                                foreach ($vehicleDisplayOrder as $fieldKey => $fieldLabel) {
                                    if (!array_key_exists($fieldKey, $veiculoExibicao)) {
                                        continue;
                                    }
                                    $fieldValue = $veiculoExibicao[$fieldKey];
                                    if (is_array($fieldValue)) {
                                        $fieldValue = json_encode($fieldValue, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
                                    }
                                    if (trim((string) $fieldValue) === '') {
                                        continue;
                                    }
                                ?>
                                    <tr>
                                        <th><?php echo htmlspecialchars(accentuatePortugueseText((string) $fieldLabel)); ?></th>
                                        <td><?php echo htmlspecialchars((string) $fieldValue); ?></td>
                                    </tr>
                                <?php } ?>
                            </tbody>
                        </table>
                    </div>
                    <div class="table-wrap" style="margin-top:12px;">
                        <table>
                            <tbody>
                                <tr>
                                    <th>Status da validacao oficial</th>
                                    <td><?php echo htmlspecialchars(humanizeOfficialValidationLabel($officialVehicleValidation['status'] ?? 'nao_disponivel')); ?></td>
                                </tr>
                                <tr>
                                    <th>Fonte da validacao</th>
                                    <td>
                                        <?php
                                        $validationSource = trim((string) (humanizeOfficialValidationSourceLabel($officialVehicleValidation['source_label'] ?? '')));
                                        if ($validationSource === '') {
                                            $validationSource = trim((string) (humanizeOfficialValidationSourceKindLabel($officialVehicleValidation['source_kind'] ?? 'indefinida')));
                                        }
                                        echo htmlspecialchars($validationSource !== '' ? $validationSource : 'indefinida');
                                        ?>
                                    </td>
                                </tr>
                                <tr>
                                    <th>Placa consultada</th>
                                    <td><?php echo htmlspecialchars((string) ($officialVehicleValidation['lookup_plate'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Campos publicos detectados</th>
                                    <td><?php echo htmlspecialchars(is_array($officialVehicleValidation['public_fields_found'] ?? null) ? implode(', ', array_map('strval', $officialVehicleValidation['public_fields_found'])) : '-'); ?></td>
                                </tr>
                                <tr>
                                    <th>Campos restritos detectados</th>
                                    <td><?php echo htmlspecialchars(is_array($officialVehicleValidation['sensitive_fields_found'] ?? null) ? implode(', ', array_map('strval', $officialVehicleValidation['sensitive_fields_found'])) : '-'); ?></td>
                                </tr>
                                <tr>
                                    <th>Politica de dados sensiveis</th>
                                    <td><?php echo htmlspecialchars((string) ($officialVehicleValidation['sensitive_policy'] ?? '-')); ?></td>
                                </tr>
                                <tr>
                                    <th>Observacoes</th>
                                    <td><?php echo htmlspecialchars(is_array($officialVehicleValidation['notes'] ?? null) ? implode(' | ', array_map('strval', $officialVehicleValidation['notes'])) : '-'); ?></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </section>
            <?php } elseif ($best) { ?>
                <section class="card">
                    <h2 class="card-title">Validação pós-placa e dados de veículo</h2>
                    <?php if ($vehicleLookupConfigured) { ?>
                        <div class="alert alert-warning">Não houve retorno estruturado de fonte oficial ou autorizada para esta placa nesta tentativa. O sistema manteve apenas a hipótese visual ou a evidência já confirmada, sem promover dado externo à conclusão.</div>
                    <?php } else { ?>
                        <div class="alert alert-warning">Integração de placa com fontes oficiais ou autorizadas desativada. Configure `GROM_OCR_SENATRAN_URL`, `GROM_OCR_PRODESP_URL`, `GROM_OCR_VEHICLE_LOOKUP_URL`, `GROM_OCR_VEHICLE_LOOKUP_URLS` ou o provedor assíncrono `GROM_OCR_USEZAPAY_ENABLE=1`; sem isso, dados como fabricante, modelo, ano, chassi, RENAVAM e outros campos dependentes de validação externa não estarão disponíveis.</div>
                    <?php } ?>
                    <?php if (!$openDataEnabled) { ?>
                        <div class="alert alert-warning" style="margin-top:10px;">Complemento de base aberta esta desativado (`GROM_OCR_OPEN_DATA_ENABLE=0`).</div>
                    <?php } ?>
                </section>
            <?php } ?>
        <?php } ?>
    </main>
    <section id="analysisProgressOverlay" class="analysis-progress-overlay" aria-hidden="true">
        <div class="analysis-progress-panel" role="status" aria-live="polite">
            <p class="analysis-progress-tag">Pipeline OCR em execucao</p>
            <h3 class="analysis-progress-title">Pesquisa em andamento</h3>
            <p id="analysisProgressStage" class="analysis-progress-subtitle">Inicializando validacao do arquivo...</p>
            <canvas id="analysisProgressChart" class="analysis-progress-chart" width="680" height="220"></canvas>
            <div class="analysis-progress-track">
                <div id="analysisProgressBar" class="analysis-progress-track-bar"></div>
            </div>
            <p class="analysis-progress-percent"><span id="analysisProgressValue">0</span>% concluido</p>
        </div>
    </section>
    <script>
        (function() {
            const form = document.getElementById('ocrUploadForm');
            const overlay = document.getElementById('analysisProgressOverlay');
            const progressBar = document.getElementById('analysisProgressBar');
            const progressValue = document.getElementById('analysisProgressValue');
            const stageText = document.getElementById('analysisProgressStage');
            const submitButton = document.getElementById('ocrSubmitButton');
            const canvas = document.getElementById('analysisProgressChart');

            if (!form || !overlay || !progressBar || !progressValue || !stageText || !canvas) {
                return;
            }

            const context = canvas.getContext('2d');
            let timerId = null;
            let progress = 0;
            let series = [];
            let analysisStartAt = 0;

            function setupCanvas() {
                const dpr = window.devicePixelRatio || 1;
                const width = canvas.clientWidth || 680;
                const height = canvas.clientHeight || 220;
                canvas.width = Math.floor(width * dpr);
                canvas.height = Math.floor(height * dpr);
                context.setTransform(dpr, 0, 0, dpr, 0, 0);
                return {
                    width,
                    height
                };
            }

            function drawChart() {
                const chart = setupCanvas();
                const width = chart.width;
                const height = chart.height;
                context.clearRect(0, 0, width, height);

                context.fillStyle = '#f7fbff';
                context.fillRect(0, 0, width, height);

                context.strokeStyle = 'rgba(52, 94, 138, 0.18)';
                context.lineWidth = 1;
                for (let index = 1; index <= 4; index += 1) {
                    const y = (height / 5) * index;
                    context.beginPath();
                    context.moveTo(0, y);
                    context.lineTo(width, y);
                    context.stroke();
                }

                if (series.length < 2) {
                    return;
                }

                const stepX = width / Math.max(1, series.length - 1);
                context.beginPath();
                series.forEach(function(point, index) {
                    const x = stepX * index;
                    const y = height - ((point / 100) * (height - 30)) - 15;
                    if (index === 0) {
                        context.moveTo(x, y);
                    } else {
                        context.lineTo(x, y);
                    }
                });

                context.lineWidth = 2.4;
                context.strokeStyle = '#0b5fae';
                context.stroke();

                context.lineTo(width, height - 10);
                context.lineTo(0, height - 10);
                context.closePath();
                const gradient = context.createLinearGradient(0, 0, 0, height);
                gradient.addColorStop(0, 'rgba(11, 95, 174, 0.34)');
                gradient.addColorStop(1, 'rgba(11, 95, 174, 0.03)');
                context.fillStyle = gradient;
                context.fill();
            }

            function stageByProgress(value, elapsedMs) {
                if (elapsedMs >= 120000) {
                    return 'Consolidacao final no servidor...';
                }
                if (value >= 99) {
                    return 'Consolidando resposta final no servidor...';
                }
                if (value >= 96) {
                    return 'Análise quase concluída. Consolidando a resposta final...';
                }
                if (elapsedMs >= 60000 && value >= 85) {
                    return 'Análise avançada em andamento no servidor. Mantenha esta aba aberta...';
                }
                if (value < 18) {
                    return 'Recebendo arquivo e validando formato...';
                }
                if (value < 45) {
                    return 'Aplicando melhorias de contraste, brilho e nitidez...';
                }
                if (value < 72) {
                    return 'Executando motores OCR e cruzando candidatos...';
                }
                if (value < 92) {
                    return 'Consolidando melhor leitura e dados complementares...';
                }
                return 'Finalizando resposta e preparando tela de resultado...';
            }

            function updateProgressVisual(value) {
                const elapsedMs = analysisStartAt ? (performance.now() - analysisStartAt) : 0;
                const rounded = Math.max(1, Math.min(99.9, Math.round(value * 10) / 10));
                progressBar.style.width = rounded + '%';
                progressValue.textContent = String(rounded);
                stageText.textContent = stageByProgress(rounded, elapsedMs);
                series.push(Math.max(1, Math.min(99, rounded + ((Math.random() * 6) - 2))));
                if (series.length > 56) {
                    series.shift();
                }
                drawChart();
            }

            function nextIncrement(current) {
                if (current < 22) {
                    return 1.9 + (Math.random() * 1.7);
                }
                if (current < 58) {
                    return 0.9 + (Math.random() * 1.1);
                }
                if (current < 84) {
                    return 0.38 + (Math.random() * 0.6);
                }
                if (current < 94) {
                    return 0.18 + (Math.random() * 0.25);
                }
                if (current < 98.5) {
                    return 0.04 + (Math.random() * 0.08);
                }
                return 0.008 + (Math.random() * 0.018);
            }

            function beginProgress() {
                if (timerId) {
                    return;
                }
                analysisStartAt = performance.now();
                progress = 2;
                series = Array.from({
                    length: 38
                }, function(_, index) {
                    return Math.min(42, Math.max(2, (index * 1.05) + (Math.random() * 2.8)));
                });
                overlay.classList.add('is-active');
                overlay.setAttribute('aria-hidden', 'false');
                document.body.classList.add('is-busy');
                if (submitButton) {
                    submitButton.disabled = true;
                    submitButton.setAttribute('aria-disabled', 'true');
                }
                updateProgressVisual(progress);
                timerId = window.setInterval(function() {
                    progress = Math.min(99.9, progress + nextIncrement(progress));
                    updateProgressVisual(progress);
                }, 420);
            }

            function resetProgress() {
                if (timerId) {
                    window.clearInterval(timerId);
                    timerId = null;
                }
                overlay.classList.remove('is-active');
                overlay.setAttribute('aria-hidden', 'true');
                document.body.classList.remove('is-busy');
                analysisStartAt = 0;
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.removeAttribute('aria-disabled');
                }
            }

            form.addEventListener('submit', beginProgress);
            window.addEventListener('pageshow', resetProgress);
            window.addEventListener('resize', function() {
                if (overlay.classList.contains('is-active')) {
                    drawChart();
                }
            });
        }());
    </script>
    <script>
        (function() {
            const panel = document.getElementById('zapayStatusPanel');
            if (!panel) {
                return;
            }

            const chip = document.getElementById('zapayStatusChip');
            const topbarChip = document.getElementById('analysisTopStatusChip');
            const refreshBtn = document.getElementById('zapayRefreshBtn');
            const plateField = document.getElementById('zapayStatusPlate');
            const requestIdField = document.getElementById('zapayStatusRequestId');
            const eventField = document.getElementById('zapayStatusEvent');
            const detailField = document.getElementById('zapayStatusDetail');
            const summaryField = document.getElementById('zapayStatusSummary');
            const historyField = document.getElementById('zapayStatusHistoryCount');
            const updatedField = document.getElementById('zapayStatusUpdatedAt');
            const topbarText = document.getElementById('analysisTopStatusText');

            const requestId = panel.dataset.usezapayRequestId || '';
            const plate = panel.dataset.usezapayPlate || '';
            let currentStatus = (panel.dataset.usezapayStatus || '').toLowerCase();
            let pollTimer = null;
            let abortController = null;

            function setText(element, value) {
                if (!element) {
                    return;
                }
                element.textContent = value && String(value).trim() !== '' ? String(value) : '-';
            }

            function statusMeta(status) {
                const normalized = String(status || '').toLowerCase();
                switch (normalized) {
                    case 'pending_async':
                    case 'pendente_webhook':
                    case 'aguardando_webhook':
                        return {
                            label: 'Pendente', className: 'status-chip--pending', final: false
                        };
                    case 'resultado_cache':
                    case 'cache_hit':
                    case 'ok':
                    case 'vehicle_debt_found':
                    case 'concluido':
                        return {
                            label: 'Concluido', className: 'status-chip--ok', final: true
                        };
                    case 'sem_retorno':
                    case 'nao_disponivel':
                    case 'not_found':
                    case 'vehicle_not_found':
                    case 'vehicle_debt_not_found':
                        return {
                            label: 'Sem retorno', className: 'status-chip--warning', final: true
                        };
                    case 'erro':
                    case 'error':
                    case 'vehicle_debt_search_error':
                        return {
                            label: 'Erro', className: 'status-chip--error', final: true
                        };
                    default:
                        return {
                            label: normalized ? normalized.replace(/_/g, ' ') : 'Indefinido',
                                className: 'status-chip--neutral',
                                final: false,
                        };
                }
            }

            function renderStatus(payload) {
                const latest = (payload && typeof payload.latest === 'object' && payload.latest) ? payload.latest : {};
                const summary = (payload && typeof payload.summary === 'object' && payload.summary) ? payload.summary : {};
                const status = String(latest.status || latest.event || payload.status || currentStatus || '').toLowerCase();
                const meta = statusMeta(status);

                currentStatus = status;
                if (chip) {
                    chip.className = 'status-chip ' + meta.className;
                    chip.textContent = meta.label;
                }
                if (topbarChip) {
                    topbarChip.className = 'status-chip ' + meta.className + ' status-chip--compact';
                    topbarChip.textContent = meta.label;
                }

                setText(plateField, payload.plate || latest.plate || plate);
                setText(requestIdField, payload.request_id || latest.request_id || requestId);
                setText(eventField, latest.event || payload.event || '');
                setText(detailField, latest.detail || '');

                const latestDebts = (latest && typeof latest.debts === 'object' && latest.debts) ? latest.debts : {};
                const summaryText = latest.status === 'pending_async' ?
                    'Consulta pendente de webhook.' :
                    (summary.summary_text || latestDebts.summary || latest.detail || '');
                setText(summaryField, summaryText || summary.status || '');

                const historyCount = typeof summary.history_count === 'number' ?
                    summary.history_count :
                    (summary.history_count ? Number(summary.history_count) : 0);
                setText(historyField, historyCount ? (historyCount + ' eventos') : (latest.event ? '1 evento' : '0 eventos'));

                const updatedAt = latest.received_at_utc || summary.updated_at_utc || '';
                setText(updatedField, updatedAt ? ('Atualizado em UTC ' + updatedAt) : 'Atualizacao: aguardando sincronizacao do cache local.');

                if (topbarText) {
                    const topbarParts = [];
                    const topbarPlate = String(payload.plate || latest.plate || plate || '').trim();
                    const topbarRequestId = String(payload.request_id || latest.request_id || requestId || '').trim();
                    if (topbarPlate) {
                        topbarParts.push('Placa ' + topbarPlate);
                    }
                    if (topbarRequestId) {
                        topbarParts.push('Request ' + topbarRequestId);
                    }
                    if (summaryText) {
                        topbarParts.push(summaryText);
                    } else if (latest.detail) {
                        topbarParts.push(String(latest.detail));
                    }
                    topbarText.textContent = topbarParts.length > 0 ? topbarParts.join(' · ') : 'Monitoramento Zapay ativo.';
                }

                panel.dataset.usezapayStatus = status;
                return meta.final;
            }

            function stopPolling() {
                if (pollTimer) {
                    window.clearInterval(pollTimer);
                    pollTimer = null;
                }
                if (abortController) {
                    abortController.abort();
                    abortController = null;
                }
            }

            function ensurePolling(active) {
                if (!active || pollTimer) {
                    return;
                }
                pollTimer = window.setInterval(function() {
                    refreshStatus(false);
                }, 5000);
            }

            async function refreshStatus(manual) {
                if (!requestId && !plate) {
                    return;
                }

                if (abortController) {
                    abortController.abort();
                }

                abortController = new AbortController();
                const url = new URL('/api/usezapay_status.php', window.location.origin);
                if (requestId) {
                    url.searchParams.set('request_id', requestId);
                } else if (plate) {
                    url.searchParams.set('plate', plate);
                }

                if (manual && refreshBtn) {
                    refreshBtn.disabled = true;
                    refreshBtn.textContent = 'Atualizando...';
                }

                try {
                    const response = await fetch(url.toString(), {
                        headers: {
                            'Accept': 'application/json'
                        },
                        cache: 'no-store',
                        signal: abortController.signal,
                    });
                    if (!response.ok) {
                        throw new Error('HTTP ' + response.status);
                    }

                    const data = await response.json();
                    const finalStatus = renderStatus(data);
                    if (finalStatus) {
                        stopPolling();
                    } else {
                        ensurePolling(true);
                    }
                } catch (error) {
                    ensurePolling(true);
                    setText(updatedField, 'Falha ao consultar status local.');
                } finally {
                    if (manual && refreshBtn) {
                        refreshBtn.disabled = false;
                        refreshBtn.textContent = 'Atualizar status';
                    }
                }
            }

            if (refreshBtn) {
                refreshBtn.addEventListener('click', function() {
                    refreshStatus(true);
                });
            }

            const shouldAutoTrack = Boolean(requestId || plate || currentStatus);
            if (shouldAutoTrack) {
                refreshStatus(false);
            }

            window.addEventListener('beforeunload', stopPolling);
        }());
    </script>
    <script>
        (function() {
            const candidateSelect = document.getElementById('humanReviewCandidateSelect');
            const confirmedTextInput = document.getElementById('humanReviewConfirmedText');
            if (!candidateSelect || !confirmedTextInput) {
                return;
            }

            function syncConfirmedText() {
                const option = candidateSelect.options[candidateSelect.selectedIndex];
                if (!option) {
                    return;
                }
                const candidateText = option.dataset.text || '';
                if (candidateText.trim() !== '') {
                    confirmedTextInput.value = candidateText.trim();
                }
            }

            candidateSelect.addEventListener('change', syncConfirmedText);
            syncConfirmedText();
        }());
    </script>
    <script>
        (function() {
            const printButton = document.querySelector('.analysis-report-actions-panel #analysisReportPrintBtn') ||
                document.getElementById('analysisReportPrintBtn');
            if (!printButton) {
                return;
            }

            printButton.addEventListener('click', function() {
                window.print();
            });
        }());
    </script>
    <script>
        (function() {
            const reportCard = document.getElementById('analysisReport');
            if (!reportCard) {
                return;
            }

            window.requestAnimationFrame(function() {
                reportCard.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            });
        }());
    </script>
</body>

</html>
