<?php
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_start();
}
if (!isset($_SESSION['user_id'])) {
    header('Location: /login.php');
    exit;
}

require_once __DIR__ . '/../app/models/User.php';

function formatVideoDuration($seconds): string
{
    $seconds = max(0, (float) $seconds);
    $total = (int) round($seconds);
    $hours = intdiv($total, 3600);
    $minutes = intdiv($total % 3600, 60);
    $remaining = $total % 60;
    if ($hours > 0) {
        return sprintf('%02d:%02d:%02d', $hours, $minutes, $remaining);
    }
    return sprintf('%02d:%02d', $minutes, $remaining);
}

function formatBytesHuman($bytes): string
{
    $bytes = max(0, (float) $bytes);
    if ($bytes >= 1073741824) {
        return number_format($bytes / 1073741824, 2, ',', '.') . ' GB';
    }
    if ($bytes >= 1048576) {
        return number_format($bytes / 1048576, 2, ',', '.') . ' MB';
    }
    if ($bytes >= 1024) {
        return number_format($bytes / 1024, 1, ',', '.') . ' KB';
    }
    return number_format($bytes, 0, ',', '.') . ' B';
}

function cleanFloat($value, $default = 0.0): float
{
    return is_numeric($value) ? (float) $value : (float) $default;
}

function cleanInt($value, $default = 0): int
{
    return is_numeric($value) ? (int) $value : (int) $default;
}

function cleanText($value, $fallback = '-'): string
{
    $text = trim((string) ($value ?? ''));
    return $text !== '' ? $text : $fallback;
}

function frameArtifactUrl($path): string
{
    $basename = trim((string) basename((string) $path));
    return $basename !== '' ? '/artifact/' . rawurlencode($basename) : '';
}

$app = require __DIR__ . '/../config/app.php';
$pythonApiUrl = $app['python_api_url'];

$result = null;
$errorMessage = null;
$analysisStage = 'preview';
$frameLimit = 12;
$uploadedFilename = '';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $analysisStage = strtolower(trim((string) ($_POST['analysis_stage'] ?? 'preview')));
    if (!in_array($analysisStage, ['preview', 'final'], true)) {
        $analysisStage = 'preview';
    }
    $frameLimitRaw = trim((string) ($_POST['frame_limit'] ?? '12'));
    if (is_numeric($frameLimitRaw)) {
        $frameLimit = max(4, min((int) $frameLimitRaw, 24));
    }

    if (!isset($_FILES['video']) || empty($_FILES['video']['tmp_name'])) {
        $errorMessage = 'Selecione um vídeo para análise.';
    } elseif (!function_exists('curl_file_create')) {
        $errorMessage = 'O ambiente PHP não suporta upload multipart avançado.';
    } else {
        $uploadedFilename = trim((string) ($_FILES['video']['name'] ?? ''));
        $videoType = trim((string) ($_FILES['video']['type'] ?? 'application/octet-stream')) ?: 'application/octet-stream';
        $videoTmp = (string) ($_FILES['video']['tmp_name'] ?? '');

        $cfile = curl_file_create($videoTmp, $videoType, $uploadedFilename);
        $payload = [
            'video' => $cfile,
            'analysis_stage' => $analysisStage,
            'frame_limit' => (string) $frameLimit,
        ];

        $ch = curl_init($pythonApiUrl . '/process_video');
        curl_setopt($ch, CURLOPT_POST, 1);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 6);
        curl_setopt($ch, CURLOPT_TIMEOUT, 1200);
        if (defined('CURL_IPRESOLVE_V4')) {
            curl_setopt($ch, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
        }
        $response = curl_exec($ch);
        $curlError = curl_error($ch);
        $httpCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($response === false) {
            $errorMessage = 'Falha ao comunicar com o motor de vídeo: ' . $curlError;
        } else {
            $decoded = json_decode($response, true);
            if (!is_array($decoded)) {
                $errorMessage = 'A resposta do motor de vídeo não pôde ser interpretada.';
            } elseif ($httpCode >= 400 || !empty($decoded['error'])) {
                $errorMessage = (string) ($decoded['error'] ?? ('Falha ao processar vídeo (HTTP ' . $httpCode . ')'));
                $result = $decoded;
            } else {
                $result = $decoded;
            }
        }
    }
}

$frameResults = is_array($result['frame_results'] ?? null) ? $result['frame_results'] : [];
$videoCandidatesPreview = is_array($result['video_candidates_preview'] ?? null) ? $result['video_candidates_preview'] : [];
$videoCandidatesCount = cleanInt($result['video_candidates_count'] ?? count($videoCandidatesPreview));
$videoPartialCandidatesPreview = is_array($result['video_partial_candidates_preview'] ?? null) ? $result['video_partial_candidates_preview'] : [];
$videoPartialCandidatesCount = cleanInt($result['video_partial_candidates_count'] ?? count($videoPartialCandidatesPreview));
$selectedCandidateIds = is_array($result['selected_candidate_ids'] ?? null) ? $result['selected_candidate_ids'] : [];
$selectedTarget = is_array($result['selected_target'] ?? null) ? $result['selected_target'] : [];
$selectedTargets = is_array($result['selected_targets'] ?? null) ? $result['selected_targets'] : [];
$analysisReportOutline = is_array($result['analysis_report_outline'] ?? null) ? $result['analysis_report_outline'] : [];
$videoMetadata = is_array($result['video_metadata'] ?? null) ? $result['video_metadata'] : [];
$frameSampling = is_array($result['frame_sampling'] ?? null) ? $result['frame_sampling'] : [];
$bestFrame = is_array($result['best_frame'] ?? null) ? $result['best_frame'] : [];
$bestResult = is_array($result['best_result'] ?? null) ? $result['best_result'] : [];
$consensus = is_array($result['consensus'] ?? null) ? $result['consensus'] : [];
$assessment = is_array($result['assessment'] ?? null) ? $result['assessment'] : [];
$pericial = is_array($result['pericial'] ?? null) ? $result['pericial'] : [];
$humanReview = is_array($result['human_review'] ?? null) ? $result['human_review'] : [];
$captureIntegrity = is_array($result['capture_integrity'] ?? null) ? $result['capture_integrity'] : [];
$contactSheetUrl = trim((string) ($result['contact_sheet_url'] ?? ''));
$comparisonSheetUrl = trim((string) ($result['comparison_sheet_url'] ?? ''));
$reportUrl = trim((string) ($result['report_url'] ?? ''));
$manifestUrl = trim((string) ($result['manifest_url'] ?? $result['evidence_manifest_url'] ?? ''));
$analysisId = trim((string) ($result['analysis_id'] ?? ''));
$videoFileName = cleanText($videoMetadata['video_filename'] ?? $uploadedFilename, 'Vídeo não identificado');
$durationText = formatVideoDuration(cleanFloat($videoMetadata['duration_seconds'] ?? 0.0));
$fpsText = number_format(cleanFloat($videoMetadata['fps'] ?? 0.0), 2, ',', '.');
$resolutionText = cleanInt($videoMetadata['width'] ?? 0) . 'x' . cleanInt($videoMetadata['height'] ?? 0) . ' px';
$frameCountText = number_format(cleanInt($videoMetadata['frame_count'] ?? 0), 0, ',', '.');
$sampleCountText = number_format(cleanInt($frameSampling['selected_frame_count'] ?? count($frameResults)), 0, ',', '.');
$bestText = cleanText($selectedTarget['text'] ?? $bestResult['text'] ?? $bestFrame['ocr'] ?? '', 'Indefinido');
$bestPattern = cleanText($selectedTarget['pattern'] ?? $bestResult['pattern'] ?? $bestFrame['pattern'] ?? '', 'Indefinido');
$consensusRatioText = number_format(cleanFloat($consensus['agreement_ratio'] ?? 0.0), 1, ',', '.');
$consensusCountText = cleanInt($consensus['agreement_count'] ?? 0);
$enginesConsideredText = cleanInt($consensus['engines_considered'] ?? count($frameResults));
$reviewStatus = cleanText($humanReview['decision_label'] ?? $humanReview['decision'] ?? 'Pendente', 'Pendente');
$captureStatus = cleanText($captureIntegrity['status'] ?? 'Indefinido', 'Indefinido');
$captureScoreText = number_format(cleanFloat($captureIntegrity['integrity_score'] ?? 0.0), 1, ',', '.');
$analysisModeLabel = $analysisStage === 'preview' ? 'Pré-análise' : 'Consolidado';
$selectedFrameSource = !empty($selectedTarget) ? $selectedTarget : $bestFrame;
$selectedFrameUrl = frameArtifactUrl($selectedFrameSource['frame_path'] ?? '');
$selectedFrameCropRawUrl = frameArtifactUrl($selectedFrameSource['crop_raw_path'] ?? '');
$selectedFrameCropTreatedUrl = frameArtifactUrl($selectedFrameSource['crop_treated_path'] ?? '');
$selectedFrameCropPreviewUrl = $selectedFrameCropTreatedUrl !== '' ? $selectedFrameCropTreatedUrl : ($selectedFrameCropRawUrl !== '' ? $selectedFrameCropRawUrl : $selectedFrameUrl);
$selectedFramePattern = cleanText($selectedTarget['pattern'] ?? $bestResult['pattern'] ?? $bestFrame['pattern'] ?? 'Indefinido', 'Indefinido');
$selectedFrameConfidence = number_format(cleanFloat($selectedTarget['avg_confidence'] ?? $selectedTarget['best_confidence'] ?? $bestFrame['confidence'] ?? $bestResult['avg_conf'] ?? 0.0), 1, ',', '.');
$selectedFrameScore = number_format(cleanFloat($selectedTarget['avg_score'] ?? $selectedTarget['best_score'] ?? $bestFrame['score'] ?? $bestResult['score'] ?? 0.0), 1, ',', '.');
$selectedFrameTimestamp = formatVideoDuration(cleanFloat($selectedTarget['timestamp_seconds'] ?? $bestFrame['timestamp_seconds'] ?? 0.0));
$selectedFrameMinute = cleanText($selectedTarget['minute_range'] ?? $bestFrame['minute_range'] ?? '', 'Indefinido');
$selectedFrameSupport = cleanText($selectedTarget['support_label'] ?? $bestFrame['support_label'] ?? '', '');
$selectedFrameIndex = cleanInt($selectedTarget['frame_order'] ?? $selectedTarget['frame_index'] ?? $bestFrame['frame_order'] ?? $bestFrame['frame_index'] ?? 0);
$selectedFrameTitle = cleanText($selectedTarget['display_label'] ?? '', '');
$selectedFrameHasTitle = $selectedFrameTitle !== '' && $selectedFrameTitle !== 'Indefinido';
$selectedFrameHasText = $bestText !== '' && $bestText !== 'Indefinido' && $bestText !== 'Sem leitura confiável' && $bestText !== 'SEM_TEXTO';
$selectedFrameHasMinute = $selectedFrameMinute !== '' && $selectedFrameMinute !== 'Indefinido';
$selectedFrameIsMeaningful = $selectedFrameHasTitle || $selectedFrameHasText || $selectedFrameHasMinute;
$selectedFrameSummaryTitle = $selectedFrameIsMeaningful ? ($selectedFrameTitle !== '' ? $selectedFrameTitle : ('Alvo ' . str_pad((string) $selectedFrameIndex, 2, '0', STR_PAD_LEFT))) : 'Nenhum alvo consolidado';
$selectedFrameSummaryMinute = $selectedFrameIsMeaningful ? $selectedFrameMinute : 'Minuto indisponível';
$selectedFrameSummaryPlate = $selectedFrameIsMeaningful ? $bestText : 'Sem leitura confiável';
$selectedFrameSummarySupport = $selectedFrameIsMeaningful ? ($selectedFrameSupport !== '' ? $selectedFrameSupport : 'Selecionado pelo operador') : 'Sem alvo consolidado';
$consolidationStateText = $analysisStage === 'preview'
    ? 'Pré-análise'
    : ($selectedFrameIsMeaningful ? 'Consolidado' : 'Sem alvo');
$consolidationHeadingText = $analysisStage === 'preview' ? 'Pré-análise com alvo em destaque' : 'Alvo consolidado para impressão';
$candidateCountText = number_format($videoCandidatesCount > 0 ? $videoCandidatesCount : (count($videoCandidatesPreview) > 0 ? count($videoCandidatesPreview) : count($frameResults)), 0, ',', '.');
$videoPartialPrimary = is_array($videoPartialCandidatesPreview[0] ?? null) ? $videoPartialCandidatesPreview[0] : [];
$videoPartialPrimaryText = cleanText($videoPartialPrimary['text'] ?? $videoPartialPrimary['normalized_text'] ?? '', 'Indefinido');
$videoPartialPrimaryMinute = cleanText($videoPartialPrimary['minute_range'] ?? '', 'Indefinido');
$videoPartialPrimarySupport = cleanText($videoPartialPrimary['support_label'] ?? '', '');
$videoPartialHasEvidence = $videoPartialCandidatesCount > 0 && $videoPartialPrimaryText !== '' && $videoPartialPrimaryText !== 'Indefinido';
$videoPartialCoverNote = $videoPartialHasEvidence
    ? 'Fragmentos parciais preservados para confronto: ' . $videoPartialPrimaryText . ' em ' . $videoPartialPrimaryMinute . ($videoPartialPrimarySupport !== '' ? ' | ' . $videoPartialPrimarySupport : '') . '.'
    : '';
$videoDocumentStatusText = $analysisStage === 'preview' ? 'Aguardando correção em tela' : 'Disponível para impressão documental';
$videoDocumentSourceText = $videoFileName;
$videoDocumentScanIntervalText = cleanFloat($frameSampling['scan_interval_seconds'] ?? 0.0) > 0
    ? number_format(cleanFloat($frameSampling['scan_interval_seconds'] ?? 0.0), 2, ',', '.') . 's'
    : 'Indefinido';
$videoDocumentStrategyText = cleanText($frameSampling['strategy'] ?? 'frame_by_frame_scan', 'frame_by_frame_scan');
$videoDocumentStrategyLabel = ucwords(str_replace('_', ' ', $videoDocumentStrategyText));
$videoDocumentFrameResultsCountText = number_format(count($frameResults), 0, ',', '.');
$videoDocumentCandidatesText = number_format($videoCandidatesCount > 0 ? $videoCandidatesCount : (count($videoCandidatesPreview) > 0 ? count($videoCandidatesPreview) : count($frameResults)), 0, ',', '.');
$videoDocumentPartialText = $videoPartialHasEvidence
    ? $videoPartialPrimaryText . ' | ' . $videoPartialPrimaryMinute . ($videoPartialPrimarySupport !== '' ? ' | ' . $videoPartialPrimarySupport : '') . ' | ' . number_format($videoPartialCandidatesCount, 0, ',', '.') . ' fragmentos'
    : 'Nenhum fragmento';
$videoDocumentSelectedTargetsText = number_format(count($selectedTargets), 0, ',', '.') . ' alvo(s)';
$videoDocumentOperatorSelectionText = count($selectedTargets) > 0 ? count($selectedTargets) . ' alvo(s) | ordem preservada' : 'Nenhum alvo consolidado';
$videoDocumentHashText = cleanText($videoMetadata['sha256'] ?? '-', '-');
$videoDocumentCodecText = cleanText($videoMetadata['codec_fourcc'] ?? ($videoMetadata['codec_hint'] ?? '-'), '-');
$operatorLabel = User::resolveSessionLabel($_SESSION);
?>
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Vídeo - Grom_OCR</title>
    <link rel="stylesheet" href="/assets/app.css">
    <link rel="icon" type="image/png" href="/assets/grom-favicon.png">
</head>
<body class="page-body">
    <main class="page-shell">
        <header class="topbar">
            <div class="brand">
                <div class="brand-mark">
                    <img src="/assets/grom-report-logo.png" alt="Grom OCR">
                </div>
                <div>
                    <h1 class="brand-title">Nova análise de vídeo</h1>
                    <p class="brand-subtitle">Apoio técnico à investigação, frame a frame e validação documental</p>
                    <div class="analysis-topbar-status">
                        <div class="status-chip status-chip--neutral status-chip--compact">Vídeo</div>
                        <p class="analysis-topbar-status-text">Extração temporal, seleção de alvos e relatório de apoio técnico à investigação.</p>
                    </div>
                    <div class="analysis-topbar-identity">
                        <span class="analysis-topbar-identity-label">Operador</span>
                        <strong class="analysis-topbar-identity-value"><?php echo htmlspecialchars($operatorLabel); ?></strong>
                    </div>
                </div>
            </div>
            <nav class="nav-links">
                <a class="nav-link" href="/">Dashboard</a>
                <a class="nav-link" href="/upload.php">Imagem</a>
                <a class="nav-link active" href="/video.php">Vídeo</a>
                <a class="nav-link" href="/historico.php">Histórico</a>
                <a class="nav-link" href="/logout.php">Sair</a>
            </nav>
        </header>

        <section class="card no-print analysis-intake-card video-intake-card">
            <div class="analysis-intake-panel">
                <div class="analysis-intake-copy">
                    <p class="analysis-report-eyebrow">Entrada documental</p>
                    <h2 class="analysis-intake-title">Enviar vídeo para análise</h2>
                    <p class="analysis-intake-text">
                        O sistema preserva o vídeo-fonte, extrai quadros em posições distribuídas ao longo da linha temporal e concentra a leitura nos quadros de maior valor probatório.
                    </p>
                    <ul class="analysis-intake-points">
                        <li>Vídeo-fonte preservado para cadeia de custódia digital.</li>
                        <li>Varredura frame a frame para localizar os alvos de interesse.</li>
                        <li>OCR, consenso e revisão humana antes da impressão documental.</li>
                    </ul>
                    <div class="analysis-intake-steps" aria-label="Fluxo de análise de vídeo">
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">01</span>
                            <div>
                                <strong>Ingestão</strong>
                                <p>Arquivo-fonte, assinatura e metadados do vídeo.</p>
                            </div>
                        </article>
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">02</span>
                            <div>
                                <strong>Varredura</strong>
                                <p>Quadros-chave distribuídos ao longo da linha temporal.</p>
                            </div>
                        </article>
                        <article class="analysis-intake-step">
                            <span class="analysis-intake-step-index">03</span>
                            <div>
                                <strong>Consolidação</strong>
                                <p>Alvos selecionados, OCR e relatório formal de apoio.</p>
                            </div>
                        </article>
                    </div>
                    <p class="analysis-intake-note">
                        A análise de vídeo permanece separada do fluxo de imagem, com arquivos, propriedades e relatório próprios para evitar regressão operacional.
                    </p>
                </div>

                <div class="analysis-upload-panel video-upload-panel">
                    <div class="analysis-upload-header">
                        <div class="analysis-upload-header-copy">
                            <p class="analysis-report-eyebrow">Arquivo de entrada</p>
                            <h3 class="card-title">Selecionar vídeo-fonte</h3>
                            <p class="analysis-upload-header-note">O motor varre o vídeo inteiro, extrai quadros-chave, executa OCR frame a frame e gera relatório de apoio à investigação com base nos alvos selecionados.</p>
                        </div>
                        <span class="status-chip status-chip--neutral status-chip--compact"><?php echo htmlspecialchars($analysisModeLabel); ?></span>
                    </div>

                    <form id="videoUploadForm" method="POST" enctype="multipart/form-data">
                        <input type="hidden" name="analysis_stage" value="preview">
                        <label class="field" for="video">
                            <span class="field-label">Arquivo de vídeo (até 10 minutos | MP4, MOV, AVI, MKV, WEBM, TS, M2TS, DAV)</span>
                            <input id="video" type="file" name="video" accept="video/*,.mp4,.mov,.avi,.mkv,.webm,.ts,.m2ts,.mts,.dav,.mpg,.mpeg,.m4v" required>
                            <span class="upload-hint">Selecione o vídeo original. O sistema fará varredura temporal integral, OCR frame a frame, preservará os artefatos e permitirá escolher os alvos com maior valor probatório.</span>
                        </label>
                        <div class="field" style="margin-top:12px;">
                            <label class="field-label" for="frame_limit">Quadros de varredura</label>
                            <input id="frame_limit" type="number" name="frame_limit" min="6" max="72" value="36">
                            <span class="upload-hint">Aumente para vídeos longos ou com variações intensas; o padrão distribui a cobertura ao longo de todo o vídeo.</span>
                        </div>
                        <div class="btn-row">
                            <button id="videoSubmitButton" class="btn btn-primary" type="submit">Processar vídeo</button>
                            <a class="btn btn-secondary" href="/historico.php">Ver histórico</a>
                        </div>
                    </form>

                    <div class="upload-meta-row">
                        <article class="upload-meta">
                            <p class="upload-meta-label">Entrada</p>
                            <p class="upload-meta-value">Vídeo-fonte preservado</p>
                        </article>
                        <article class="upload-meta">
                            <p class="upload-meta-label">Processamento</p>
                            <p class="upload-meta-value">Quadros-chave e OCR frame a frame</p>
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
        </section>

        <?php if (!$result || !is_array($result)) { ?>
            <section class="card analysis-bridge-card no-print">
                <div class="analysis-bridge-header">
                    <div>
                        <p class="analysis-report-eyebrow">Fluxo documental</p>
                        <h2 class="analysis-bridge-title">Análise técnica de vídeo em três movimentos</h2>
                        <p class="analysis-bridge-text">
                        O sistema mantém o vídeo-fonte preservado, extrai quadros em posições distribuídas ao longo da linha temporal e consolida a leitura nos alvos marcados antes da revisão humana.
                        </p>
                    </div>
                    <div class="analysis-bridge-badge">Apoio técnico</div>
                </div>

                <div class="analysis-bridge-grid">
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">01</span>
                        <div>
                            <h3>Preservação do vídeo</h3>
                            <p>O arquivo original é mantido íntegro, com hash e metadados para cadeia de custódia digital.</p>
                        </div>
                    </article>
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">02</span>
                        <div>
                            <h3>Tratamento técnico</h3>
                            <p>Os quadros são amostrados, analisados e comparados para localizar a melhor leitura da placa.</p>
                        </div>
                    </article>
                    <article class="analysis-bridge-item">
                        <span class="analysis-bridge-index">03</span>
                        <div>
                            <h3>Conferência humana</h3>
                            <p>O consenso temporal é apresentado para revisão antes da impressão documental.</p>
                        </div>
                    </article>
                </div>
            </section>
        <?php } ?>
    <section id="analysisProgressOverlay" class="analysis-progress-overlay" aria-hidden="true">
        <div class="analysis-progress-panel" role="status" aria-live="polite">
            <p class="analysis-progress-tag">Pipeline de vídeo em execução</p>
            <h3 class="analysis-progress-title">Pesquisa em andamento</h3>
            <p id="analysisProgressStage" class="analysis-progress-subtitle">Inicializando validação do arquivo...</p>
            <canvas id="analysisProgressChart" class="analysis-progress-chart" width="680" height="220"></canvas>
            <div class="analysis-progress-track">
                <div id="analysisProgressBar" class="analysis-progress-track-bar"></div>
            </div>
            <p class="analysis-progress-percent"><span id="analysisProgressValue">0</span>% concluído</p>
        </div>
    </section>

    <script>
    (function () {
        const form = document.getElementById('videoUploadForm');
        const overlay = document.getElementById('analysisProgressOverlay');
        const progressBar = document.getElementById('analysisProgressBar');
        const progressValue = document.getElementById('analysisProgressValue');
        const stageText = document.getElementById('analysisProgressStage');
        const submitButton = document.getElementById('videoSubmitButton');
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
            return { width, height };
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
            series.forEach(function (point, index) {
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
            if (elapsedMs >= 150000) {
                return 'Consolidação final do vídeo...';
            }
            if (value >= 99) {
                return 'Consolidando resposta final no servidor...';
            }
            if (value >= 96) {
                return 'Análise quase concluída. Consolidando a leitura temporal...';
            }
            if (elapsedMs >= 60000 && value >= 84) {
                return 'Análise avançada em andamento no servidor. Mantenha esta aba aberta...';
            }
            if (value < 18) {
                return 'Recebendo vídeo e validando formato...';
            }
            if (value < 45) {
                return 'Extraindo quadros-chave e métricas temporais...';
            }
            if (value < 72) {
                return 'Executando OCR frame a frame...';
            }
            if (value < 92) {
                return 'Consolidando melhor leitura temporal...';
            }
            return 'Finalizando resposta e preparando relatório...';
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
            series = Array.from({ length: 38 }, function (_, index) {
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
            timerId = window.setInterval(function () {
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
        window.addEventListener('resize', function () {
            if (overlay.classList.contains('is-active')) {
                drawChart();
            }
        });
    }());
    </script>

    <?php if ($result && is_array($result) && $reportUrl !== '') { ?>
    <script>
    window.addEventListener('DOMContentLoaded', function () {
        const printBtn = document.getElementById('videoReportPrintBtn');
        const reportOpenLink = document.getElementById('videoReportOpenPdf');
        if (!printBtn) {
            return;
        }
        printBtn.addEventListener('click', function () {
            const reportUrl = (reportOpenLink && reportOpenLink.href) ? reportOpenLink.href : <?php echo json_encode($pythonApiUrl . '/pdf/' . urlencode(basename($reportUrl))); ?>;
            const printFrame = window.open(reportUrl, '_blank');
            if (printFrame) {
                printFrame.focus();
            }
        });
    });
    </script>
    <?php } ?>

    <?php if ($result && is_array($result)) { ?>
    <script>
    window.addEventListener('DOMContentLoaded', function () {
        const cards = Array.from(document.querySelectorAll('[data-video-target-card]'));
        const frameImage = document.getElementById('videoTargetFrame');
        const frameLink = document.getElementById('videoTargetFrameLink');
        const plateImage = document.getElementById('videoTargetPlate');
        const plateLink = document.getElementById('videoTargetPlateLink');
        const frameTitle = document.getElementById('videoTargetFrameTitle');
        const frameMeta = document.getElementById('videoTargetFrameMeta');
        const plateMeta = document.getElementById('videoTargetPlateMeta');
        const focusTitle = document.getElementById('videoTargetFocusTitle');
        const focusMeta = document.getElementById('videoTargetFocusMeta');
        const focusPlate = document.getElementById('videoTargetFocusPlate');
        const focusPattern = document.getElementById('videoTargetFocusPattern');
        const focusConfidence = document.getElementById('videoTargetFocusConfidence');
        const focusScore = document.getElementById('videoTargetFocusScore');
        const consolidationHeading = document.getElementById('videoConsolidationHeading');
        const consolidationTarget = document.getElementById('videoConsolidationTarget');
        const consolidationMinute = document.getElementById('videoConsolidationMinute');
        const consolidationPlate = document.getElementById('videoConsolidationPlate');
        const consolidationState = document.getElementById('videoConsolidationState');

        if (!cards.length || !frameImage || !frameLink || !plateImage || !plateLink || !frameTitle || !frameMeta || !plateMeta) {
            return;
        }

        function activateCard(card) {
            cards.forEach(function (item) {
                item.classList.toggle('is-active', item === card);
                item.setAttribute('aria-pressed', item === card ? 'true' : 'false');
            });

            const frameUrl = card.getAttribute('data-frame-url') || '';
            const plateUrl = card.getAttribute('data-plate-url') || frameUrl;
            const label = card.getAttribute('data-frame-label') || 'Quadro selecionado';
            const title = card.getAttribute('data-frame-title') || 'Sem OCR';
            const meta = card.getAttribute('data-frame-meta') || '';
            const score = card.getAttribute('data-frame-score') || '';
            const confidence = card.getAttribute('data-frame-confidence') || '';
            const pattern = card.getAttribute('data-frame-pattern') || '';
            const time = card.getAttribute('data-frame-time') || '';
            const minute = card.getAttribute('data-frame-minute') || '';
            const support = card.getAttribute('data-frame-support') || '';
            const hasMeaningfulTarget = Boolean(title && title !== 'Sem OCR' && title !== 'Indefinido');
            const targetLabel = hasMeaningfulTarget ? (title || label || 'Indefinido') : 'Nenhum alvo consolidado';
            const minuteLabel = hasMeaningfulTarget ? (minute || time || 'Indefinido') : 'Minuto indisponível';
            const plateLabel = hasMeaningfulTarget ? (title || 'Indefinido') : 'Sem leitura confiável';
            const supportLabel = hasMeaningfulTarget ? (support || 'Selecionado pelo operador') : 'Sem alvo consolidado';

            if (frameUrl) {
                frameImage.src = frameUrl;
                frameLink.href = frameUrl;
            }
            if (plateUrl) {
                plateImage.src = plateUrl;
                plateLink.href = plateUrl;
            }
            frameTitle.textContent = label + (time ? ' | ' + time : '');
            frameMeta.textContent = title + (pattern ? ' | ' + pattern : '') + (confidence ? ' | Confiança ' + confidence + '%' : '') + (score ? ' | Score ' + score : '');
            plateMeta.textContent = meta || 'Seleção documental atualizada pelo operador.';
            if (focusTitle) {
                focusTitle.textContent = label + (time ? ' | ' + time : '');
            }
            if (focusMeta) {
                const summaryParts = [];
                if (label) {
                    summaryParts.push(label);
                }
                if (time) {
                    summaryParts.push(time);
                }
                if (minute && minute !== time) {
                    summaryParts.push(minute);
                }
                if (pattern) {
                    summaryParts.push(pattern);
                }
                if (support) {
                    summaryParts.push(support);
                }
                focusMeta.textContent = summaryParts.join(' | ');
            }
            if (focusPlate) {
                focusPlate.textContent = 'Placa ' + (title || '-');
            }
            if (focusPattern) {
                focusPattern.textContent = 'Padrão ' + (pattern || 'Indefinido');
            }
            if (focusConfidence) {
                focusConfidence.textContent = 'Confiança ' + (confidence || '0,0') + '%';
            }
            if (focusScore) {
                focusScore.textContent = 'Score ' + (score || '0,0');
            }
            if (consolidationTarget) {
                consolidationTarget.textContent = targetLabel;
            }
            if (consolidationMinute) {
                consolidationMinute.textContent = minuteLabel;
            }
            if (consolidationPlate) {
                consolidationPlate.textContent = plateLabel;
            }
            const consolidationNote = document.querySelector('#videoConsolidationSummary .analysis-report-item-note');
            if (consolidationNote && !hasMeaningfulTarget) {
                consolidationNote.textContent = supportLabel;
            }
        }

        cards.forEach(function (card) {
            card.addEventListener('click', function () {
                activateCard(card);
            });
        });

        const preselected = cards.find(function (card) {
            return card.classList.contains('is-active');
        }) || cards[0];

        if (preselected) {
            activateCard(preselected);
        }
    });
    </script>
    <?php } ?>

    <?php if ($result && is_array($result)) { ?>
    <script>
    window.addEventListener('DOMContentLoaded', function () {
        const cards = Array.from(document.querySelectorAll('[data-video-target-card]'));
        const selectionStatus = document.getElementById('videoSelectionStatus');
        const clearBtn = document.getElementById('videoSelectionClearBtn');
        const finalizeBtn = document.getElementById('videoFinalizeBtn');
        const finalizeInlineBtn = document.getElementById('videoReportFinalizeBtnInline');
        const reportOpenLink = document.getElementById('videoReportOpenPdf');
        const printBtn = document.getElementById('videoReportPrintBtn');
        const selectedIdsField = document.getElementById('videoSelectedCandidateIds');
        const reportCard = document.getElementById('videoReport');
        const analysisTag = reportCard ? reportCard.querySelector('.analysis-report-cover-tag') : null;
        const analysisChip = reportCard ? reportCard.querySelector('.status-chip') : null;
        const finalizeUrl = <?php echo json_encode($pythonApiUrl . '/finalize_video'); ?>;
        const apiBase = <?php echo json_encode($pythonApiUrl); ?>;
        const analysisId = <?php echo json_encode($analysisId); ?>;

        if (!cards.length || !selectedIdsField) {
            return;
        }

        let selectedIds = [];
        try {
            const parsed = JSON.parse(selectedIdsField.value || '[]');
            if (Array.isArray(parsed)) {
                selectedIds = parsed.map(function (item) {
                    return String(item || '').trim();
                }).filter(Boolean);
            }
        } catch (error) {
            selectedIds = [];
        }

        if (!selectedIds.length && cards.length) {
            const fallbackCard = cards.find(function (card) {
                return card.classList.contains('is-selected');
            }) || cards[0];
            const fallbackId = fallbackCard ? (fallbackCard.getAttribute('data-candidate-id') || '') : '';
            if (fallbackId) {
                selectedIds = [fallbackId];
            }
        }

        function syncField() {
            selectedIdsField.value = JSON.stringify(selectedIds);
        }

        function updateStatus() {
            if (selectionStatus) {
                selectionStatus.textContent = selectedIds.length + ' selecionado' + (selectedIds.length === 1 ? '' : 's');
            }
            if (finalizeBtn) {
                finalizeBtn.disabled = selectedIds.length === 0;
            }
            if (finalizeInlineBtn) {
                finalizeInlineBtn.disabled = selectedIds.length === 0;
            }
            cards.forEach(function (card) {
                const candidateId = card.getAttribute('data-candidate-id') || '';
                const isSelected = selectedIds.indexOf(candidateId) !== -1;
                card.classList.toggle('is-selected', isSelected);
                card.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            });
        }

        function setReportState(reportUrl) {
            if (reportOpenLink && reportUrl) {
                reportOpenLink.href = reportUrl;
                reportOpenLink.textContent = 'Abrir PDF consolidado';
            }
            if (printBtn) {
                printBtn.textContent = 'Imprimir relatório consolidado';
            }
            if (analysisTag) {
                analysisTag.textContent = 'Disponível para impressão documental';
            }
            if (analysisChip) {
                analysisChip.textContent = 'Consolidado';
                analysisChip.classList.remove('status-chip--pending');
                analysisChip.classList.add('status-chip--ok');
            }
            if (consolidationHeading) {
                consolidationHeading.textContent = 'Alvo consolidado para impressão documental';
            }
            if (consolidationState) {
                consolidationState.textContent = 'Consolidado';
                consolidationState.classList.remove('status-chip--neutral');
                consolidationState.classList.add('status-chip--ok');
            }
        }

        function toggleSelection(card) {
            const candidateId = card.getAttribute('data-candidate-id') || '';
            if (!candidateId) {
                return;
            }
            if (selectedIds.indexOf(candidateId) !== -1) {
                selectedIds = selectedIds.filter(function (item) {
                    return item !== candidateId;
                });
            } else {
                selectedIds.push(candidateId);
            }
            syncField();
            updateStatus();
        }

        async function consolidateSelection() {
            if (!analysisId || selectedIds.length === 0) {
                return;
            }

            const formData = new FormData();
            formData.append('analysis_id', analysisId);
            selectedIds.forEach(function (candidateId) {
                formData.append('selected_candidate_ids[]', candidateId);
            });

            const previousFinalizeLabel = finalizeBtn ? finalizeBtn.textContent : '';
            const previousInlineLabel = finalizeInlineBtn ? finalizeInlineBtn.textContent : '';
            if (finalizeBtn) {
                finalizeBtn.disabled = true;
                finalizeBtn.textContent = 'Consolidando...';
            }
            if (finalizeInlineBtn) {
                finalizeInlineBtn.disabled = true;
                finalizeInlineBtn.textContent = 'Consolidando...';
            }

            try {
                const response = await fetch(finalizeUrl, {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin',
                });
                const result = await response.json().catch(function () {
                    return {};
                });
                if (!response.ok || !result || !result.report_url) {
                    throw new Error((result && result.error) ? result.error : 'Falha ao consolidar a seleção.');
                }

                const reportUrl = apiBase + result.report_url;
                setReportState(reportUrl);
                if (Array.isArray(result.selected_candidate_ids)) {
                    selectedIds = result.selected_candidate_ids.map(function (item) {
                        return String(item || '').trim();
                    }).filter(Boolean);
                    syncField();
                    updateStatus();
                }
                if (reportUrl) {
                    const win = window.open(reportUrl, '_blank');
                    if (win) {
                        win.focus();
                    }
                }
            } catch (error) {
                window.alert(error && error.message ? error.message : 'Falha ao consolidar a seleção.');
            } finally {
                if (finalizeBtn) {
                    finalizeBtn.textContent = previousFinalizeLabel || 'Consolidar seleção';
                }
                if (finalizeInlineBtn) {
                    finalizeInlineBtn.textContent = previousInlineLabel || 'Consolidar seleção';
                }
                updateStatus();
            }
        }

        cards.forEach(function (card) {
            card.addEventListener('click', function () {
                toggleSelection(card);
            });
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                selectedIds = [];
                syncField();
                updateStatus();
            });
        }

        if (finalizeBtn) {
            finalizeBtn.addEventListener('click', consolidateSelection);
        }
        if (finalizeInlineBtn) {
            finalizeInlineBtn.addEventListener('click', consolidateSelection);
        }

        syncField();
        updateStatus();
    });
    </script>
    <?php } ?>

        <?php if ($result && is_array($result)) { ?>
            <section class="card analysis-report-card video-report-card" id="videoReport">
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
                            <h2 class="analysis-report-cover-title">Relatório de apoio técnico à investigação - vídeo</h2>
                            <p class="analysis-report-cover-subtitle">
                                <?php echo htmlspecialchars($analysisStage === 'preview'
                                    ? 'Pré-análise em tela para correção antes da consolidação documental.'
                                    : 'Documento consolidado e pronto para impressão documental.'); ?>
                            </p>
                        </div>
                    </div>

                    <div class="analysis-report-cover-status">
                        <span class="status-chip <?php echo htmlspecialchars($analysisStage === 'preview' ? 'status-chip--pending' : 'status-chip--ok'); ?> status-chip--compact">
                            <?php echo htmlspecialchars($analysisModeLabel); ?>
                        </span>
                        <span class="analysis-report-cover-tag">
                            <?php echo htmlspecialchars($analysisStage === 'preview' ? 'Aguardando revisão em tela' : 'Disponível para impressão documental'); ?>
                        </span>
                    </div>

                    <div class="analysis-report-cover-meta">
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Identificação</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($analysisId !== '' ? $analysisId : '-'); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Pré-análise' : 'Consolidado'); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Arquivo de vídeo</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoFileName); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($resolutionText); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Alvo principal</span>
                            <strong class="analysis-report-item-value mono"><?php echo htmlspecialchars($bestText); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($bestPattern); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Consenso temporal</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($consensusRatioText); ?>%</strong>
                            <span class="analysis-report-item-note"><?php echo (int) $consensusCountText; ?> de <?php echo (int) $enginesConsideredText; ?> quadros</span>
                        </article>
                    </div>

                    <p class="analysis-report-cover-note">
                        <?php echo htmlspecialchars($analysisStage === 'preview'
                            ? 'Revise os alvos selecionados e, se necessário, marque ou desmarque cartões antes da consolidação. O resumo abaixo já deixa claro o alvo em foco e o minuto identificado.'
                            : 'O PDF consolidado já pode ser aberto para arquivamento e impressão, com o alvo e o minuto do quadro selecionado claramente documentados.'); ?>
                    </p>
                <?php if ($videoPartialHasEvidence) { ?>
                    <p class="analysis-report-cover-fragment-note">
                        <?php echo htmlspecialchars($videoPartialCoverNote); ?>
                    </p>
                <?php } ?>
                </div>

                <div class="video-document-summary" id="videoDocumentSummary">
                    <div class="video-document-summary-head">
                        <div>
                            <p class="analysis-report-eyebrow">Resumo técnico-documental</p>
                            <h3>Conferência visual e documental antes da impressão</h3>
                        </div>
                        <span class="status-chip <?php echo htmlspecialchars($analysisStage === 'preview' ? 'status-chip--pending' : 'status-chip--ok'); ?> status-chip--compact">
                            <?php echo htmlspecialchars($videoDocumentStatusText); ?>
                        </span>
                    </div>
                    <p class="video-document-summary-text">
                        Fluxo pericial: vídeo-fonte preservado, varredura frame a frame, alvos candidatos agrupados por minuto, quadro de maior valor probatório tratado, OCR em consenso e conferência humana antes da liberação documental.
                    </p>
                    <div class="analysis-report-summary-grid video-document-summary-grid">
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Status do relatório</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentStatusText); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($analysisStage === 'preview' ? 'Aguardando correção em tela.' : 'Disponível para impressão documental.'); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Identificação</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($analysisId !== '' ? $analysisId : '-'); ?></strong>
                            <span class="analysis-report-item-note">Análise em vídeo.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Fonte documental</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentSourceText); ?></strong>
                            <span class="analysis-report-item-note">Arquivo-fonte preservado para conferência.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Resolução do vídeo</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($resolutionText); ?></strong>
                            <span class="analysis-report-item-note">Dimensão nativa da captura.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Duração</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($durationText); ?></strong>
                            <span class="analysis-report-item-note">Tempo total do arquivo-fonte.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Cobertura temporal</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($frameSampling['coverage_label'] ?? 'Indefinido'); ?></strong>
                            <span class="analysis-report-item-note">Varredura do vídeo completo.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Intervalo de varredura</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentScanIntervalText); ?></strong>
                            <span class="analysis-report-item-note">Amostragem temporal em segundos.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Estratégia de varredura</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentStrategyLabel); ?></strong>
                            <span class="analysis-report-item-note">Método aplicado ao vídeo.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Taxa de quadros</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($fpsText); ?></strong>
                            <span class="analysis-report-item-note">Taxa percebida pelo decoder.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Quadros no vídeo</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($frameCountText); ?></strong>
                            <span class="analysis-report-item-note">Total de quadros no arquivo.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Quadros varridos</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($sampleCountText); ?></strong>
                            <span class="analysis-report-item-note">Quadros amostrados na pesquisa.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Quadros avaliados</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentFrameResultsCountText); ?></strong>
                            <span class="analysis-report-item-note">Submetidos ao OCR e ao consenso.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Candidatos apresentados</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentCandidatesText); ?></strong>
                            <span class="analysis-report-item-note">Elementos disponíveis para seleção.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Fragmentos parciais</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentPartialText); ?></strong>
                            <span class="analysis-report-item-note">Evidência curta preservada para confronto.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Alvos selecionados</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentSelectedTargetsText); ?></strong>
                            <span class="analysis-report-item-note">Marcados pelo operador na revisão.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Seleção do operador</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentOperatorSelectionText); ?></strong>
                            <span class="analysis-report-item-note">Ordem preservada na consolidação.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Integridade da captura</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($captureStatus); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($captureScoreText); ?>/100</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Consenso temporal</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($consensusRatioText); ?>%</strong>
                            <span class="analysis-report-item-note"><?php echo (int) $consensusCountText; ?> de <?php echo (int) $enginesConsideredText; ?> quadros</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Revisão humana</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($reviewStatus); ?></strong>
                            <span class="analysis-report-item-note"><?php echo $analysisStage === 'preview' ? 'Ajuste a hipótese antes de consolidar.' : 'Conferência registrada antes da impressão.'; ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Hash SHA-256 do vídeo</span>
                            <strong class="analysis-report-item-value mono"><?php echo htmlspecialchars($videoDocumentHashText); ?></strong>
                            <span class="analysis-report-item-note">Fingerprint da fonte digital.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Codec percebido</span>
                            <strong class="analysis-report-item-value"><?php echo htmlspecialchars($videoDocumentCodecText); ?></strong>
                            <span class="analysis-report-item-note">Parâmetro percebido pelo decoder.</span>
                        </article>
                    </div>
                </div>

                <div class="video-consolidation-summary" id="videoConsolidationSummary">
                    <div class="video-consolidation-summary-head">
                        <div>
                            <p class="analysis-report-eyebrow">Alvo consolidado</p>
                            <h3 id="videoConsolidationHeading"><?php echo htmlspecialchars($consolidationHeadingText); ?></h3>
                        </div>
                        <span id="videoConsolidationState" class="status-chip status-chip--neutral status-chip--compact"><?php echo htmlspecialchars($consolidationStateText); ?></span>
                    </div>
                    <div class="analysis-report-summary-grid video-consolidation-grid">
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Alvo</span>
                            <strong id="videoConsolidationTarget" class="analysis-report-item-value mono"><?php echo htmlspecialchars($selectedFrameSummaryTitle); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($selectedFrameSummarySupport); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Minuto</span>
                            <strong id="videoConsolidationMinute" class="analysis-report-item-value"><?php echo htmlspecialchars($selectedFrameSummaryMinute); ?></strong>
                            <span class="analysis-report-item-note">Faixa temporal do alvo.</span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Placa principal</span>
                            <strong id="videoConsolidationPlate" class="analysis-report-item-value mono"><?php echo htmlspecialchars($selectedFrameSummaryPlate); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($bestPattern); ?></span>
                        </article>
                        <article class="analysis-report-item">
                            <span class="analysis-report-item-label">Estado documental</span>
                            <strong id="videoConsolidationStatus" class="analysis-report-item-value"><?php echo htmlspecialchars($analysisModeLabel); ?></strong>
                            <span class="analysis-report-item-note"><?php echo htmlspecialchars($reviewStatus); ?></span>
                        </article>
                    </div>
                </div>

                <?php if ($videoPartialHasEvidence) { ?>
                <div class="video-partial-evidence">
                    <div class="video-partial-evidence-head">
                        <div>
                            <p class="analysis-report-eyebrow">Fragmentos parciais</p>
                            <h3>Leituras curtas preservadas para confronto</h3>
                        </div>
                        <span class="video-partial-evidence-badge"><?php echo (int) $videoPartialCandidatesCount; ?> fragmentos</span>
                    </div>
                    <p class="video-partial-evidence-text">
                        Esses fragmentos não são tratados como placa final. Eles são preservados como indício documental para confronto com veículo suspeito, minuto por minuto.
                    </p>
                    <div class="video-partial-grid" aria-label="Fragmentos parciais observados">
                        <?php foreach (array_slice($videoPartialCandidatesPreview, 0, 8) as $partialIndex => $partial) { ?>
                            <?php
                            if (!is_array($partial)) {
                                continue;
                            }
                            $partialText = cleanText($partial['text'] ?? $partial['normalized_text'] ?? 'Indefinido', 'Indefinido');
                            $partialMinute = cleanText($partial['minute_range'] ?? 'Indefinido', 'Indefinido');
                            $partialFrame = cleanInt($partial['frame_order'] ?? $partial['frame_index'] ?? ($partialIndex + 1));
                            $partialConfidence = number_format(cleanFloat($partial['best_confidence'] ?? $partial['avg_confidence'] ?? 0.0), 1, ',', '.');
                            $partialScore = number_format(cleanFloat($partial['best_score'] ?? $partial['avg_score'] ?? 0.0), 1, ',', '.');
                            $partialSupport = cleanText($partial['support_label'] ?? '', '');
                            $partialKind = cleanText($partial['fragment_kind'] ?? 'fragmento parcial', 'fragmento parcial');
                            $partialSlot = cleanText($partial['slot_hint'] ?? '', '');
                            $partialFrameUrl = trim((string) ($partial['frame_url'] ?? frameArtifactUrl($partial['frame_path'] ?? '')));
                            $partialPlateUrl = trim((string) ($partial['crop_treated_url'] ?? '')) ?: trim((string) ($partial['crop_raw_url'] ?? '')) ?: $partialFrameUrl;
                            $partialMediaUrl = $partialPlateUrl !== '' ? $partialPlateUrl : $partialFrameUrl;
                            ?>
                            <article class="video-partial-card">
                                <?php if ($partialMediaUrl !== '') { ?>
                                    <a class="video-partial-card-media" href="<?php echo htmlspecialchars($partialMediaUrl); ?>" target="_blank" rel="noopener">
                                        <img src="<?php echo htmlspecialchars($partialMediaUrl); ?>" alt="<?php echo htmlspecialchars($partialText); ?>">
                                    </a>
                                <?php } else { ?>
                                    <div class="video-partial-card-media">
                                        <span class="video-partial-card-fallback">Sem imagem associada</span>
                                    </div>
                                <?php } ?>
                                <div class="video-partial-card-copy">
                                    <strong><?php echo htmlspecialchars($partialText); ?></strong>
                                    <span><?php echo htmlspecialchars($partialKind); ?> | <?php echo htmlspecialchars($partialMinute); ?> | Quadro <?php echo htmlspecialchars(str_pad((string) $partialFrame, 2, '0', STR_PAD_LEFT)); ?></span>
                                    <em><?php echo htmlspecialchars('Confiança ' . $partialConfidence . '% | Score ' . $partialScore . ($partialSupport !== '' ? ' | ' . $partialSupport : '') . ($partialSlot !== '' ? ' | Slot ' . $partialSlot : '')); ?></em>
                                </div>
                            </article>
                        <?php } ?>
                    </div>
                </div>
                <?php } ?>

                <div class="video-target-focus-bar">
                    <div class="video-target-focus-copy">
                        <p class="analysis-report-eyebrow">Alvo ativo</p>
                        <strong id="videoTargetFocusTitle"><?php echo htmlspecialchars($selectedFrameTitle !== '' ? $selectedFrameTitle : ('Alvo ' . str_pad((string) $selectedFrameIndex, 2, '0', STR_PAD_LEFT) . ' | ' . $selectedFrameTimestamp)); ?></strong>
                        <span id="videoTargetFocusMeta">Quadro <?php echo htmlspecialchars(str_pad((string) $selectedFrameIndex, 2, '0', STR_PAD_LEFT)); ?> | <?php echo htmlspecialchars($selectedFrameTimestamp); ?> | <?php echo htmlspecialchars($selectedFrameMinute); ?><?php echo $selectedFrameSupport !== '' ? ' | ' . htmlspecialchars($selectedFrameSupport) : ''; ?></span>
                    </div>
                    <div class="video-target-focus-pills">
                        <span id="videoTargetFocusPlate" class="video-target-focus-pill">Placa <?php echo htmlspecialchars($bestText); ?></span>
                        <span id="videoTargetFocusPattern" class="video-target-focus-pill">Padrão <?php echo htmlspecialchars($selectedFramePattern); ?></span>
                        <span id="videoTargetFocusConfidence" class="video-target-focus-pill">Confiança <?php echo htmlspecialchars($selectedFrameConfidence); ?>%</span>
                        <span id="videoTargetFocusScore" class="video-target-focus-pill">Score <?php echo htmlspecialchars($selectedFrameScore); ?></span>
                    </div>
                </div>

                <div class="video-target-workbench">
                    <section class="video-target-stage">
                        <article class="video-target-stage-frame">
                            <span class="video-target-stage-label">Veículo em destaque</span>
                            <a id="videoTargetFrameLink" class="video-target-media-link" href="<?php echo htmlspecialchars($selectedFrameUrl); ?>" target="_blank" rel="noopener">
                                <img id="videoTargetFrame" src="<?php echo htmlspecialchars($selectedFrameUrl); ?>" alt="Quadro selecionado do veículo">
                            </a>
                            <div class="video-target-stage-caption">
                                <strong id="videoTargetFrameTitle"><?php echo htmlspecialchars($selectedFrameTitle !== '' ? $selectedFrameTitle : ('Alvo ' . str_pad((string) $selectedFrameIndex, 2, '0', STR_PAD_LEFT) . ' | ' . $selectedFrameTimestamp)); ?></strong>
                                <span id="videoTargetFrameMeta">Placa <?php echo htmlspecialchars($bestText); ?> | <?php echo htmlspecialchars($selectedFramePattern); ?> | Confiança <?php echo htmlspecialchars($selectedFrameConfidence); ?>% | Score <?php echo htmlspecialchars($selectedFrameScore); ?></span>
                            </div>
                        </article>
                        <article class="video-target-stage-plate">
                            <span class="video-target-stage-label">Captura da placa</span>
                            <a id="videoTargetPlateLink" class="video-target-media-link" href="<?php echo htmlspecialchars($selectedFrameCropPreviewUrl); ?>" target="_blank" rel="noopener">
                                <img id="videoTargetPlate" src="<?php echo htmlspecialchars($selectedFrameCropPreviewUrl); ?>" alt="Recorte selecionado da placa">
                            </a>
                            <div class="video-target-stage-caption">
                                <strong id="videoTargetPlateTitle">Recorte pericial</strong>
                                <span id="videoTargetPlateMeta">Clique em um cartão abaixo para trocar o alvo em destaque.</span>
                            </div>
                        </article>
                    </section>

                    <aside class="video-target-selector">
                        <div class="video-target-selector-head">
                            <div>
                                <p class="analysis-report-eyebrow">Seleção de alvo</p>
                                <h3 class="video-target-selector-title">Alvos detectados no vídeo inteiro</h3>
                            </div>
                            <span class="video-target-selector-badge"><?php echo htmlspecialchars($candidateCountText); ?> candidatos</span>
                        </div>
                        <p class="video-target-selector-text">
                            A varredura cobre todo o vídeo de até 10 minutos. Selecione um ou mais cartões para consolidar o PDF final exatamente sobre os alvos escolhidos pelo operador.
                        </p>
                        <div class="video-target-selector-actions">
                            <span id="videoSelectionStatus" class="video-target-selection-status">0 selecionados</span>
                            <button id="videoSelectionClearBtn" class="btn btn-secondary btn-small" type="button">Limpar seleção</button>
                            <button id="videoFinalizeBtn" class="btn btn-primary btn-small" type="button" <?php echo empty($videoCandidatesPreview) ? 'disabled' : ''; ?>>Consolidar seleção</button>
                        </div>
                        <input type="hidden" id="videoSelectedCandidateIds" value="<?php echo htmlspecialchars(json_encode($selectedCandidateIds)); ?>">
                        <div class="video-target-grid" aria-label="Candidatos de alvo">
                            <?php foreach (array_slice($videoCandidatesPreview ?: $frameResults, 0, 12) as $frameIndex => $frame) { ?>
                                <?php
                                if (!is_array($frame)) {
                                    continue;
                                }
                                $frameUrl = trim((string) ($frame['frame_url'] ?? frameArtifactUrl($frame['frame_path'] ?? '')));
                                $plateUrl = trim((string) ($frame['crop_treated_url'] ?? '')) ?: trim((string) ($frame['crop_raw_url'] ?? '')) ?: $frameUrl;
                                $candidateId = cleanText($frame['candidate_id'] ?? '', '');
                                $frameOrder = cleanInt($frame['rank'] ?? $frame['frame_order'] ?? ($frameIndex + 1));
                                $frameLabel = 'Alvo ' . str_pad((string) $frameOrder, 2, '0', STR_PAD_LEFT);
                                $frameTimestamp = formatVideoDuration(cleanFloat($frame['timestamp_seconds'] ?? 0.0));
                                $frameMinute = cleanText($frame['minute_range'] ?? '', 'Indefinido');
                                $frameText = cleanText($frame['text'] ?? $frame['ocr'] ?? 'Sem OCR', 'Sem OCR');
                                $framePattern = cleanText($frame['pattern'] ?? 'Indefinido', 'Indefinido');
                                $frameConfidence = number_format(cleanFloat($frame['best_confidence'] ?? $frame['confidence'] ?? 0.0), 1, ',', '.');
                                $frameScore = number_format(cleanFloat($frame['best_score'] ?? $frame['score'] ?? 0.0), 1, ',', '.');
                                $frameSupport = cleanText($frame['support_label'] ?? '', '');
                                $isSelected = in_array($candidateId, $selectedCandidateIds, true);
                                $isDefault = $candidateId !== '' && !empty($selectedCandidateIds) ? $isSelected : ($frameIndex === 0);
                                ?>
                                <button
                                    type="button"
                                    class="video-target-card<?php echo $isSelected ? ' is-selected' : ''; ?><?php echo $isDefault ? ' is-active' : ''; ?>"
                                    data-video-target-card
                                    data-candidate-id="<?php echo htmlspecialchars($candidateId); ?>"
                                    data-frame-url="<?php echo htmlspecialchars($frameUrl); ?>"
                                    data-plate-url="<?php echo htmlspecialchars($plateUrl); ?>"
                                    data-frame-label="<?php echo htmlspecialchars($frameLabel); ?>"
                                    data-frame-meta="<?php echo htmlspecialchars($frameMinute . ' | ' . $framePattern . ' | ' . $frameConfidence . '%'); ?>"
                                    data-frame-title="<?php echo htmlspecialchars($frameText); ?>"
                                    data-frame-score="<?php echo htmlspecialchars($frameScore); ?>"
                                    data-frame-confidence="<?php echo htmlspecialchars($frameConfidence); ?>"
                                    data-frame-pattern="<?php echo htmlspecialchars($framePattern); ?>"
                                    data-frame-time="<?php echo htmlspecialchars($frameTimestamp); ?>"
                                    data-frame-minute="<?php echo htmlspecialchars($frameMinute); ?>"
                                    data-frame-support="<?php echo htmlspecialchars($frameSupport); ?>"
                                    aria-pressed="<?php echo $isSelected ? 'true' : 'false'; ?>"
                                >
                                    <span class="video-target-card-index"><?php echo htmlspecialchars(str_pad((string) $frameOrder, 2, '0', STR_PAD_LEFT)); ?></span>
                                    <?php if ($frameUrl !== '') { ?>
                                        <img src="<?php echo htmlspecialchars($frameUrl); ?>" alt="<?php echo htmlspecialchars($frameLabel); ?>">
                                    <?php } ?>
                                    <div class="video-target-card-copy">
                                        <strong><?php echo htmlspecialchars($frameText); ?></strong>
                                        <span><?php echo htmlspecialchars($frameMinute); ?> | <?php echo htmlspecialchars($framePattern); ?> | <?php echo htmlspecialchars($frameConfidence); ?>% | Score <?php echo htmlspecialchars($frameScore); ?></span>
                                    </div>
                                </button>
                            <?php } ?>
                        </div>
                        <p class="video-target-selector-foot">Clique para marcar ou desmarcar. O PDF final seguirá a ordem de seleção do operador e preservará o minuto em que cada alvo foi identificado.</p>
                    </aside>
                </div>

                <div class="btn-row analysis-report-actions-panel">
                    <?php if ($reportUrl !== '') { ?>
                        <a id="videoReportOpenPdf" class="btn btn-primary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . '/pdf/' . urlencode(basename($reportUrl))); ?>">Abrir PDF documental</a>
                        <?php if ($manifestUrl !== '') { ?>
                            <a class="btn btn-secondary analysis-report-manifest-link" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $manifestUrl); ?>">Abrir manifesto pericial</a>
                        <?php } ?>
                        <button id="videoReportPrintBtn" class="btn btn-secondary" type="button">Imprimir relatório</button>
                        <button id="videoReportFinalizeBtnInline" class="btn btn-secondary" type="button">Consolidar seleção</button>
                    <?php } ?>
                    <?php if ($contactSheetUrl !== '') { ?>
                        <a class="btn btn-secondary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $contactSheetUrl); ?>">Abrir quadro-chave</a>
                    <?php } ?>
                    <?php if ($comparisonSheetUrl !== '') { ?>
                        <a class="btn btn-secondary" target="_blank" href="<?php echo htmlspecialchars($pythonApiUrl . $comparisonSheetUrl); ?>">Abrir comparação</a>
                    <?php } ?>
                    <span class="muted">Resultado consolidado, com artefatos individuais preservados para conferência documental.</span>
                </div>

                <div class="analysis-report-topics-panel">
                    <p class="analysis-report-section-label">Procedimentos efetuados na análise de vídeo</p>
                    <div class="analysis-report-outline">
                        <?php foreach ($analysisReportOutline as $outlineSection) { ?>
                            <?php if (!is_array($outlineSection)) { continue; } ?>
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
                                            <?php if (!is_array($outlineSubitem)) { continue; } ?>
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

                <?php if ($frameResults) { ?>
                    <p class="analysis-report-section-label">Quadros avaliados em ordem de pontuação</p>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Quadro</th>
                                    <th>Tempo</th>
                                    <th>OCR</th>
                                    <th>Confiança</th>
                                    <th>Padrão</th>
                                </tr>
                            </thead>
                            <tbody>
                        <?php foreach ($frameResults as $frame) { ?>
                                    <?php if (!is_array($frame)) { continue; } ?>
                                    <tr>
                                        <td><?php echo htmlspecialchars('Quadro ' . str_pad((string) cleanInt($frame['frame_order'] ?? 0), 2, '0', STR_PAD_LEFT)); ?></td>
                                        <td><?php echo htmlspecialchars(formatVideoDuration(cleanFloat($frame['timestamp_seconds'] ?? 0.0))); ?></td>
                                        <td><?php echo htmlspecialchars(cleanText($frame['ocr'] ?? '', 'Sem OCR')); ?></td>
                                        <td><?php echo htmlspecialchars(number_format(cleanFloat($frame['confidence'] ?? 0.0), 1, ',', '.')); ?>%</td>
                                        <td><?php echo htmlspecialchars(cleanText($frame['pattern'] ?? 'Indefinido', 'Indefinido')); ?></td>
                                    </tr>
                                <?php } ?>
                            </tbody>
                        </table>
                    </div>
                <?php } ?>
            </section>
        <?php } ?>
    </main>
</body>
</html>
