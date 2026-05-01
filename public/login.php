<?php
require_once __DIR__ . '/../app/controllers/AuthController.php';

session_start();

if (isset($_SESSION['user_id'])) {
    header('Location: /');
    exit;
}

(new AuthController())->login();
