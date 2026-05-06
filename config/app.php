<?php
$pythonApiUrl = trim((string) (getenv('GROM_OCR_PYTHON_API_URL') ?: 'http://127.0.0.1:8000'));

if ($pythonApiUrl === '') {
    $pythonApiUrl = 'http://127.0.0.1:8000';
}

$pythonApiUrl = rtrim($pythonApiUrl, '/');
$parts = parse_url($pythonApiUrl);
if (is_array($parts) && isset($parts['host']) && strtolower((string) $parts['host']) === 'localhost') {
    $scheme = $parts['scheme'] ?? 'http';
    $port = isset($parts['port']) ? ':' . $parts['port'] : '';
    $path = $parts['path'] ?? '';
    $pythonApiUrl = $scheme . '://127.0.0.1' . $port . $path;
}

return [
    'python_api_url' => $pythonApiUrl,
    'ocr_min_confidence' => (float) (getenv('GROM_OCR_MIN_CONFIDENCE') ?: 75),
];
