<?php
class DatabaseConnection {
    private static function looksUnset($value) {
        if ($value === null) {
            return true;
        }

        $value = trim((string) $value);
        if ($value === '') {
            return true;
        }

        return preg_match('/^(SEU|SUA)_/i', $value) === 1;
    }

    private static function envFlagEnabled($name, $default = false) {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }

        $normalized = strtolower(trim((string) $value));
        if ($normalized === '') {
            return $default;
        }

        return in_array($normalized, ['1', 'true', 'yes', 'on'], true);
    }

    private static function sqlitePath() {
        $customPath = getenv('GROM_OCR_SQLITE_PATH');
        if ($customPath !== false && trim((string) $customPath) !== '') {
            return trim((string) $customPath);
        }

        return dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'data' . DIRECTORY_SEPARATOR . 'grom_ocr.sqlite';
    }

    private static function createSqliteConnection() {
        $sqlitePath = self::sqlitePath();
        $sqliteDir = dirname($sqlitePath);

        if (!is_dir($sqliteDir)) {
            mkdir($sqliteDir, 0777, true);
        }

        $pdo = new PDO('sqlite:' . $sqlitePath, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);

        self::ensureSqliteSchema($pdo);
        return $pdo;
    }

    private static function ensureSqliteSchema(PDO $pdo) {
        $pdo->exec("
            CREATE TABLE IF NOT EXISTS analises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT,
                ocr TEXT,
                pdf TEXT,
                datahora TEXT,
                origem TEXT,
                color_info TEXT,
                adulteracao INTEGER
            )
        ");

        $pdo->exec("CREATE INDEX IF NOT EXISTS idx_analises_user_id ON analises(user_id)");
    }

    private static function createMysqlConnection(array $db) {
        $pass = array_key_exists('pass', $db) ? $db['pass'] : null;

        if (
            self::looksUnset($db['host'] ?? null) ||
            self::looksUnset($db['dbname'] ?? null) ||
            self::looksUnset($db['user'] ?? null) ||
            (is_string($pass) && preg_match('/^SUA_/i', trim($pass)) === 1)
        ) {
            throw new RuntimeException('Configure as variaveis GROM_OCR_DB_HOST, GROM_OCR_DB_NAME, GROM_OCR_DB_USER e GROM_OCR_DB_PASS antes de usar o sistema.');
        }

        $port = $db['port'] ?? '3306';
        $charset = $db['charset'] ?? 'utf8mb4';
        $dsn = sprintf(
            'mysql:host=%s;port=%s;dbname=%s;charset=%s',
            $db['host'],
            $port,
            $db['dbname'],
            $charset
        );

        return new PDO($dsn, $db['user'], $db['pass'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
    }

    public static function create(array $db) {
        $driver = strtolower(trim((string) (getenv('GROM_OCR_DB_DRIVER') ?: 'mysql')));
        $fallbackSqlite = self::envFlagEnabled('GROM_OCR_DB_FALLBACK_SQLITE', true);

        if ($driver === 'sqlite') {
            return self::createSqliteConnection();
        }

        try {
            return self::createMysqlConnection($db);
        } catch (Throwable $exception) {
            if (!$fallbackSqlite) {
                throw $exception;
            }

            return self::createSqliteConnection();
        }
    }
}
