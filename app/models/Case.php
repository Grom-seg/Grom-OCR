<?php
class CaseModel {
    private $pdo;
    private $fallbackPath;

    public function __construct($pdo = null, $fallbackPath = null) {
        $this->pdo = $pdo;
        $this->fallbackPath = $fallbackPath ?: dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'data' . DIRECTORY_SEPARATOR . 'analises_fallback.json';
    }

    public function save($user_id, $filename, $ocr, $pdf, $datahora, $origem, $color_info, $adulteracao) {
        if ($this->pdo instanceof PDO) {
            $stmt = $this->pdo->prepare('INSERT INTO analises (user_id, filename, ocr, pdf, datahora, origem, color_info, adulteracao) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([$user_id, $filename, json_encode($ocr), $pdf, $datahora, $origem, json_encode($color_info), $adulteracao]);
            return $this->pdo->lastInsertId();
        }

        $records = $this->readFallbackRecords();
        $nextId = 1;
        if (!empty($records)) {
            $ids = array_column($records, 'id');
            $nextId = ((int) max($ids)) + 1;
        }

        $records[] = [
            'id' => $nextId,
            'user_id' => (int) $user_id,
            'filename' => (string) $filename,
            'ocr' => json_encode($ocr),
            'pdf' => (string) $pdf,
            'datahora' => (string) $datahora,
            'origem' => (string) $origem,
            'color_info' => json_encode($color_info),
            'adulteracao' => (int) $adulteracao,
        ];

        $this->writeFallbackRecords($records);
        return $nextId;
    }

    public function allByUser($user_id) {
        if ($this->pdo instanceof PDO) {
            $stmt = $this->pdo->prepare('SELECT * FROM analises WHERE user_id = ? ORDER BY datahora DESC');
            $stmt->execute([$user_id]);
            return $stmt->fetchAll(PDO::FETCH_ASSOC);
        }

        $records = $this->readFallbackRecords();
        $filtered = array_values(array_filter($records, function ($item) use ($user_id) {
            return isset($item['user_id']) && (int) $item['user_id'] === (int) $user_id;
        }));

        usort($filtered, function ($left, $right) {
            return strcmp((string) ($right['datahora'] ?? ''), (string) ($left['datahora'] ?? ''));
        });

        return $filtered;
    }

    private function normalizePlate($value) {
        $text = strtoupper((string) $value);
        return preg_replace('/[^A-Z0-9]/', '', $text);
    }

    public function findByPlate($user_id, $plate, $limit = 20) {
        $target = $this->normalizePlate($plate);
        if ($target === '' || strlen($target) < 7) {
            return [];
        }

        $all = $this->allByUser($user_id);
        $matches = [];
        foreach ($all as $record) {
            $ocrRaw = $record['ocr'] ?? '';
            $ocrData = json_decode((string) $ocrRaw, true);
            if (!is_array($ocrData)) {
                continue;
            }

            $bestText = $this->normalizePlate($ocrData['best']['text'] ?? '');
            if ($bestText !== $target) {
                continue;
            }

            $matches[] = [
                'id' => $record['id'] ?? null,
                'datahora' => (string) ($record['datahora'] ?? ''),
                'filename' => (string) ($record['filename'] ?? ''),
                'engine' => (string) ($ocrData['best']['engine'] ?? ''),
                'avg_conf' => (float) ($ocrData['best']['avg_conf'] ?? 0),
                'analysis_id' => (string) ($ocrData['forensic']['analysis_id'] ?? ''),
            ];

            if (count($matches) >= max(1, (int) $limit)) {
                break;
            }
        }

        return $matches;
    }

    private function readFallbackRecords() {
        if (!file_exists($this->fallbackPath)) {
            return [];
        }

        $raw = @file_get_contents($this->fallbackPath);
        if ($raw === false || trim($raw) === '') {
            return [];
        }

        $decoded = json_decode($raw, true);
        return is_array($decoded) ? $decoded : [];
    }

    private function writeFallbackRecords(array $records) {
        $dir = dirname($this->fallbackPath);
        if (!is_dir($dir)) {
            mkdir($dir, 0777, true);
        }

        file_put_contents(
            $this->fallbackPath,
            json_encode($records, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT),
            LOCK_EX
        );
    }
}
