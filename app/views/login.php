<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - Grom_OCR</title>
    <link rel="stylesheet" href="/assets/app.css">
    <link rel="icon" type="image/png" href="/assets/grom-favicon.png">
</head>
<body class="auth-page">
    <main class="login-wrap auth-shell">
        <section class="auth-hero">
            <div class="auth-hero-content">
                <div class="auth-hero-brand">
                    <div class="brand-mark brand-mark--hero">
                        <img src="/assets/grom-report-logo.png" alt="Grom OCR">
                    </div>
                    <div>
                        <p class="analysis-report-eyebrow">Acesso institucional</p>
                        <h1 class="auth-hero-title">Grom_OCR</h1>
                    </div>
                </div>

                <p class="auth-hero-subtitle">
                    Plataforma de apoio técnico à investigação com OCR de placas, cadeia de custódia digital e impressão documental formal.
                </p>

                <ul class="auth-hero-list">
                    <li>Imagem original preservada para comparação pericial e conferência humana.</li>
                    <li>Recorte bruto, recorte tratado e metadados organizados no mesmo fluxo.</li>
                    <li>Identidade visual formal, consistente em tela e no PDF final.</li>
                </ul>

                <p class="auth-hero-foot">Acesso restrito a operadores autorizados.</p>
            </div>
        </section>

        <section class="card login-card auth-panel">
            <p class="analysis-report-eyebrow">Painel protegido</p>
            <h2 class="card-title">Acesso ao sistema</h2>
            <p class="card-subtitle">Entre com suas credenciais para iniciar a análise.</p>

            <?php if (!empty($securityWarning)) { ?>
                <div class="alert alert-warning"><?php echo htmlspecialchars($securityWarning); ?></div>
            <?php } ?>

            <?php if (!empty($error)) { ?>
                <div class="alert alert-danger"><?php echo htmlspecialchars($error); ?></div>
            <?php } ?>

            <form method="POST" action="/login.php">
                <div class="field">
                    <label class="field-label" for="user">Usuário</label>
                    <input id="user" name="user" type="text" autocomplete="username" required>
                </div>
                <div class="field" style="margin-top:12px;">
                    <label class="field-label" for="pass">Senha</label>
                    <input id="pass" name="pass" type="password" autocomplete="current-password" required>
                </div>
                <div class="btn-row">
                    <button class="btn btn-primary" type="submit">Entrar</button>
                </div>
            </form>
        </section>
    </main>
</body>
</html>
