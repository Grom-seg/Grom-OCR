<?php

session_start();
if (!isset($_SESSION['user_id'])) {
    http_response_code(401);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'unauthorized'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

require_once __DIR__ . '/../../app/services/UseZapayWebhookStore.php';

$plate = '';
$requestId = '';

if (strtoupper($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    $payload = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($payload)) {
        $payload = $_POST;
    }
    $plate = trim((string) ($payload['plate'] ?? $payload['placa'] ?? ''));
    $requestId = trim((string) ($payload['request_id'] ?? $payload['requestId'] ?? ''));
} else {
    $plate = trim((string) ($_GET['plate'] ?? $_GET['placa'] ?? ''));
    $requestId = trim((string) ($_GET['request_id'] ?? $_GET['requestId'] ?? ''));
}

$lookup = [];
$summary = [];

if ($requestId !== '') {
    $lookup = UseZapayWebhookStore::findByRequestId($requestId);
    if ($lookup && !$plate) {
        $plate = (string) ($lookup['plate'] ?? '');
    }
    if ($plate !== '') {
        $summary = UseZapayWebhookStore::summarizePlateCache($plate);
    }
}

if (!$lookup && $plate !== '') {
    $lookup = UseZapayWebhookStore::findLatestByPlate($plate);
    $summary = UseZapayWebhookStore::summarizePlateCache($plate);
}

header('Content-Type: application/json; charset=utf-8');
echo json_encode([
    'status' => !empty($lookup) ? 'ok' : 'not_found',
    'plate' => $plate !== '' ? $plate : null,
    'request_id' => $requestId !== '' ? $requestId : null,
    'latest' => $lookup ?: null,
    'summary' => $summary ?: null,
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
