<?php
session_start();
if (!isset($_SESSION['user_id'])) {
    header('Location: /login.php');
    exit;
}

require_once __DIR__ . '/../app/models/Case.php';
require_once __DIR__ . '/../app/models/User.php';
require_once __DIR__ . '/../app/services/DatabaseConnection.php';

$app = require __DIR__ . '/../config/app.php';
$db = require __DIR__ . '/../config/database.php';
$pythonApiUrl = $app['python_api_url'];
$operatorLabel = User::resolveSessionLabel($_SESSION);
$analises = [];
$loadError = null;
$loadWarning = null;

try {
    $pdo = null;
    try {
        $pdo = DatabaseConnection::create($db);
    } catch (Throwable $databaseException) {
        $loadWarning = 'Banco indisponivel no momento; exibindo historico salvo em fallback local.';
    }

    $caseModel = new CaseModel($pdo);
    $analises = $caseModel->allByUser($_SESSION['user_id']);
} catch (Throwable $exception) {
    $loadError = 'Nao foi possivel carregar o historico: ' . $exception->getMessage();
}

function resolveHistoricalPlatePattern(array $ocr, $colorInfoRaw): string
{
    $normalize = static function (string $value): string {
        $text = trim($value);
        if ($text === 'Antiga (cinza)') {
            return 'Antigo';
        }
        return $text === '' ? 'Indefinido' : $text;
    };

    $patternFromBest = trim((string) ($ocr['best']['pattern'] ?? ''));
    if ($patternFromBest !== '') {
        return $normalize($patternFromBest);
    }

    $colorInfo = json_decode((string) $colorInfoRaw, true);
    if (is_array($colorInfo)) {
        $patternFromColorInfo = trim((string) ($colorInfo['padrao_placa'] ?? $colorInfo['detected_pattern'] ?? ''));
        if ($patternFromColorInfo !== '') {
            return $normalize($patternFromColorInfo);
        }
    }

    return 'Indefinido';
}
?>
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Histórico de Análises - Grom_OCR</title>
    <link rel="stylesheet" href="/assets/app.css">
    <link rel="icon" type="image/png" href="/assets/grom-favicon.png">
</head>
<body>
    <main class="page-shell">
        <header class="topbar">
            <div class="brand">
                <div class="brand-mark">
                    <img src="/assets/grom-report-logo.png" alt="Grom OCR">
                </div>
                <div>
                    <h1 class="brand-title">Histórico de Análises</h1>
                    <p class="brand-subtitle">Rastreio completo de execuções OCR realizadas pelo operador</p>
                    <div class="analysis-topbar-identity">
                        <span class="analysis-topbar-identity-label">Operador</span>
                        <strong class="analysis-topbar-identity-value"><?php echo htmlspecialchars($operatorLabel); ?></strong>
                    </div>
                </div>
            </div>
            <nav class="nav-links">
                <a class="nav-link" href="/">Dashboard</a>
                <a class="nav-link" href="/upload.php">Nova análise</a>
                <a class="nav-link active" href="/historico.php">Histórico</a>
                <a class="nav-link" href="/logout.php">Sair</a>
            </nav>
        </header>

        <section class="card">
            <h2 class="card-title">Registros salvos</h2>
            <p class="card-subtitle">Cada item abaixo representa uma análise persistida no banco.</p>

            <?php if ($loadError) { ?>
                <div class="alert alert-danger"><?php echo htmlspecialchars($loadError); ?></div>
            <?php } else { ?>
                <?php if ($loadWarning) { ?>
                    <div class="alert alert-warning"><?php echo htmlspecialchars($loadWarning); ?></div>
                <?php } ?>
                <?php if (!$analises) { ?>
                    <div class="alert alert-warning">Nenhuma análise registrada até o momento.</div>
                <?php } else { ?>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Data/Hora</th>
                                <th>Arquivo</th>
                                <th>Analysis ID</th>
                                <th>Placa (OCR)</th>
                                <th>Confianca</th>
                                <th>Nivel probatorio</th>
                                <th>Revisao manual</th>
                                <th>PDF</th>
                                <th>Origem</th>
                                <th>Padrao placa</th>
                                <th>Adulteracao</th>
                            </tr>
                        </thead>
                        <tbody>
                        <?php foreach ($analises as $analise) {
                            $ocr = json_decode($analise['ocr'], true);
                            if (!is_array($ocr)) {
                                $ocr = [];
                            }
                            $placa = isset($ocr['best']['text']) ? (string) $ocr['best']['text'] : '-';
                            $confianca = isset($ocr['best']['avg_conf']) ? number_format((float) $ocr['best']['avg_conf'], 1, ',', '.') . '%' : '-';
                            $analysisId = isset($ocr['forensic']['analysis_id']) ? (string) $ocr['forensic']['analysis_id'] : '-';
                            $evidenceLevel = isset($ocr['assessment']['evidence_level']) ? (string) $ocr['assessment']['evidence_level'] : 'BAIXA';
                            $manualReview = !empty($ocr['assessment']['manual_review_required']) ? 'Sim' : 'Nao';
                            $padraoPlaca = resolveHistoricalPlatePattern($ocr, $analise['color_info'] ?? '');
                            $adulteracao = !empty($analise['adulteracao']) ? 'Sim' : 'Nao';
                        ?>
                            <tr>
                                <td><?php echo htmlspecialchars((string) $analise['datahora']); ?></td>
                                <td><?php echo htmlspecialchars((string) $analise['filename']); ?></td>
                                <td class="mono"><?php echo htmlspecialchars($analysisId); ?></td>
                                <td><?php echo htmlspecialchars($placa); ?></td>
                                <td><?php echo htmlspecialchars($confianca); ?></td>
                                <td><?php echo htmlspecialchars($evidenceLevel); ?></td>
                                <td><?php echo htmlspecialchars($manualReview); ?></td>
                                <td>
                                    <?php if (!empty($analise['pdf'])) { ?>
                                        <a href="<?php echo htmlspecialchars($pythonApiUrl . '/pdf/' . urlencode((string) $analise['pdf'])); ?>" target="_blank">Abrir</a>
                                    <?php } else { ?>
                                        -
                                    <?php } ?>
                                </td>
                                <td><?php echo htmlspecialchars((string) $analise['origem']); ?></td>
                                <td><?php echo htmlspecialchars($padraoPlaca); ?></td>
                                <td><?php echo htmlspecialchars($adulteracao); ?></td>
                            </tr>
                        <?php } ?>
                        </tbody>
                    </table>
                </div>
                <?php } ?>
            <?php } ?>
        </section>
    </main>
</body>
</html>
