<?php
require_once __DIR__ . '/../models/Case.php';

class CaseController {
    private $pdo;
    private $caseModel;

    public function __construct($pdo = null) {
        $this->pdo = $pdo;
        $this->caseModel = new CaseModel($pdo);
    }

    public function saveAnalysis($user_id, $filename, $ocr, $pdf, $origem, $color_info, $adulteracao) {
        $datahora = date('Y-m-d H:i:s');

        // Salva analise local e retorna id persistido.
        $savedId = $this->caseModel->save($user_id, $filename, $ocr, $pdf, $datahora, $origem, $color_info, $adulteracao);

        return $savedId;
    }
}
