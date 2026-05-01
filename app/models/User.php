<?php

class User
{
    public static function authUser(): string
    {
        $value = trim((string) (getenv('GROM_OCR_ADMIN_USER') ?: 'admin'));
        return $value !== '' ? $value : 'admin';
    }

    public static function resolveDisplayName(?string $username = null): string
    {
        $fullName = trim((string) (getenv('GROM_OCR_ADMIN_FULL_NAME') ?: ''));
        if ($fullName !== '') {
            return $fullName;
        }

        $username = trim((string) ($username ?? ''));
        if ($username !== '') {
            return 'Operador ' . self::humanizeToken($username);
        }

        return 'Operador autenticado';
    }

    public static function resolveSessionLabel(array $session): string
    {
        foreach (['display_name', 'full_name', 'user_name', 'username'] as $key) {
            $value = trim((string) ($session[$key] ?? ''));
            if ($value !== '') {
                return $value;
            }
        }

        if (isset($session['user_id'])) {
            return 'Operador #' . (int) $session['user_id'];
        }

        return 'Operador autenticado';
    }

    public static function buildSessionIdentity(string $username): array
    {
        $username = trim($username);
        $displayName = self::resolveDisplayName($username);

        return [
            'user_id' => 1,
            'user_name' => $username,
            'username' => $username,
            'full_name' => $displayName,
            'display_name' => $displayName,
            'operator_label' => $displayName,
            'responsavel' => $displayName,
        ];
    }

    private static function humanizeToken(string $value): string
    {
        $value = trim($value);
        if ($value === '') {
            return '';
        }

        $value = preg_replace('/[_.-]+/', ' ', $value) ?? $value;
        $value = preg_replace('/\s+/', ' ', $value) ?? $value;

        if (function_exists('mb_convert_case')) {
            return trim((string) mb_convert_case($value, MB_CASE_TITLE, 'UTF-8'));
        }

        return trim((string) ucwords(strtolower($value)));
    }
}
