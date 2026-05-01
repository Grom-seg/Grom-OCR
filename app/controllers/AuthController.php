<?php
require_once __DIR__ . '/../models/User.php';

class AuthController {
    private function authUser(): string
    {
        $value = trim((string) (getenv('GROM_OCR_ADMIN_USER') ?: 'admin'));
        return $value !== '' ? $value : 'admin';
    }

    private function authPassHash(): string
    {
        return trim((string) (getenv('GROM_OCR_ADMIN_PASS_HASH') ?: ''));
    }

    private function authPassPlain(): string
    {
        $value = getenv('GROM_OCR_ADMIN_PASS');
        if ($value !== false) {
            return (string) $value;
        }

        // Mantido por compatibilidade local; em producao, use hash via GROM_OCR_ADMIN_PASS_HASH.
        return 'admin';
    }

    private function verifyCredentials(string $user, string $pass): bool
    {
        if (!hash_equals($this->authUser(), $user)) {
            return false;
        }

        $hash = $this->authPassHash();
        if ($hash !== '') {
            return password_verify($pass, $hash);
        }

        return hash_equals($this->authPassPlain(), $pass);
    }

    private function enforceThrottle(): void
    {
        $attempts = (int) ($_SESSION['auth_failures'] ?? 0);
        if ($attempts >= 4) {
            usleep(450000);
        } elseif ($attempts >= 2) {
            usleep(200000);
        }
    }

    public function login() {
        $error = null;
        $securityWarning = null;

        if ($this->authPassHash() === '' && $this->authPassPlain() === 'admin') {
            $securityWarning = 'Credencial padrao ativa. Configure GROM_OCR_ADMIN_PASS_HASH para uso profissional.';
        }

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $this->enforceThrottle();
            $user = trim((string) ($_POST['user'] ?? ''));
            $pass = (string) ($_POST['pass'] ?? '');

            if ($this->verifyCredentials($user, $pass)) {
                session_regenerate_id(true);
                foreach (User::buildSessionIdentity($user) as $key => $value) {
                    $_SESSION[$key] = $value;
                }
                $_SESSION['auth_failures'] = 0;
                header('Location: /');
                exit;
            }

            $_SESSION['auth_failures'] = (int) ($_SESSION['auth_failures'] ?? 0) + 1;
            $error = 'Login invalido.';
        }

        require __DIR__ . '/../views/login.php';
    }
}
