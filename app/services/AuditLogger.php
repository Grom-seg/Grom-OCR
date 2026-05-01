<?php
class AuditLogger {
    private static function defaultPath(): string
    {
        $customPath = getenv('GROM_OCR_AUDIT_LOG_PATH');
        if (is_string($customPath) && trim($customPath) !== '') {
            return trim($customPath);
        }

        return dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'data' . DIRECTORY_SEPARATOR . 'audit_events.log';
    }

    /**
     * Registro append-only em JSON Lines.
     * Retorna true em sucesso e false em falha silenciosa.
     */
    public static function logEvent(string $eventType, array $payload): bool
    {
        $path = self::defaultPath();
        $dir = dirname($path);
        if (!is_dir($dir) && !@mkdir($dir, 0777, true) && !is_dir($dir)) {
            return false;
        }

        $record = [
            'event_type' => $eventType,
            'event_time_utc' => gmdate('Y-m-d\TH:i:s\Z'),
            'payload' => $payload,
        ];

        $line = json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if (!is_string($line)) {
            return false;
        }

        return file_put_contents($path, $line . PHP_EOL, FILE_APPEND | LOCK_EX) !== false;
    }
}
