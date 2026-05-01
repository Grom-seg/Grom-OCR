<?php
$host = getenv('GROM_OCR_DB_HOST');
$port = getenv('GROM_OCR_DB_PORT');
$dbname = getenv('GROM_OCR_DB_NAME');
$user = getenv('GROM_OCR_DB_USER');
$pass = getenv('GROM_OCR_DB_PASS');
$charset = getenv('GROM_OCR_DB_CHARSET');

return [
    'host' => $host !== false ? $host : 'SEU_HOST_REMOTO',
    'port' => $port !== false ? $port : '3306',
    'dbname' => $dbname !== false ? $dbname : 'grom_ocr',
    'user' => $user !== false ? $user : 'SEU_USUARIO',
    'pass' => $pass !== false ? $pass : '',
    'charset' => $charset !== false ? $charset : 'utf8mb4',
];
