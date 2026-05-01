<?php

class UseZapayWebhookStore {
    private const DEFAULT_MAX_EVENTS = 250;
    private const DEFAULT_HISTORY_LIMIT = 8;

    private static function envBool(string $name, bool $default): bool
    {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }

        $normalized = strtolower(trim((string) $value));
        if ($normalized === '') {
            return $default;
        }

        return in_array($normalized, ['1', 'true', 'yes', 'on', 'sim'], true);
    }

    private static function envInt(string $name, int $default): int
    {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }

        $parsed = (int) trim((string) $value);
        return $parsed > 0 ? $parsed : $default;
    }

    private static function cachePath(): string
    {
        $baseDir = dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'data';
        if (!is_dir($baseDir)) {
            @mkdir($baseDir, 0777, true);
        }

        return $baseDir . DIRECTORY_SEPARATOR . 'usezapay_cache.json';
    }

    private static function normalizePlate(string $value): string
    {
        $text = strtoupper(trim($value));
        return preg_replace('/[^A-Z0-9]/', '', $text);
    }

    private static function normalizeText(string $value): string
    {
        $text = trim($value);
        if ($text === '') {
            return '';
        }
        $text = preg_replace('/\s+/', ' ', $text);
        return trim((string) $text);
    }

    private static function defaultCache(): array
    {
        return [
            'version' => 1,
            'updated_at_utc' => null,
            'events' => [],
            'by_plate' => [],
            'by_request_id' => [],
        ];
    }

    private static function loadCache(): array
    {
        $path = self::cachePath();
        if (!is_file($path)) {
            return self::defaultCache();
        }

        $raw = @file_get_contents($path);
        if (!is_string($raw) || trim($raw) === '') {
            return self::defaultCache();
        }

        $decoded = json_decode($raw, true);
        if (!is_array($decoded)) {
            return self::defaultCache();
        }

        return array_replace_recursive(self::defaultCache(), $decoded);
    }

    private static function saveCache(array $cache): void
    {
        $cache['version'] = 1;
        $cache['updated_at_utc'] = gmdate('c');

        $maxEvents = self::envInt('GROM_OCR_USEZAPAY_CACHE_MAX_EVENTS', self::DEFAULT_MAX_EVENTS);
        if (isset($cache['events']) && is_array($cache['events']) && count($cache['events']) > $maxEvents) {
            $cache['events'] = array_values(array_slice($cache['events'], -$maxEvents));
        }

        if (!isset($cache['by_plate']) || !is_array($cache['by_plate'])) {
            $cache['by_plate'] = [];
        }
        if (!isset($cache['by_request_id']) || !is_array($cache['by_request_id'])) {
            $cache['by_request_id'] = [];
        }

        $json = json_encode($cache, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if (!is_string($json)) {
            return;
        }

        file_put_contents(self::cachePath(), $json, LOCK_EX);
    }

    private static function extractDataPayload(array $payload): array
    {
        if (isset($payload['data']) && is_array($payload['data'])) {
            return $payload['data'];
        }

        return $payload;
    }

    private static function extractVehiclePayload(array $payload): array
    {
        $data = self::extractDataPayload($payload);
        $vehicle = [];

        if (isset($data['vehicle']) && is_array($data['vehicle'])) {
            $vehicle = $data['vehicle'];
        } elseif (isset($payload['vehicle']) && is_array($payload['vehicle'])) {
            $vehicle = $payload['vehicle'];
        }

        if (!empty($vehicle) && !empty($data) && is_array($data)) {
            return array_merge($data, $vehicle);
        }

        if (!empty($vehicle)) {
            return $vehicle;
        }

        return is_array($data) ? $data : [];
    }

    private static function extractPlate(array $payload): string
    {
        $vehicle = self::extractVehiclePayload($payload);
        $candidates = [
            $vehicle['license_plate'] ?? '',
            $vehicle['placa'] ?? '',
            $vehicle['plate'] ?? '',
            $vehicle['plate_number'] ?? '',
            $payload['license_plate'] ?? '',
            $payload['placa'] ?? '',
            $payload['plate'] ?? '',
            $payload['plate_number'] ?? '',
            $payload['data']['license_plate'] ?? '',
            $payload['data']['placa'] ?? '',
        ];

        foreach ($candidates as $candidate) {
            $plate = self::normalizePlate((string) $candidate);
            if ($plate !== '') {
                return $plate;
            }
        }

        return '';
    }

    private static function extractRequestId(array $payload): string
    {
        $data = self::extractDataPayload($payload);
        $candidates = [
            $payload['request_id'] ?? '',
            $payload['requestId'] ?? '',
            $data['request_id'] ?? '',
            $data['requestId'] ?? '',
            $data['search_request_id'] ?? '',
        ];

        foreach ($candidates as $candidate) {
            $value = self::normalizeText((string) $candidate);
            if ($value !== '') {
                return $value;
            }
        }

        return '';
    }

    private static function summarizeDebts(array $payload): array
    {
        $data = self::extractDataPayload($payload);
        $debts = [];
        if (isset($data['debts']) && is_array($data['debts'])) {
            $debts = $data['debts'];
        } elseif (isset($payload['debts']) && is_array($payload['debts'])) {
            $debts = $payload['debts'];
        }

        $items = [];
        foreach ($debts as $debt) {
            if (!is_array($debt)) {
                continue;
            }
            $label = self::normalizeText((string) ($debt['name'] ?? $debt['description'] ?? $debt['type'] ?? $debt['detail'] ?? ''));
            if ($label === '') {
                continue;
            }
            $amount = self::normalizeText((string) ($debt['amount'] ?? $debt['value'] ?? ''));
            if ($amount !== '') {
                $label .= ' (' . $amount . ')';
            }
            $items[] = $label;
            if (count($items) >= 4) {
                break;
            }
        }

        return [
            'count' => count($debts),
            'summary' => !empty($items) ? implode(' | ', $items) : '',
        ];
    }

    private static function eventDedupKey(array $event): string
    {
        $requestId = self::normalizeText((string) ($event['request_id'] ?? ''));
        if ($requestId !== '') {
            return 'request_id:' . $requestId;
        }

        $plate = self::normalizePlate((string) ($event['plate'] ?? ''));
        $eventName = self::normalizeText((string) ($event['event'] ?? ''));
        $status = self::normalizeText((string) ($event['status'] ?? ''));
        $detail = self::normalizeText((string) ($event['detail'] ?? ''));
        return 'fallback:' . implode('|', [$plate, $eventName, $status, $detail]);
    }

    private static function normalizeWebhookPayload(array $payload, array $meta = []): array
    {
        $data = self::extractDataPayload($payload);
        $vehicle = self::extractVehiclePayload($payload);
        $plate = self::extractPlate($payload);
        $requestId = self::extractRequestId($payload);
        $debts = self::summarizeDebts($payload);

        $event = self::normalizeText((string) ($payload['event'] ?? $data['event'] ?? $meta['event'] ?? 'webhook_event'));
        $detail = self::normalizeText((string) ($payload['detail'] ?? $data['detail'] ?? $meta['detail'] ?? ''));
        $status = self::normalizeText((string) ($payload['status'] ?? $data['status'] ?? $meta['status'] ?? $event));
        $webhookId = self::normalizeText((string) (($payload['webhook']['id'] ?? null) ?? ($payload['webhook_id'] ?? null) ?? ($meta['webhook_id'] ?? '')));
        $resource = self::normalizeText((string) (($payload['webhook']['resource'] ?? null) ?? ($payload['resource'] ?? null) ?? ($meta['resource'] ?? 'vehicle_debt')));
        $version = self::normalizeText((string) (($payload['webhook']['version'] ?? null) ?? ($payload['version'] ?? null) ?? ($meta['version'] ?? 'v2')));

        $normalizedVehicle = [];
        foreach ([
            'license_plate',
            'placa',
            'plate',
            'plate_number',
            'make',
            'brand',
            'fabricante',
            'marca_modelo',
            'modelo',
            'model',
            'color',
            'cor',
            'year',
            'ano',
            'fabrication_year',
            'model_year',
            'chassis',
            'chassi',
            'vin',
            'renavam',
            'owner',
            'proprietario',
            'document',
            'cpf_cnpj',
            'state',
            'uf',
            'city',
            'cidade',
            'municipio',
            'restrictions',
            'restricoes',
        ] as $field) {
            if (!array_key_exists($field, $vehicle)) {
                continue;
            }
            $value = $vehicle[$field];
            if (is_array($value) || is_object($value)) {
                continue;
            }
            $normalizedVehicle[$field] = self::normalizeText((string) $value);
        }

        return [
            'received_at_utc' => gmdate('c'),
            'event' => $event !== '' ? $event : 'webhook_event',
            'status' => $status !== '' ? $status : $event,
            'detail' => $detail,
            'request_id' => $requestId,
            'event_key' => self::eventDedupKey([
                'request_id' => $requestId,
                'plate' => $plate,
                'event' => $event !== '' ? $event : 'webhook_event',
                'status' => $status !== '' ? $status : $event,
                'detail' => $detail,
            ]),
            'plate' => $plate,
            'vehicle' => $normalizedVehicle,
            'debts' => $debts,
            'webhook_id' => $webhookId,
            'resource' => $resource,
            'version' => $version,
            'signature_valid' => array_key_exists('signature_valid', $meta) ? (bool) $meta['signature_valid'] : null,
            'auth_valid' => array_key_exists('auth_valid', $meta) ? (bool) $meta['auth_valid'] : null,
            'source' => (string) ($meta['source'] ?? 'usezapay_webhook'),
            'raw_event' => self::envBool('GROM_OCR_USEZAPAY_STORE_RAW', false) ? $payload : null,
        ];
    }

    private static function persistEvent(array $event): array
    {
        $cache = self::loadCache();
        if (!isset($cache['events']) || !is_array($cache['events'])) {
            $cache['events'] = [];
        }

        $plate = self::normalizePlate((string) ($event['plate'] ?? ''));
        $requestId = self::normalizeText((string) ($event['request_id'] ?? ''));
        $eventKey = self::normalizeText((string) ($event['event_key'] ?? self::eventDedupKey($event)));
        $event['event_key'] = $eventKey;

        $replaced = false;
        foreach ($cache['events'] as $index => $existingEvent) {
            if (!is_array($existingEvent)) {
                continue;
            }
            $existingKey = self::normalizeText((string) ($existingEvent['event_key'] ?? self::eventDedupKey($existingEvent)));
            if ($existingKey !== '' && $existingKey === $eventKey) {
                $cache['events'][$index] = $event;
                $replaced = true;
                break;
            }
        }
        if (!$replaced) {
            $cache['events'][] = $event;
        }

        if ($plate !== '') {
            if (!isset($cache['by_plate'][$plate]) || !is_array($cache['by_plate'][$plate])) {
                $cache['by_plate'][$plate] = [
                    'latest' => null,
                    'history' => [],
                    'updated_at_utc' => null,
                    'latest_request_id' => '',
                ];
            }
            $plateEntry = $cache['by_plate'][$plate];
            if (!isset($plateEntry['history']) || !is_array($plateEntry['history'])) {
                $plateEntry['history'] = [];
            }
            $plateEntry['latest'] = $event;
            $plateEntry['updated_at_utc'] = $event['received_at_utc'] ?? gmdate('c');
            if ($requestId !== '') {
                $plateEntry['latest_request_id'] = $requestId;
            }
            $historyReplaced = false;
            foreach ($plateEntry['history'] as $historyIndex => $historyItem) {
                if (!is_array($historyItem)) {
                    continue;
                }
                $historyKey = self::normalizeText((string) ($historyItem['event_key'] ?? self::eventDedupKey($historyItem)));
                if ($historyKey !== '' && $historyKey === $eventKey) {
                    $plateEntry['history'][$historyIndex] = $event;
                    $historyReplaced = true;
                    break;
                }
            }
            if (!$historyReplaced) {
                $plateEntry['history'][] = $event;
            }
            if (count($plateEntry['history']) > self::DEFAULT_HISTORY_LIMIT) {
                $plateEntry['history'] = array_values(array_slice($plateEntry['history'], -self::DEFAULT_HISTORY_LIMIT));
            }
            $cache['by_plate'][$plate] = $plateEntry;
        }

        if ($requestId !== '') {
            $cache['by_request_id'][$requestId] = $event;
        }

        self::saveCache($cache);
        return $event;
    }

    public static function recordWebhookEvent(array $payload, array $meta = []): array
    {
        $event = self::normalizeWebhookPayload($payload, $meta);
        return self::persistEvent($event);
    }

    public static function registerPendingRequest(string $plate, string $requestId, array $meta = []): array
    {
        $normalizedPlate = self::normalizePlate($plate);
        $normalizedRequestId = self::normalizeText($requestId);
        $event = [
            'received_at_utc' => gmdate('c'),
            'event' => 'vehicle_debt_requested',
            'status' => 'pending_async',
            'detail' => self::normalizeText((string) ($meta['detail'] ?? 'consulta_enviada_aguardando_webhook')),
            'request_id' => $normalizedRequestId,
            'plate' => $normalizedPlate,
            'vehicle' => [
                'license_plate' => $normalizedPlate,
            ],
            'debts' => [
                'count' => 0,
                'summary' => '',
            ],
            'webhook_id' => '',
            'resource' => 'vehicle_debt',
            'version' => 'v2',
            'signature_valid' => null,
            'auth_valid' => null,
            'source' => 'usezapay_request',
            'raw_event' => null,
        ];

        return self::persistEvent($event);
    }

    public static function findLatestByPlate(string $plate): array
    {
        $normalizedPlate = self::normalizePlate($plate);
        if ($normalizedPlate === '') {
            return [];
        }

        $cache = self::loadCache();
        $entry = $cache['by_plate'][$normalizedPlate] ?? null;
        if (!is_array($entry)) {
            return [];
        }

        $latest = $entry['latest'] ?? null;
        return is_array($latest) ? $latest : [];
    }

    public static function findByRequestId(string $requestId): array
    {
        $normalizedRequestId = self::normalizeText($requestId);
        if ($normalizedRequestId === '') {
            return [];
        }

        $cache = self::loadCache();
        $entry = $cache['by_request_id'][$normalizedRequestId] ?? null;
        return is_array($entry) ? $entry : [];
    }

    public static function summarizePlateCache(string $plate): array
    {
        $normalizedPlate = self::normalizePlate($plate);
        if ($normalizedPlate === '') {
            return [];
        }

        $cache = self::loadCache();
        $entry = $cache['by_plate'][$normalizedPlate] ?? null;
        if (!is_array($entry)) {
            return [];
        }

        $latest = is_array($entry['latest'] ?? null) ? $entry['latest'] : [];
        $history = is_array($entry['history'] ?? null) ? $entry['history'] : [];
        return [
            'plate' => $normalizedPlate,
            'latest' => $latest,
            'history' => $history,
            'latest_request_id' => (string) ($entry['latest_request_id'] ?? ''),
            'updated_at_utc' => (string) ($entry['updated_at_utc'] ?? ''),
            'history_count' => count($history),
        ];
    }

    public static function summarizeRecentActivity(): array
    {
        $cache = self::loadCache();
        $events = is_array($cache['events'] ?? null) ? $cache['events'] : [];
        $plates = is_array($cache['by_plate'] ?? null) ? $cache['by_plate'] : [];

        $latestEvent = [];
        $latestTimestamp = null;

        $candidates = $events;
        if (empty($candidates) && !empty($plates)) {
            foreach ($plates as $plateEntry) {
                if (!is_array($plateEntry) || !is_array($plateEntry['latest'] ?? null)) {
                    continue;
                }
                $candidates[] = $plateEntry['latest'];
            }
        }

        foreach ($candidates as $candidate) {
            if (!is_array($candidate)) {
                continue;
            }

            $receivedAt = trim((string) ($candidate['received_at_utc'] ?? ''));
            $timestamp = $receivedAt !== '' ? strtotime($receivedAt) : false;
            if ($timestamp === false) {
                $timestamp = null;
            }

            if ($latestTimestamp === null || ($timestamp !== null && $timestamp >= $latestTimestamp)) {
                $latestTimestamp = $timestamp;
                $latestEvent = $candidate;
            }
        }

        $latestPlate = (string) ($latestEvent['plate'] ?? '');
        $latestRequestId = (string) ($latestEvent['request_id'] ?? '');
        $latestStatus = strtolower(trim((string) ($latestEvent['status'] ?? $latestEvent['event'] ?? '')));

        return [
            'latest' => $latestEvent,
            'latest_plate' => $latestPlate,
            'latest_request_id' => $latestRequestId,
            'latest_event' => (string) ($latestEvent['event'] ?? ''),
            'latest_status' => $latestStatus,
            'latest_detail' => (string) ($latestEvent['detail'] ?? ''),
            'updated_at_utc' => (string) ($latestEvent['received_at_utc'] ?? ($cache['updated_at_utc'] ?? '')),
            'history_count' => count($events),
            'plate_count' => count($plates),
        ];
    }
}
