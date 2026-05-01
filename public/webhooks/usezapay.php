<?php

require_once __DIR__ . '/../../app/services/UseZapayWebhookStore.php';

if (strtoupper($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    http_response_code(405);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'method_not_allowed'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$rawBody = file_get_contents('php://input');
$rawBody = is_string($rawBody) ? $rawBody : '';
$payload = json_decode($rawBody, true);
if (!is_array($payload)) {
    http_response_code(400);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'invalid_json'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$secret = trim((string) (getenv('GROM_OCR_USEZAPAY_WEBHOOK_SECRET') ?: ''));
$signatureHeader = trim((string) (
    $_SERVER['HTTP_X_HMAC_SIGNATURE']
    ?? $_SERVER['HTTP_X_HMAC']
    ?? $_SERVER['HTTP_X_SIGNATURE']
    ?? ''
));
$signatureValid = true;
if ($secret !== '') {
    $calculated = hash_hmac('sha256', $rawBody, $secret);
    $signatureValid = hash_equals($calculated, $signatureHeader);
}

$authToken = trim((string) (getenv('GROM_OCR_USEZAPAY_WEBHOOK_AUTH_TOKEN') ?: ''));
$authHeaderName = strtoupper(trim((string) (getenv('GROM_OCR_USEZAPAY_WEBHOOK_AUTH_HEADER') ?: 'Authorization')));
$authPrefix = trim((string) (getenv('GROM_OCR_USEZAPAY_WEBHOOK_AUTH_PREFIX') ?: ''));
$headerKey = 'HTTP_' . strtoupper(str_replace('-', '_', $authHeaderName));
$authHeaderValue = trim((string) ($_SERVER[$headerKey] ?? ''));
$authValid = true;
if ($authToken !== '') {
    $normalizedHeader = $authHeaderValue;
    if ($authPrefix !== '' && stripos($normalizedHeader, $authPrefix . ' ') === 0) {
        $normalizedHeader = trim(substr($normalizedHeader, strlen($authPrefix)));
    }
    $authValid = hash_equals($authToken, $normalizedHeader);
}

if (!$signatureValid || !$authValid) {
    http_response_code(401);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'error' => 'unauthorized_webhook',
        'signature_valid' => $signatureValid,
        'auth_valid' => $authValid,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$stored = UseZapayWebhookStore::recordWebhookEvent($payload, [
    'signature_valid' => $signatureValid,
    'auth_valid' => $authValid,
    'source' => 'usezapay_webhook',
]);

header('Content-Type: application/json; charset=utf-8');
http_response_code(200);
echo json_encode([
    'status' => 'ok',
    'received' => true,
    'event' => (string) ($stored['event'] ?? ''),
    'request_id' => (string) ($stored['request_id'] ?? ''),
    'plate' => (string) ($stored['plate'] ?? ''),
    'stored' => true,
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
