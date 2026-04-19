<?php
// Minimal .env loader + PDO connection for the Postgres warehouse.
declare(strict_types=1);

function load_env(string $path): array {
    $env = [];
    if (!is_readable($path)) {
        return $env;
    }
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        [$k, $v] = array_pad(explode('=', $line, 2), 2, '');
        $env[trim($k)] = trim($v);
    }
    return $env;
}

function pdo_from_env(): PDO {
    $env = load_env(__DIR__ . '/../.env');
    $host = $env['PG_HOST'] ?? 'localhost';
    $port = $env['PG_PORT'] ?? '5432';
    $db   = $env['PG_DATABASE'] ?? 'dw';
    $user = $env['PG_USER'] ?? 'postgres';
    $pass = $env['PG_PASSWORD'] ?? '';
    $dsn  = "pgsql:host=$host;port=$port;dbname=$db";
    return new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
}

function h(?string $s): string {
    return htmlspecialchars((string) $s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function fmt_num($n): string {
    if ($n === null) return '—';
    return number_format((float) $n);
}

function fmt_bytes($n): string {
    if ($n === null) return '—';
    $n = (float) $n;
    foreach (['B', 'KB', 'MB', 'GB', 'TB'] as $unit) {
        if ($n < 1024) return number_format($n, $unit === 'B' ? 0 : 1) . ' ' . $unit;
        $n /= 1024;
    }
    return number_format($n, 1) . ' PB';
}

function fmt_duration($seconds): string {
    if ($seconds === null) return '—';
    $s = (float) $seconds;
    if ($s < 60)   return number_format($s, 1) . 's';
    if ($s < 3600) return floor($s / 60) . 'm ' . number_format($s - 60 * floor($s / 60), 0) . 's';
    return floor($s / 3600) . 'h ' . floor(($s % 3600) / 60) . 'm';
}
