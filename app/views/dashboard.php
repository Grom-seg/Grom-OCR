<?php
require_once __DIR__ . '/../models/User.php';
$operatorLabel = User::resolveSessionLabel($_SESSION);
?>
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Dashboard - Grom_OCR</title>
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
                    <h1 class="brand-title">Grom_OCR</h1>
                    <p class="brand-subtitle">Central de inteligência para apoio técnico à leitura de placas</p>
                    <div class="analysis-topbar-identity">
                        <span class="analysis-topbar-identity-label">Operador</span>
                        <strong class="analysis-topbar-identity-value"><?php echo htmlspecialchars($operatorLabel); ?></strong>
                    </div>
                </div>
            </div>
            <nav class="nav-links">
                <a class="nav-link active" href="/">Dashboard</a>
                <a class="nav-link" href="/upload.php">Nova análise</a>
                <a class="nav-link" href="/historico.php">Histórico</a>
                <a class="nav-link" href="/logout.php">Sair</a>
            </nav>
        </header>

        <section class="card">
            <h2 class="card-title">Ambiente operacional pronto</h2>
            <p class="card-subtitle">
                Use o fluxo de upload para processar imagens, consolidar consenso entre motores e gerar relatório com cadeia de custódia digital.
            </p>
            <div class="grid">
                <div class="col-4 kpi">
                    <p class="kpi-label">Pipeline</p>
                    <p class="kpi-value">OCR Multi-engine</p>
                </div>
                <div class="col-4 kpi">
                    <p class="kpi-label">Saida</p>
                    <p class="kpi-value">Placa + Cadeia digital</p>
                </div>
                <div class="col-4 kpi">
                    <p class="kpi-label">Rastreabilidade</p>
                    <p class="kpi-value">Histórico + Audit Log</p>
                </div>
            </div>
            <div class="btn-row">
                <a class="btn btn-primary" href="/upload.php">Iniciar nova analise</a>
                <a class="btn btn-secondary" href="/historico.php">Abrir historico</a>
            </div>
        </section>

        <?php if (!empty($zapayDashboard) && is_array($zapayDashboard)) { ?>
            <section class="card">
                <h2 class="card-title">Painel de validacao veicular</h2>
                <p class="card-subtitle">
                    <?php echo htmlspecialchars((string) ($zapayDashboard['subtitle'] ?? 'Resumo da ultima validacao veicular disponivel no cache local.')); ?>
                </p>
                <div class="analysis-status-panel" style="margin-top:0;">
                    <div class="analysis-status-header">
                        <div>
                            <p class="muted" style="margin:0;">Estado global</p>
                            <div class="status-chip <?php echo htmlspecialchars((string) ($zapayDashboard['chip_class'] ?? 'status-chip--neutral')); ?>">
                                <?php echo htmlspecialchars((string) ($zapayDashboard['chip_label'] ?? 'Indefinido')); ?>
                            </div>
                        </div>
                        <div class="btn-row" style="margin:0;">
                            <a class="btn btn-primary" href="/upload.php">Abrir monitor</a>
                            <a class="btn btn-secondary" href="/historico.php">Ver historico</a>
                        </div>
                    </div>
                    <div class="status-row">
                        <div class="status-box">
                            <p class="status-box-label">Ultima placa</p>
                            <p class="status-box-value"><?php echo htmlspecialchars((string) ($zapayDashboard['plate'] ?? '-')); ?></p>
                        </div>
                        <div class="status-box">
                            <p class="status-box-label">Request ID</p>
                            <p class="status-box-value"><?php echo htmlspecialchars((string) ($zapayDashboard['request_id'] ?? '-')); ?></p>
                        </div>
                        <div class="status-box">
                            <p class="status-box-label">Evento</p>
                            <p class="status-box-value"><?php echo htmlspecialchars((string) ($zapayDashboard['event'] ?? '-')); ?></p>
                        </div>
                        <div class="status-box">
                            <p class="status-box-label">Atualizacao UTC</p>
                            <p class="status-box-value"><?php echo htmlspecialchars((string) ($zapayDashboard['updated_at_utc'] ?? '-')); ?></p>
                        </div>
                        <div class="status-box">
                            <p class="status-box-label">Histórico local</p>
                            <p class="status-box-value"><?php echo (int) ($zapayDashboard['history_count'] ?? 0); ?> eventos</p>
                        </div>
                        <div class="status-box">
                            <p class="status-box-label">Placas no cache</p>
                            <p class="status-box-value"><?php echo (int) ($zapayDashboard['plate_count'] ?? 0); ?> placas</p>
                        </div>
                    </div>
                    <p class="muted" style="margin:12px 0 0;">
                        <?php echo htmlspecialchars((string) ($zapayDashboard['detail'] ?? '')); ?>
                    </p>
                    <p class="muted" style="margin:6px 0 0;">
                        <?php echo htmlspecialchars((string) ($zapayDashboard['summary'] ?? '')); ?>
                    </p>
                </div>
            </section>
        <?php } ?>
    </main>
</body>
</html>
