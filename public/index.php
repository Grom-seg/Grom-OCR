<?php

$root = dirname(__DIR__);
$envFile = $root . DIRECTORY_SEPARATOR . '.env';

function grom_env(string $key, ?string $default = null): ?string
{
    static $env = null;

    if ($env === null) {
        $env = [];
        $file = dirname(__DIR__) . DIRECTORY_SEPARATOR . '.env';

        if (is_file($file)) {
            foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
                if (str_starts_with(trim($line), '#') || !str_contains($line, '=')) {
                    continue;
                }

                [$k, $v] = explode('=', $line, 2);
                $env[trim($k)] = trim($v);
            }
        }
    }

    return $env[$key] ?? $default;
}

$tesseract = grom_env('TESSERACT_CMD');

$statusTesseract = is_file((string) $tesseract) ? 'OK' : 'NÃO ENCONTRADO';

?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <title>GROM OCR</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #f5f5f5;
        }

        .card {
            background: white;
            border-radius: 10px;
            padding: 24px;
            max-width: 720px;
            box-shadow: 0 2px 12px rgba(0,0,0,.08);
        }

        .ok {
            color: #0a7a2f;
            font-weight: bold;
        }

        .erro {
            color: #b00020;
            font-weight: bold;
        }

        code {
            background: #eee;
            padding: 2px 5px;
            border-radius: 4px;
        }
    </style>
</head>
<body>
<div class="card">
    <h1>GROM OCR</h1>
    <p>Sistema PHP carregado com sucesso.</p>

    <p><strong>PHP:</strong> <?= htmlspecialchars(PHP_VERSION) ?></p>

    <p>
        <strong>Tesseract:</strong>
        <span class="<?= $statusTesseract === 'OK' ? 'ok' : 'erro' ?>">
            <?= htmlspecialchars($statusTesseract) ?>
        </span>
    </p>

    <p><strong>Caminho:</strong> <code><?= htmlspecialchars((string) $tesseract) ?></code></p>

    <hr>

    <p>Base pronta para iniciar o módulo OCR de placas veiculares.</p>
</div>
</body>
</html>
