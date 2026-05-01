<?php

require_once __DIR__ . '/../services/UseZapayWebhookStore.php';

class DashboardController
{
    private function envBool(string $name, bool $default = false): bool
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

    private function envString(string $name, string $default = ''): string
    {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }

        return trim((string) $value);
    }

    private function useZapayConfigured(): bool
    {
        $provider = strtolower($this->envString('GROM_OCR_VEHICLE_LOOKUP_PROVIDER', ''));
        return $this->envBool('GROM_OCR_USEZAPAY_ENABLE', false) || $provider === 'usezapay';
    }

    private function normalizeStatusMeta(string $status): array
    {
        $normalized = strtolower(trim($status));

        switch ($normalized) {
            case 'pending_async':
            case 'pendente_webhook':
            case 'aguardando_webhook':
                return [
                    'label' => 'Pendente',
                    'class' => 'status-chip--pending',
                ];
            case 'resultado_cache':
            case 'cache_hit':
            case 'ok':
            case 'vehicle_debt_found':
            case 'concluido':
                return [
                    'label' => 'Concluido',
                    'class' => 'status-chip--ok',
                ];
            case 'sem_retorno':
            case 'nao_disponivel':
            case 'not_found':
            case 'vehicle_not_found':
            case 'vehicle_debt_not_found':
            case 'sem_historico':
                return [
                    'label' => 'Sem retorno',
                    'class' => 'status-chip--warning',
                ];
            case 'erro':
            case 'error':
            case 'vehicle_debt_search_error':
                return [
                    'label' => 'Erro',
                    'class' => 'status-chip--error',
                ];
            case 'nao_configurado':
                return [
                    'label' => 'Nao configurado',
                    'class' => 'status-chip--neutral',
                ];
            default:
                return [
                    'label' => $normalized !== '' ? str_replace('_', ' ', $normalized) : 'Indefinido',
                    'class' => 'status-chip--neutral',
                ];
        }
    }

    private function buildZapayDashboardPanel(): array
    {
        $configured = $this->useZapayConfigured();
        $summary = [
            'visible' => true,
            'configured' => $configured,
            'status' => $configured ? 'sem_historico' : 'nao_configurado',
            'chip_label' => $configured ? 'Aguardando consultas' : 'Nao configurado',
            'chip_class' => $configured ? 'status-chip--pending' : 'status-chip--neutral',
            'subtitle' => $configured
                ? 'Monitoramento assincrono pronto para consolidar a ultima validacao veicular.'
                : 'Integracao desativada. O painel ainda exibe o cache local mais recente, quando existir.',
            'plate' => '-',
            'request_id' => '-',
            'event' => '-',
            'detail' => $configured
                ? 'Sem eventos registrados ainda.'
                : 'Ative o conector para acompanhar os status no painel principal.',
            'summary' => $configured
                ? 'Integração pronta para receber webhook.'
                : 'Integracao desativada.',
            'updated_at_utc' => '-',
            'history_count' => 0,
            'plate_count' => 0,
        ];

        if (!class_exists('UseZapayWebhookStore')) {
            return $summary;
        }

        $recent = UseZapayWebhookStore::summarizeRecentActivity();
        if (!is_array($recent) || empty($recent)) {
            return $summary;
        }

        $latest = is_array($recent['latest'] ?? null) ? $recent['latest'] : [];
        $status = strtolower(trim((string) ($recent['latest_status'] ?? ($latest['status'] ?? $latest['event'] ?? 'sem_historico'))));
        $meta = $this->normalizeStatusMeta($status);
        $summaryText = trim((string) ($latest['detail'] ?? ''));
        if ($summaryText === '') {
            $summaryText = trim((string) ($recent['latest_event'] ?? ''));
        }
        if ($summaryText === '') {
            $summaryText = $configured ? 'Sem eventos registrados ainda.' : 'Integracao desativada.';
        }

        $plate = trim((string) ($recent['latest_plate'] ?? ($latest['plate'] ?? '')));
        $requestId = trim((string) ($recent['latest_request_id'] ?? ($latest['request_id'] ?? '')));
        $updatedAt = trim((string) ($recent['updated_at_utc'] ?? ($latest['received_at_utc'] ?? '')));
        $detail = trim((string) ($latest['detail'] ?? ''));
        if ($detail === '') {
            $detail = $summaryText;
        }

        $summary['status'] = $status !== '' ? $status : $summary['status'];
        $summary['chip_label'] = $meta['label'];
        $summary['chip_class'] = $meta['class'];
        $summary['plate'] = $plate !== '' ? $plate : '-';
        $summary['request_id'] = $requestId !== '' ? $requestId : '-';
        $summary['event'] = trim((string) ($recent['latest_event'] ?? ($latest['event'] ?? '')));
        $summary['detail'] = $detail !== '' ? $detail : $summary['detail'];
        $summary['summary'] = $summaryText;
        $summary['updated_at_utc'] = $updatedAt !== '' ? $updatedAt : '-';
        $summary['history_count'] = (int) ($recent['history_count'] ?? 0);
        $summary['plate_count'] = (int) ($recent['plate_count'] ?? 0);
        $summary['visible'] = true;

        if ($summary['event'] === '' && $summary['history_count'] === 0) {
            $summary['chip_label'] = $configured ? 'Aguardando consultas' : 'Nao configurado';
            $summary['chip_class'] = $configured ? 'status-chip--pending' : 'status-chip--neutral';
        }

        return $summary;
    }

    public function index()
    {
        $zapayDashboard = $this->buildZapayDashboardPanel();
        require __DIR__ . '/../views/dashboard.php';
    }
}
