<?php
/**
 * Consulta dados veiculares em provedores externos reais.
 * Por padrao NAO retorna dados simulados/ficticios.
 */
require_once __DIR__ . '/UseZapayWebhookStore.php';

class ExternalVehicleLookup {
    private const FIPE_DOC_URL = 'https://deividfortuna.github.io/fipe/v2/';
    private const FIPE_SOURCE_LABEL = 'FIPE API aberta (fipe.parallelum.com.br, licenca MIT)';
    private const DEFAULT_SENATRAN_SOURCE_LABEL = 'Senatran/SERPRO';
    private const DEFAULT_PRODESP_SOURCE_LABEL = 'Prodesp (Detran-SP)';

    private static function sanitizePlate(string $plate): string
    {
        return strtoupper(preg_replace('/[^A-Z0-9]/', '', $plate));
    }

    private static function envInt(string $name, int $default): int
    {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }

        $parsed = (int) trim((string) $value);
        if ($parsed <= 0) {
            return $default;
        }
        return $parsed;
    }

    private static function envString(string $name, string $default = ''): string
    {
        $value = getenv($name);
        if ($value === false) {
            return $default;
        }
        return trim((string) $value);
    }

    private static function envBool(string $name, bool $default): bool
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

    private static function useZapayConfigured(): bool
    {
        $provider = strtolower(self::envString('GROM_OCR_VEHICLE_LOOKUP_PROVIDER', ''));
        if ($provider === 'usezapay') {
            return true;
        }

        if (self::envBool('GROM_OCR_USEZAPAY_ENABLE', false)) {
            return true;
        }

        $baseUrl = strtolower(self::envString('GROM_OCR_USEZAPAY_BASE_URL', ''));
        return $baseUrl !== '' && strpos($baseUrl, 'usezapay.com.br') !== false;
    }

    private static function useZapayBaseUrl(): string
    {
        $base = self::envString('GROM_OCR_USEZAPAY_BASE_URL', 'https://api.b2b.usezapay.com.br/v2/vehicle/debts/');
        return rtrim(trim($base), '/');
    }

    private static function useZapayBasicAuthHeaders(): array
    {
        $headers = ['Accept: application/json', 'Content-Type: application/json'];

        $authB64 = self::envString('GROM_OCR_USEZAPAY_BASIC_AUTH_B64', '');
        if ($authB64 !== '') {
            $headers[] = 'Authorization: Basic ' . $authB64;
            return $headers;
        }

        $username = self::envString('GROM_OCR_USEZAPAY_USERNAME', '');
        $password = self::envString('GROM_OCR_USEZAPAY_PASSWORD', '');
        if ($username !== '' || $password !== '') {
            $headers[] = 'Authorization: Basic ' . base64_encode($username . ':' . $password);
            return $headers;
        }

        $token = self::envString('GROM_OCR_USEZAPAY_TOKEN', '');
        if ($token !== '') {
            $headers[] = 'Authorization: ' . $token;
        }

        return $headers;
    }

    private static function parseExtraHeaders(string $raw): array
    {
        if ($raw === '') {
            return [];
        }

        $headers = [];
        $chunks = preg_split('/[\r\n;]+/', $raw);
        if (!is_array($chunks)) {
            return [];
        }

        foreach ($chunks as $chunk) {
            $line = trim((string) $chunk);
            if ($line === '' || strpos($line, ':') === false) {
                continue;
            }
            [$name, $value] = explode(':', $line, 2);
            $name = trim($name);
            $value = trim($value);
            if ($name === '' || $value === '') {
                continue;
            }
            $headers[] = $name . ': ' . $value;
        }

        return $headers;
    }

    private static function envTokenHeaders(string $token, string $tokenHeader, string $tokenPrefix, array $baseHeaders = []): array
    {
        $headers = $baseHeaders;
        if ($token !== '' && $tokenHeader !== '') {
            $tokenValue = $tokenPrefix !== '' ? ($tokenPrefix . ' ' . $token) : $token;
            $headers[] = $tokenHeader . ': ' . $tokenValue;
        }
        return $headers;
    }

    private static function providerAliasMatches(array $aliases): bool
    {
        $provider = strtolower(self::envString('GROM_OCR_VEHICLE_LOOKUP_PROVIDER', ''));
        if ($provider === '') {
            return false;
        }
        return in_array($provider, $aliases, true);
    }

    private static function senatranConfigured(): bool
    {
        if (self::providerAliasMatches(['senatran', 'serpro', 'senatran_serpro', 'wsdenatran', 'consulta_senatran'])) {
            return self::envString('GROM_OCR_SENATRAN_URL', '') !== '';
        }
        return self::envBool('GROM_OCR_SENATRAN_ENABLE', false) || self::envString('GROM_OCR_SENATRAN_URL', '') !== '';
    }

    private static function prodespConfigured(): bool
    {
        if (self::providerAliasMatches(['prodesp', 'prodesp_detran_sp', 'detran_sp', 'consulta_veiculos_sp'])) {
            return self::envString('GROM_OCR_PRODESP_URL', '') !== '';
        }
        return self::envBool('GROM_OCR_PRODESP_ENABLE', false) || self::envString('GROM_OCR_PRODESP_URL', '') !== '';
    }

    private static function buildConfiguredProviderRequest(string $plate, string $prefix, array $defaults): array
    {
        $url = self::envString($prefix . '_URL', (string) ($defaults['url'] ?? ''));
        if ($url === '') {
            return [];
        }

        $method = strtoupper(self::envString($prefix . '_METHOD', (string) ($defaults['method'] ?? 'GET')));
        if (!in_array($method, ['GET', 'POST'], true)) {
            $method = 'GET';
        }

        $plateParam = self::envString($prefix . '_PLATE_PARAM', (string) ($defaults['plate_param'] ?? 'placa'));
        $endpoint = $url;
        $payload = [];
        if (strpos($endpoint, '{plate}') !== false) {
            $endpoint = str_replace('{plate}', rawurlencode($plate), $endpoint);
        } elseif ($method === 'GET') {
            $joiner = strpos($endpoint, '?') !== false ? '&' : '?';
            $endpoint .= $joiner . rawurlencode($plateParam) . '=' . rawurlencode($plate);
        } else {
            $payload = [$plateParam => $plate];
        }

        $payloadTemplate = self::envString($prefix . '_PAYLOAD_TEMPLATE', '');
        if ($method === 'POST' && $payloadTemplate !== '') {
            $decoded = json_decode(str_replace('{plate}', $plate, $payloadTemplate), true);
            if (is_array($decoded) && !empty($decoded)) {
                $payload = $decoded;
            }
        }

        $token = self::envString($prefix . '_TOKEN', '');
        $tokenHeader = self::envString($prefix . '_TOKEN_HEADER', (string) ($defaults['token_header'] ?? 'Authorization'));
        $tokenPrefix = self::envString($prefix . '_TOKEN_PREFIX', (string) ($defaults['token_prefix'] ?? 'Bearer'));
        $extraHeaders = self::parseExtraHeaders(self::envString($prefix . '_EXTRA_HEADERS', ''));
        $headers = self::envTokenHeaders($token, $tokenHeader, $tokenPrefix, ['Accept: application/json']);
        foreach ($extraHeaders as $headerLine) {
            $headers[] = $headerLine;
        }

        return [
            'endpoint' => $endpoint,
            'method' => $method,
            'payload' => $payload,
            'headers' => $headers,
            'source_kind' => self::envString($prefix . '_SOURCE_KIND', (string) ($defaults['source_kind'] ?? 'external_provider')),
            'source_label' => self::envString($prefix . '_SOURCE_LABEL', (string) ($defaults['source_label'] ?? 'provedor_externo')),
            'response_path' => self::envString($prefix . '_RESPONSE_PATH', ''),
            'priority' => max(1, self::envInt($prefix . '_PRIORITY', (int) ($defaults['priority'] ?? 50))),
        ];
    }

    private static function resolveGenericSourceRequests(string $plate): array
    {
        $requests = [];
        $token = self::envString('GROM_OCR_VEHICLE_LOOKUP_TOKEN', '');
        $tokenHeader = self::envString('GROM_OCR_VEHICLE_LOOKUP_TOKEN_HEADER', 'Authorization');
        $tokenPrefix = self::envString('GROM_OCR_VEHICLE_LOOKUP_TOKEN_PREFIX', 'Bearer');
        $extraHeaders = self::parseExtraHeaders(self::envString('GROM_OCR_VEHICLE_LOOKUP_EXTRA_HEADERS', ''));
        $headers = self::envTokenHeaders($token, $tokenHeader, $tokenPrefix, ['Accept: application/json']);
        foreach ($extraHeaders as $headerLine) {
            $headers[] = $headerLine;
        }

        foreach (self::resolveEndpointList($plate) as $endpoint) {
            $requests[] = [
                'endpoint' => $endpoint,
                'method' => 'GET',
                'payload' => [],
                'headers' => $headers,
                'source_kind' => self::classifySourceKind($endpoint),
                'source_label' => self::endpointSourceLabel($endpoint),
                'response_path' => '',
                'priority' => 80,
            ];
        }

        return $requests;
    }

    private static function buildConfiguredSourceRequests(string $plate): array
    {
        $requests = [];

        if (self::senatranConfigured()) {
            $request = self::buildConfiguredProviderRequest($plate, 'GROM_OCR_SENATRAN', [
                'method' => 'GET',
                'plate_param' => 'placa',
                'source_kind' => 'official_senatran',
                'source_label' => self::DEFAULT_SENATRAN_SOURCE_LABEL,
                'priority' => 10,
            ]);
            if (!empty($request)) {
                $requests[] = $request;
            }
        }

        if (self::prodespConfigured()) {
            $request = self::buildConfiguredProviderRequest($plate, 'GROM_OCR_PRODESP', [
                'method' => 'GET',
                'plate_param' => 'placa',
                'source_kind' => 'official_prodesp',
                'source_label' => self::DEFAULT_PRODESP_SOURCE_LABEL,
                'priority' => 20,
            ]);
            if (!empty($request)) {
                $requests[] = $request;
            }
        }

        foreach (self::resolveGenericSourceRequests($plate) as $request) {
            $requests[] = $request;
        }

        usort($requests, static function (array $left, array $right): int {
            $leftPriority = (int) ($left['priority'] ?? 50);
            $rightPriority = (int) ($right['priority'] ?? 50);
            if ($leftPriority !== $rightPriority) {
                return $leftPriority <=> $rightPriority;
            }
            return strcmp((string) ($left['source_label'] ?? ''), (string) ($right['source_label'] ?? ''));
        });

        $normalized = [];
        $seen = [];
        foreach ($requests as $request) {
            $signature = strtoupper((string) ($request['method'] ?? 'GET')) . ' ' . trim((string) ($request['endpoint'] ?? '')) . ' ' . trim((string) ($request['source_label'] ?? ''));
            if ($signature === '' || isset($seen[$signature])) {
                continue;
            }
            $seen[$signature] = true;
            $normalized[] = $request;
        }

        return $normalized;
    }

    private static function extractPathPayload(array $decoded, string $path): array
    {
        $path = trim($path);
        if ($path === '') {
            return [];
        }

        $current = $decoded;
        foreach (explode('.', $path) as $segment) {
            $segment = trim($segment);
            if ($segment === '' || !is_array($current) || !array_key_exists($segment, $current)) {
                return [];
            }
            $current = $current[$segment];
        }

        return is_array($current) ? $current : [];
    }

    private static function httpRequestJson(string $method, string $url, int $timeout, array $headers = [], array $payload = []): array
    {
        $method = strtoupper(trim($method));
        if ($method === 'POST') {
            return self::httpPostJson($url, $payload, $timeout, $headers);
        }
        return self::httpGetJson($url, $timeout, $headers);
    }

    private static function resolveEndpoint(string $plate): string
    {
        $base = trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_URL') ?: ''));
        if ($base === '') {
            return '';
        }

        if (strpos($base, '{plate}') !== false) {
            return str_replace('{plate}', rawurlencode($plate), $base);
        }

        $joiner = strpos($base, '?') !== false ? '&' : '?';
        return $base . $joiner . 'placa=' . rawurlencode($plate);
    }

    private static function resolveEndpointList(string $plate): array
    {
        $endpoints = [];
        $rawList = self::envString('GROM_OCR_VEHICLE_LOOKUP_URLS', '');
        if ($rawList !== '') {
            $chunks = preg_split('/[\r\n;,]+/', $rawList);
            if (is_array($chunks)) {
                foreach ($chunks as $chunk) {
                    $base = trim((string) $chunk);
                    if ($base === '') {
                        continue;
                    }
                    if (strpos($base, '{plate}') !== false) {
                        $endpoint = str_replace('{plate}', rawurlencode($plate), $base);
                    } else {
                        $joiner = strpos($base, '?') !== false ? '&' : '?';
                        $endpoint = $base . $joiner . 'placa=' . rawurlencode($plate);
                    }
                    $endpoints[] = $endpoint;
                }
            }
        }

        $single = self::resolveEndpoint($plate);
        if ($single !== '') {
            $endpoints[] = $single;
        }

        $normalized = [];
        foreach ($endpoints as $endpoint) {
            $ep = trim((string) $endpoint);
            if ($ep === '') {
                continue;
            }
            $normalized[] = $ep;
        }

        return array_values(array_unique($normalized));
    }

    private static function pickDataPayload(array $decoded): array
    {
        if (isset($decoded['data']) && is_array($decoded['data'])) {
            return $decoded['data'];
        }
        if (isset($decoded['result']) && is_array($decoded['result'])) {
            return $decoded['result'];
        }
        return $decoded;
    }

    private static function mapVehicleFields(array $payload): array
    {
        $source = $payload;
        if (isset($payload['vehicle']) && is_array($payload['vehicle'])) {
            $source = array_merge($payload, $payload['vehicle']);
        }
        if (isset($payload['veiculo']) && is_array($payload['veiculo'])) {
            $source = array_merge($source, $payload['veiculo']);
        }
        if (isset($payload['owner']) && is_array($payload['owner'])) {
            $source = array_merge($source, $payload['owner']);
        }
        if (isset($payload['proprietario']) && is_array($payload['proprietario'])) {
            $source = array_merge($source, $payload['proprietario']);
        }

        $mapped = [
            'placa' => (string) ($source['placa'] ?? $source['license_plate'] ?? $source['plate'] ?? $source['plate_number'] ?? ''),
            'fabricante' => (string) ($source['fabricante'] ?? $source['marca'] ?? $source['make'] ?? $source['brand'] ?? $source['manufacturer'] ?? ''),
            'marca_modelo' => (string) ($source['marca_modelo'] ?? $source['marcaModelo'] ?? $source['brandModel'] ?? $source['brand_model'] ?? $source['brand_model_name'] ?? ''),
            'modelo' => (string) ($source['modelo'] ?? $source['model'] ?? ''),
            'ano' => (string) ($source['ano'] ?? $source['ano_modelo'] ?? $source['anoModelo'] ?? $source['year'] ?? $source['modelYear'] ?? $source['ano_fabricacao'] ?? $source['anoFabricacao'] ?? $source['fabrication_year'] ?? $source['model_year'] ?? ''),
            'cor' => (string) ($source['cor'] ?? $source['corPredominante'] ?? $source['color'] ?? ''),
            'categoria' => (string) ($source['categoria'] ?? $source['category'] ?? ''),
            'uf' => (string) ($source['uf'] ?? $source['estado'] ?? $source['estadoSigla'] ?? $source['state'] ?? ''),
            'cidade' => (string) ($source['cidade'] ?? $source['city'] ?? $source['municipio'] ?? $source['town'] ?? ''),
            'municipio' => (string) ($source['municipio'] ?? $source['county'] ?? ''),
            'chassi' => (string) ($source['chassi'] ?? $source['vin'] ?? $source['chassis'] ?? $source['numero_chassi'] ?? ''),
            'renavam' => (string) ($source['renavam'] ?? $source['codigo_renavam'] ?? $source['renavam_code'] ?? ''),
            'proprietario' => (string) ($source['proprietario'] ?? $source['owner'] ?? $source['nome_proprietario'] ?? $source['owner_name'] ?? ''),
            'cpf_cnpj' => (string) ($source['cpf_cnpj'] ?? $source['documento'] ?? $source['document'] ?? $source['owner_document'] ?? ''),
            'endereco' => (string) ($source['endereco'] ?? $source['address'] ?? ''),
            'estampador' => (string) ($source['estampador'] ?? $source['plate_maker'] ?? $source['emplacador'] ?? ''),
            'codigo_seguranca_crv' => (string) ($source['codigo_seguranca_crv'] ?? $source['crv_security_code'] ?? $source['codigo_crv'] ?? ''),
            'serial_qrcode' => (string) ($source['serial_qrcode'] ?? $source['qr_code_serial'] ?? $source['qrcode_serial'] ?? $source['qr_serial'] ?? ''),
            'restricoes' => (string) ($source['restricoes'] ?? $source['restrictions'] ?? $source['debts_summary'] ?? ''),
            'fonte' => (string) ($source['fonte'] ?? $source['source'] ?? 'provedor_externo'),
        ];

        return array_filter($mapped, static function ($value) {
            return $value !== '';
        });
    }

    private static function pickLikelyVehiclePayload(array $decoded): array
    {
        $payload = self::pickDataPayload($decoded);
        if (!is_array($payload) || empty($payload)) {
            return [];
        }

        $isAssoc = array_keys($payload) !== range(0, count($payload) - 1);
        if ($isAssoc) {
            return $payload;
        }

        foreach ($payload as $item) {
            if (is_array($item) && !empty($item)) {
                return $item;
            }
        }
        return [];
    }

    private static function endpointSourceLabel(string $endpoint): string
    {
        $host = parse_url($endpoint, PHP_URL_HOST);
        if (!is_string($host) || trim($host) === '') {
            return 'provedor_externo';
        }
        return 'fonte_aberta:' . strtolower(trim($host));
    }

    private static function classifySourceKind(string $endpoint): string
    {
        $forced = strtolower(self::envString('GROM_OCR_VEHICLE_LOOKUP_SOURCE_KIND', ''));
        if ($forced !== '') {
            return $forced;
        }

        $host = strtolower((string) parse_url($endpoint, PHP_URL_HOST));
        if ($host === '') {
            return 'external_provider';
        }
        if (strpos($host, 'gov.br') !== false) {
            return 'official_gov_br';
        }
        if (strpos($host, 'serpro') !== false) {
            return 'official_serpro';
        }
        if (strpos($host, 'senatran') !== false || strpos($host, 'denatran') !== false) {
            return 'official_senatran';
        }
        if (strpos($host, 'prodesp') !== false || strpos($host, 'detran.sp') !== false || strpos($host, 'sp.gov.br') !== false) {
            return 'official_prodesp';
        }
        if (strpos($host, 'sinesp') !== false) {
            return 'official_sinesp';
        }
        if (strpos($host, 'usezapay') !== false) {
            return 'official_authorized';
        }
        if (strpos($host, 'fipe.parallelum.com.br') !== false || strpos($host, 'deividfortuna.github.io') !== false) {
            return 'open_data_reference';
        }

        return 'external_provider';
    }

    private static function maskSensitiveValue(string $value, int $visibleTail = 4): string
    {
        $clean = trim($value);
        if ($clean === '') {
            return '';
        }

        $compact = preg_replace('/\s+/', '', $clean);
        if (!is_string($compact) || $compact === '') {
            return $clean;
        }

        $length = strlen($compact);
        if ($visibleTail <= 0) {
            return str_repeat('*', max(1, $length));
        }
        if ($length <= $visibleTail) {
            return str_repeat('*', max(1, $length));
        }

        return str_repeat('*', max(1, $length - $visibleTail)) . substr($compact, -$visibleTail);
    }

    private static function publicVehicleFields(): array
    {
        return [
            'placa',
            'fabricante',
            'marca_modelo',
            'modelo',
            'ano',
            'cor',
            'categoria',
            'uf',
            'cidade',
            'municipio',
            'restricoes',
            'fipe_preco_medio',
            'fipe_codigo',
            'fipe_ano_modelo',
            'fipe_mes_referencia',
            'fipe_combustivel',
        ];
    }

    private static function sensitiveVehicleFields(): array
    {
        return [
            'chassi',
            'renavam',
            'proprietario',
            'cpf_cnpj',
            'endereco',
            'estampador',
            'codigo_seguranca_crv',
            'serial_qrcode',
        ];
    }

    private static function consultationVehicleFields(): array
    {
        return [
            'placa',
            'fabricante',
            'marca_modelo',
            'modelo',
            'ano',
            'cor',
            'categoria',
            'uf',
            'cidade',
            'municipio',
            'restricoes',
            'estampador',
            'fipe_preco_medio',
            'fipe_codigo',
            'fipe_ano_modelo',
        ];
    }

    private static function sourceTrustWeight(string $sourceKind): float
    {
        switch ($sourceKind) {
            case 'official_gov_br':
            case 'official_serpro':
            case 'official_senatran':
                return 1.0;
            case 'official_prodesp':
                return 0.97;
            case 'official_sinesp':
                return 0.95;
            case 'official_authorized':
                return 0.92;
            case 'open_data_reference':
                return 0.76;
            default:
                return 0.6;
        }
    }

    private static function scoreVehicleCandidate(array $vehicle, array $validation, string $sourceKind, string $normalizedPlate): array
    {
        $score = 0.0;
        $reasons = [];

        $sourceBonus = round(self::sourceTrustWeight($sourceKind) * 28.0, 1);
        $score += $sourceBonus;
        $reasons[] = 'procedencia=' . $sourceKind . ' (' . $sourceBonus . ')';

        $publicCount = 0;
        foreach (self::publicVehicleFields() as $field) {
            if (trim((string) ($vehicle[$field] ?? '')) !== '') {
                $publicCount++;
            }
        }
        if ($publicCount > 0) {
            $publicBonus = min(36.0, $publicCount * 4.5);
            $score += $publicBonus;
            $reasons[] = 'campos_publicos=' . $publicCount . ' (' . $publicBonus . ')';
        }

        $sensitiveCount = 0;
        foreach (self::sensitiveVehicleFields() as $field) {
            if (trim((string) ($vehicle[$field] ?? '')) !== '') {
                $sensitiveCount++;
            }
        }
        if ($sensitiveCount > 0) {
            $sensitiveBonus = min(12.0, $sensitiveCount * 2.0);
            $score += $sensitiveBonus;
            $reasons[] = 'campos_restritos=' . $sensitiveCount . ' (' . $sensitiveBonus . ')';
        }

        if (trim((string) ($vehicle['fabricante'] ?? '')) !== '' && trim((string) ($vehicle['modelo'] ?? '')) !== '') {
            $score += 7.0;
            $reasons[] = 'fabricante_modelo_presentes (+7.0)';
        }
        if (trim((string) ($vehicle['ano'] ?? '')) !== '') {
            $score += 4.0;
            $reasons[] = 'ano_presente (+4.0)';
        }
        if (trim((string) ($vehicle['cor'] ?? '')) !== '') {
            $score += 2.0;
            $reasons[] = 'cor_presente (+2.0)';
        }
        if (trim((string) ($vehicle['uf'] ?? '')) !== '' || trim((string) ($vehicle['cidade'] ?? '')) !== '' || trim((string) ($vehicle['municipio'] ?? '')) !== '') {
            $score += 3.0;
            $reasons[] = 'localizacao_presente (+3.0)';
        }
        if (trim((string) ($vehicle['fipe_preco_medio'] ?? '')) !== '' || trim((string) ($vehicle['fipe_codigo'] ?? '')) !== '') {
            $score += 4.0;
            $reasons[] = 'complemento_fipe (+4.0)';
        }

        if (!empty($validation['is_official'])) {
            $score += 18.0;
            $reasons[] = 'validacao_oficial (+18.0)';
        } elseif ((string) ($validation['status'] ?? '') === 'sem_validacao_oficial') {
            $reasons[] = 'sem_validacao_oficial';
        }

        if ((int) ($validation['public_fields_count'] ?? 0) >= 5) {
            $score += 3.0;
            $reasons[] = 'validacao_campos_publicos_suficientes (+3.0)';
        }
        if ((int) ($validation['sensitive_fields_count'] ?? 0) > 0 && !empty($validation['is_official'])) {
            $score += 2.0;
            $reasons[] = 'validacao_campos_restritos (+2.0)';
        }

        $plateValue = self::sanitizePlate((string) ($vehicle['placa'] ?? ''));
        if ($normalizedPlate !== '' && $plateValue !== '') {
            if ($plateValue === $normalizedPlate) {
                $score += 8.0;
                $reasons[] = 'placa_compativel (+8.0)';
            } else {
                $score -= 25.0;
                $reasons[] = 'placa_inconsistente (-25.0)';
            }
        } elseif ($normalizedPlate !== '' && $plateValue === '') {
            $score -= 8.0;
            $reasons[] = 'placa_ausente (-8.0)';
        }

        $score = max(0.0, min(100.0, $score));

        return [
            'score' => round($score, 1),
            'public_fields_count' => $publicCount,
            'sensitive_fields_count' => $sensitiveCount,
            'reasons' => $reasons,
        ];
    }

    private static function summarizeLookupCandidates(array $candidates, string $normalizedPlate): array
    {
        if (empty($candidates)) {
            return [
                'status' => 'indefinido',
                'candidates_count' => 0,
                'official_candidates' => 0,
                'best_source_label' => '',
                'best_source_kind' => '',
                'best_source_endpoint' => '',
                'best_score' => 0.0,
                'confidence' => 0.0,
                'consensus_ratio' => 0.0,
                'consensus_fields' => [],
                'divergent_fields' => [],
                'divergent_details' => [],
                'source_labels' => [],
                'official_labels' => [],
                'summary_text' => 'Nenhuma fonte retornou dados utilizaveis.',
                'notes' => ['nenhuma_fonte_utilizavel'],
                'resolved_vehicle' => [],
                'best_vehicle' => [],
            ];
        }

        usort($candidates, static function (array $left, array $right): int {
            $leftScore = (float) ($left['lookup_score'] ?? 0.0);
            $rightScore = (float) ($right['lookup_score'] ?? 0.0);
            if ($leftScore < $rightScore) {
                return 1;
            }
            if ($leftScore > $rightScore) {
                return -1;
            }

            $leftOfficial = !empty(($left['official_validation'] ?? [])['is_official']);
            $rightOfficial = !empty(($right['official_validation'] ?? [])['is_official']);
            if ($leftOfficial !== $rightOfficial) {
                return $rightOfficial <=> $leftOfficial;
            }

            $leftPublic = (int) ($left['public_fields_count'] ?? 0);
            $rightPublic = (int) ($right['public_fields_count'] ?? 0);
            if ($leftPublic !== $rightPublic) {
                return $rightPublic <=> $leftPublic;
            }

            $leftSensitive = (int) ($left['sensitive_fields_count'] ?? 0);
            $rightSensitive = (int) ($right['sensitive_fields_count'] ?? 0);
            if ($leftSensitive !== $rightSensitive) {
                return $rightSensitive <=> $leftSensitive;
            }

            return strcmp((string) ($left['source_label'] ?? ''), (string) ($right['source_label'] ?? ''));
        });

        $best = $candidates[0];
        $votes = [];
        $sourceLabels = [];
        $officialLabels = [];
        $resolvedFields = [];
        $consensusFields = [];
        $divergentDetails = [];
        $divergentFields = [];
        $fieldsConsidered = 0;
        $fieldsWithAgreement = 0;

        foreach ($candidates as $candidate) {
            $sourceLabel = trim((string) ($candidate['source_label'] ?? ''));
            if ($sourceLabel !== '') {
                $sourceLabels[] = $sourceLabel;
            }

            $validation = is_array($candidate['official_validation'] ?? null) ? $candidate['official_validation'] : [];
            if (!empty($validation['is_official'])) {
                $officialLabels[] = $sourceLabel !== '' ? $sourceLabel : (string) ($candidate['source_kind'] ?? 'official');
            }

            $vehicle = is_array($candidate['vehicle'] ?? null) ? $candidate['vehicle'] : [];
            $voteWeight = max(1.0, ((float) ($candidate['lookup_score'] ?? 0.0)) / 20.0);

            foreach (self::consultationVehicleFields() as $field) {
                $value = trim((string) ($vehicle[$field] ?? ''));
                if ($value === '') {
                    continue;
                }

                $normalized = self::normalizeText($value);
                if ($normalized === '') {
                    continue;
                }

                if (!isset($votes[$field])) {
                    $votes[$field] = [];
                }

                if (!isset($votes[$field][$normalized])) {
                    $votes[$field][$normalized] = [
                        'value' => $value,
                        'count' => 0,
                        'weight' => 0.0,
                        'best_score' => 0.0,
                    ];
                }

                $votes[$field][$normalized]['count']++;
                $votes[$field][$normalized]['weight'] += $voteWeight;
                $candidateScore = (float) ($candidate['lookup_score'] ?? 0.0);
                if ($candidateScore >= (float) ($votes[$field][$normalized]['best_score'] ?? 0.0)) {
                    $votes[$field][$normalized]['value'] = $value;
                    $votes[$field][$normalized]['best_score'] = $candidateScore;
                }
            }
        }

        foreach ($votes as $field => $voteSet) {
            if (empty($voteSet)) {
                continue;
            }

            $fieldsConsidered++;
            uasort($voteSet, static function (array $left, array $right): int {
                $weightLeft = (float) ($left['weight'] ?? 0.0);
                $weightRight = (float) ($right['weight'] ?? 0.0);
                if ($weightLeft < $weightRight) {
                    return 1;
                }
                if ($weightLeft > $weightRight) {
                    return -1;
                }

                $countLeft = (int) ($left['count'] ?? 0);
                $countRight = (int) ($right['count'] ?? 0);
                if ($countLeft < $countRight) {
                    return 1;
                }
                if ($countLeft > $countRight) {
                    return -1;
                }

                $scoreLeft = (float) ($left['best_score'] ?? 0.0);
                $scoreRight = (float) ($right['best_score'] ?? 0.0);
                if ($scoreLeft < $scoreRight) {
                    return 1;
                }
                if ($scoreLeft > $scoreRight) {
                    return -1;
                }

                return 0;
            });

            $winner = array_key_first($voteSet);
            if ($winner === null) {
                continue;
            }

            $resolvedFields[$field] = (string) ($voteSet[$winner]['value'] ?? '');
            if (count($voteSet) > 1) {
                $detailPieces = [];
                foreach ($voteSet as $voteData) {
                    $detailPieces[] = trim((string) ($voteData['value'] ?? '')) . 'x' . (int) ($voteData['count'] ?? 0);
                }
                $divergentFields[] = $field;
                $divergentDetails[] = $field . ': ' . implode(' | ', array_slice($detailPieces, 0, 4));
            }

            if (count($voteSet) === 1 || (int) ($voteSet[$winner]['count'] ?? 0) > 1) {
                $fieldsWithAgreement++;
                $consensusFields[] = $field;
            } else {
                $winnerWeight = (float) ($voteSet[$winner]['weight'] ?? 0.0);
                $totalWeight = 0.0;
                foreach ($voteSet as $voteData) {
                    $totalWeight += (float) ($voteData['weight'] ?? 0.0);
                }
                if ($totalWeight > 0.0 && ($winnerWeight / $totalWeight) >= 0.66) {
                    $fieldsWithAgreement++;
                }
            }
        }

        $consensusRatio = $fieldsConsidered > 0 ? round(($fieldsWithAgreement / $fieldsConsidered) * 100.0, 1) : 0.0;
        $bestVehicle = is_array($best['vehicle'] ?? null) ? $best['vehicle'] : [];
        $resolvedVehicle = $bestVehicle;
        foreach ($resolvedFields as $field => $value) {
            if (!isset($resolvedVehicle[$field]) || trim((string) $resolvedVehicle[$field]) === '') {
                $resolvedVehicle[$field] = $value;
            }
        }
        if (trim((string) ($resolvedVehicle['placa'] ?? '')) === '' && $normalizedPlate !== '') {
            $resolvedVehicle['placa'] = $normalizedPlate;
        }

        $sourceLabels = array_values(array_unique(array_filter($sourceLabels)));
        $officialLabels = array_values(array_unique(array_filter($officialLabels)));
        $bestScore = (float) ($best['lookup_score'] ?? 0.0);
        $confidence = round(min(100.0, ($bestScore * 0.7) + ($consensusRatio * 0.3)), 1);

        $summaryText = sprintf(
            '%d fontes consultadas; %d oficiais; melhor fonte=%s; consenso em %d/%d campos; divergencias=%d; confianca=%.1f%%',
            count($candidates),
            count($officialLabels),
            (string) ($best['source_label'] ?? 'indefinida'),
            count($consensusFields),
            $fieldsConsidered,
            count($divergentFields),
            $confidence
        );

        $notes = [];
        if (count($candidates) > 1) {
            $notes[] = 'consulta_multifonte_consolidada';
        }
        if (!empty($officialLabels)) {
            $notes[] = 'fontes_oficiais_detectadas';
        }
        if (!empty($divergentFields)) {
            $notes[] = 'divergencias_identificadas';
        }
        if ($consensusRatio < 60.0) {
            $notes[] = 'consenso_baixo';
        }

        return [
            'status' => count($candidates) > 1 ? 'multifonte' : 'unifonte',
            'candidates_count' => count($candidates),
            'official_candidates' => count($officialLabels),
            'best_source_label' => (string) ($best['source_label'] ?? ''),
            'best_source_kind' => (string) ($best['source_kind'] ?? ''),
            'best_source_endpoint' => (string) ($best['endpoint'] ?? ''),
            'best_score' => round($bestScore, 1),
            'confidence' => $confidence,
            'consensus_ratio' => $consensusRatio,
            'consensus_fields' => $consensusFields,
            'divergent_fields' => $divergentFields,
            'divergent_details' => $divergentDetails,
            'source_labels' => $sourceLabels,
            'official_labels' => $officialLabels,
            'summary_text' => $summaryText,
            'notes' => $notes,
            'resolved_vehicle' => $resolvedVehicle,
            'best_vehicle' => $bestVehicle,
        ];
    }

    private static function buildOfficialValidation(array $vehicle, string $endpoint, string $normalizedPlate, array $metadata = []): array
    {
        $sourceKind = (string) ($metadata['source_kind'] ?? self::classifySourceKind($endpoint));
        $sourceLabel = (string) ($metadata['source_label'] ?? self::endpointSourceLabel($endpoint));
        $isOfficial = in_array($sourceKind, [
            'official_gov_br',
            'official_serpro',
            'official_senatran',
            'official_prodesp',
            'official_sinesp',
            'official_authorized',
        ], true);
        $strictOfficial = self::envBool('GROM_OCR_VEHICLE_LOOKUP_STRICT_OFFICIAL', false);
        $lookupState = strtolower(trim((string) ($vehicle['consulta_status'] ?? '')));
        $pendingLookup = in_array($lookupState, ['pending_async', 'pendente_webhook', 'aguardando_webhook'], true);

        $publicFields = ['placa', 'fabricante', 'marca_modelo', 'modelo', 'ano', 'cor', 'categoria', 'uf', 'cidade', 'municipio', 'restricoes'];
        $sensitiveFields = self::sensitiveVehicleFields();

        $publicFound = [];
        foreach ($publicFields as $field) {
            if (trim((string) ($vehicle[$field] ?? '')) !== '') {
                $publicFound[] = $field;
            }
        }

        $sensitiveFound = [];
        foreach ($sensitiveFields as $field) {
            if (trim((string) ($vehicle[$field] ?? '')) !== '') {
                $sensitiveFound[] = $field;
            }
        }

        $notes = [];
        if (!$isOfficial) {
            $notes[] = 'fonte_nao_classificada_como_oficial';
        }
        if ($strictOfficial && !$isOfficial) {
            $notes[] = 'consulta_nao_promovida_a_validacao_oficial';
        }
        if ($pendingLookup) {
            $notes[] = 'consulta_assincrona_pendente';
        }
        if (in_array('chassi', $sensitiveFound, true)) {
            $notes[] = 'chassi_detectado_em_fluxo_restrito';
        }
        if (in_array('proprietario', $sensitiveFound, true) || in_array('cpf_cnpj', $sensitiveFound, true)) {
            $notes[] = 'dados_pessoais_detectados';
        }
        if (empty($publicFound)) {
            $notes[] = 'campos_publicos_incompletos';
        }

        $status = $isOfficial ? 'ok' : ($strictOfficial ? 'nao_oficial' : 'sem_validacao_oficial');
        if ($pendingLookup) {
            $status = 'pendente_webhook';
        }

        return [
            'status' => $status,
            'is_official' => $isOfficial,
            'source_kind' => $sourceKind,
            'source_label' => $sourceLabel,
            'source_url' => $endpoint,
            'lookup_plate' => $normalizedPlate,
            'public_fields' => $publicFields,
            'public_fields_found' => $publicFound,
            'public_fields_missing' => array_values(array_diff($publicFields, $publicFound)),
            'sensitive_fields' => $sensitiveFields,
            'sensitive_fields_found' => $sensitiveFound,
            'sensitive_fields_masked' => !self::envBool('GROM_OCR_VEHICLE_REVEAL_SENSITIVE_FIELDS', false),
            'sensitive_policy' => self::envBool('GROM_OCR_VEHICLE_REVEAL_SENSITIVE_FIELDS', false)
                ? 'revelado_por_configuracao'
                : 'mascarado_por_padrao',
            'public_fields_count' => count($publicFound),
            'sensitive_fields_count' => count($sensitiveFound),
            'notes' => $notes,
        ];
    }

    private static function httpGetJson(string $url, int $timeout, array $headers = []): array
    {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 4);
        curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
        curl_setopt($ch, CURLOPT_HTTPGET, true);
        if (defined('CURL_IPRESOLVE_V4')) {
            curl_setopt($ch, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
        }

        $skipTlsVerify = self::envBool('GROM_OCR_HTTP_INSECURE_SKIP_VERIFY', false);
        $caBundle = self::envString('GROM_OCR_HTTP_CA_BUNDLE', '');
        if ($skipTlsVerify) {
            curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
            curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);
        } elseif ($caBundle !== '' && is_file($caBundle)) {
            curl_setopt($ch, CURLOPT_CAINFO, $caBundle);
        }

        if (!empty($headers)) {
            curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        }

        $response = curl_exec($ch);
        $error = curl_error($ch);
        $statusCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($error !== '' || $statusCode < 200 || $statusCode >= 400 || !is_string($response)) {
            return [];
        }

        $decoded = json_decode($response, true);
        return is_array($decoded) ? $decoded : [];
    }

    private static function httpPostJson(string $url, array $payload, int $timeout, array $headers = []): array
    {
        $ch = curl_init($url);
        $body = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if (!is_string($body)) {
            return [];
        }

        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 4);
        curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
        if (defined('CURL_IPRESOLVE_V4')) {
            curl_setopt($ch, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
        }

        $skipTlsVerify = self::envBool('GROM_OCR_HTTP_INSECURE_SKIP_VERIFY', false);
        $caBundle = self::envString('GROM_OCR_HTTP_CA_BUNDLE', '');
        if ($skipTlsVerify) {
            curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
            curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);
        } elseif ($caBundle !== '' && is_file($caBundle)) {
            curl_setopt($ch, CURLOPT_CAINFO, $caBundle);
        }

        $mergedHeaders = array_merge(['Content-Type: application/json', 'Accept: application/json'], $headers);
        if (!empty($mergedHeaders)) {
            curl_setopt($ch, CURLOPT_HTTPHEADER, $mergedHeaders);
        }

        $response = curl_exec($ch);
        $error = curl_error($ch);
        $statusCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($error !== '' || $statusCode < 200 || $statusCode >= 400 || !is_string($response)) {
            return [];
        }

        $decoded = json_decode($response, true);
        return is_array($decoded) ? $decoded : [];
    }

    private static function normalizeText(string $value): string
    {
        $text = trim($value);
        if ($text === '') {
            return '';
        }

        $transliterated = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
        if (is_string($transliterated) && $transliterated !== '') {
            $text = $transliterated;
        }

        $text = strtoupper($text);
        $text = preg_replace('/[^A-Z0-9 ]+/', ' ', $text);
        $text = preg_replace('/\s+/', ' ', (string) $text);
        return trim((string) $text);
    }

    private static function scoreNameMatch(string $needle, string $candidate): float
    {
        $needleNorm = self::normalizeText($needle);
        $candidateNorm = self::normalizeText($candidate);

        if ($needleNorm === '' || $candidateNorm === '') {
            return 0.0;
        }

        if ($needleNorm === $candidateNorm) {
            return 200.0;
        }

        $score = 0.0;
        if (strpos($candidateNorm, $needleNorm) !== false) {
            $score += 80.0;
        }
        if (strpos($needleNorm, $candidateNorm) !== false) {
            $score += 40.0;
        }

        $needleParts = array_values(array_filter(explode(' ', $needleNorm), static function ($part) {
            return $part !== '';
        }));
        $candidateParts = array_values(array_filter(explode(' ', $candidateNorm), static function ($part) {
            return $part !== '';
        }));

        if (!empty($needleParts) && !empty($candidateParts)) {
            $intersect = array_intersect($needleParts, $candidateParts);
            $score += count($intersect) * 28.0;
            $score += (count($intersect) / max(1, count($needleParts))) * 30.0;
        }

        similar_text($needleNorm, $candidateNorm, $percent);
        $score += $percent * 0.45;

        return $score;
    }

    private static function pickBestByName(array $items, string $target): array
    {
        if ($target === '' || empty($items)) {
            return [];
        }

        $best = [];
        $bestScore = 0.0;

        foreach ($items as $item) {
            if (!is_array($item)) {
                continue;
            }
            $name = trim((string) ($item['name'] ?? $item['nome'] ?? ''));
            if ($name === '') {
                continue;
            }

            $score = self::scoreNameMatch($target, $name);
            if ($score > $bestScore) {
                $best = $item;
                $bestScore = $score;
            }
        }

        if ($bestScore < 36.0) {
            return [];
        }

        return $best;
    }

    private static function resolveFipeVehicleType(array $vehicle): string
    {
        $category = self::normalizeText((string) ($vehicle['categoria'] ?? ''));
        if ($category !== '') {
            if (strpos($category, 'MOTO') !== false || strpos($category, 'MOTOCICLETA') !== false) {
                return 'motorcycles';
            }
            if (
                strpos($category, 'CAMINHAO') !== false
                || strpos($category, 'CAMINHONETE') !== false
                || strpos($category, 'TRUCK') !== false
            ) {
                return 'trucks';
            }
        }

        return 'cars';
    }

    private static function extractTargetYear(string $rawYear): int
    {
        if ($rawYear === '') {
            return 0;
        }

        preg_match_all('/\b(19|20)\d{2}\b/', $rawYear, $matches);
        if (!isset($matches[0]) || !is_array($matches[0]) || empty($matches[0])) {
            return 0;
        }

        $years = array_map('intval', $matches[0]);
        return max($years);
    }

    private static function parseYearFromYearItem(array $item): int
    {
        $code = (string) ($item['code'] ?? '');
        $name = (string) ($item['name'] ?? '');

        if (preg_match('/\b(19|20)\d{2}\b/', $code, $match)) {
            return (int) $match[0];
        }
        if (preg_match('/\b(19|20)\d{2}\b/', $name, $match)) {
            return (int) $match[0];
        }
        return 0;
    }

    private static function pickBestYearId(array $years, string $vehicleYear): string
    {
        if (empty($years)) {
            return '';
        }

        $targetYear = self::extractTargetYear($vehicleYear);
        if ($targetYear > 0) {
            foreach ($years as $item) {
                if (!is_array($item)) {
                    continue;
                }
                if (self::parseYearFromYearItem($item) === $targetYear) {
                    return (string) ($item['code'] ?? '');
                }
            }
        }

        foreach ($years as $item) {
            if (!is_array($item)) {
                continue;
            }
            $year = self::parseYearFromYearItem($item);
            if ($year >= 1900 && $year <= 2100) {
                return (string) ($item['code'] ?? '');
            }
        }

        return (string) (($years[0]['code'] ?? ''));
    }

    private static function summarizeUseZapayDebtSummary(array $event): string
    {
        $debts = is_array($event['debts'] ?? null) ? $event['debts'] : [];
        if (trim((string) ($debts['summary'] ?? '')) !== '') {
            return trim((string) $debts['summary']);
        }

        $detail = trim((string) ($event['detail'] ?? ''));
        if ($detail !== '') {
            return $detail;
        }

        $count = (int) ($debts['count'] ?? 0);
        if ($count > 0) {
            return 'Debitos encontrados: ' . $count;
        }

        return '';
    }

    private static function buildUseZapayLookupResult(array $record, string $normalizedPlate, bool $cacheHit): array
    {
        $sourceUrl = self::useZapayBaseUrl();
        $recordStatus = strtolower(trim((string) ($record['status'] ?? $record['event'] ?? '')));
        $pendingRecord = in_array($recordStatus, ['pending_async', 'pendente_webhook', 'aguardando_webhook', 'vehicle_debt_requested'], true);
        $effectiveCacheHit = $cacheHit && !$pendingRecord;
        $sourceLabel = $effectiveCacheHit
            ? 'Zapay B2B (cache webhook)'
            : ($pendingRecord ? 'Zapay B2B (pendente webhook)' : 'Zapay B2B');
        $eventName = trim((string) ($record['event'] ?? 'vehicle_debt_result'));
        $requestId = trim((string) ($record['request_id'] ?? ''));
        $plate = self::sanitizePlate((string) ($record['plate'] ?? $normalizedPlate));
        $vehiclePayload = is_array($record['vehicle'] ?? null) ? $record['vehicle'] : [];
        $vehicle = self::mapVehicleFields($vehiclePayload);

        if ($plate !== '' && trim((string) ($vehicle['placa'] ?? '')) === '') {
            $vehicle['placa'] = $plate;
        }
        if ($requestId !== '') {
            $vehicle['consulta_request_id'] = $requestId;
        }
        $vehicle['consulta_status'] = $pendingRecord
            ? 'pendente_webhook'
            : ($effectiveCacheHit ? 'resultado_cache' : 'pendente_webhook');
        $vehicle['consulta_evento'] = $eventName;
        $vehicle['consulta_origem'] = $cacheHit ? 'zapay_webhook_cache' : 'zapay_api_async';
        $vehicle['consulta_detalhe'] = trim((string) ($record['detail'] ?? ''));
        $vehicle['consulta_protocolo'] = trim((string) ($record['webhook_id'] ?? ''));
        $vehicle['consulta_versao'] = trim((string) ($record['version'] ?? 'v2'));
        $vehicle['consulta_codigo'] = trim((string) ($record['resource'] ?? 'vehicle_debt'));
        $vehicle['fonte'] = $sourceLabel;
        $vehicle['fonte_complementar'] = 'Consulta veicular assíncrona Zapay';

        $debtSummary = self::summarizeUseZapayDebtSummary($record);
        if ($debtSummary !== '' && trim((string) ($vehicle['restricoes'] ?? '')) === '') {
            $vehicle['restricoes'] = $debtSummary;
        }

        $validation = self::buildOfficialValidation(
            $vehicle,
            $sourceUrl,
            $normalizedPlate,
            [
                'source_kind' => 'official_authorized',
                'source_label' => $sourceLabel,
            ]
        );
        $scoreData = self::scoreVehicleCandidate($vehicle, $validation, 'official_authorized', $normalizedPlate);
        $vehicle['official_validation'] = $validation;

        $summaryStatus = $cacheHit ? 'cache_hit' : 'pending_async';
        if ($pendingRecord) {
            $summaryStatus = 'pending_async';
        } elseif ($effectiveCacheHit) {
            $summaryStatus = 'cache_hit';
        }
        $summaryText = $cacheHit
            ? 'Zapay retornou dados assíncronos consolidados via webhook.'
            : 'Consulta Zapay enviada; aguardando webhook de retorno.';
        if ($pendingRecord) {
            $summaryText = 'Consulta Zapay pendente de webhook.';
        } elseif ($effectiveCacheHit) {
            $summaryText = 'Zapay retornou dados assíncronos consolidados via webhook.';
        }

        $summary = [
            'status' => $summaryStatus,
            'candidates_count' => 1,
            'official_candidates' => 1,
            'best_source_label' => $sourceLabel,
            'best_source_kind' => 'official_authorized',
            'best_source_endpoint' => $sourceUrl,
            'best_score' => $scoreData['score'],
            'confidence' => $effectiveCacheHit ? min(100.0, max(42.0, ($scoreData['score'] * 0.88))) : 28.0,
            'consensus_ratio' => $effectiveCacheHit ? 100.0 : 0.0,
            'consensus_fields' => array_values(array_filter([
                trim((string) ($vehicle['placa'] ?? '')) !== '' ? 'placa' : '',
                trim((string) ($vehicle['fabricante'] ?? '')) !== '' ? 'fabricante' : '',
                trim((string) ($vehicle['modelo'] ?? '')) !== '' ? 'modelo' : '',
                trim((string) ($vehicle['ano'] ?? '')) !== '' ? 'ano' : '',
                trim((string) ($vehicle['cor'] ?? '')) !== '' ? 'cor' : '',
                trim((string) ($vehicle['restricoes'] ?? '')) !== '' ? 'restricoes' : '',
            ])),
            'divergent_fields' => [],
            'divergent_details' => [],
            'source_labels' => [$sourceLabel],
            'official_labels' => [$sourceLabel],
            'summary_text' => $summaryText,
            'notes' => $effectiveCacheHit
                ? ['zapay_webhook_cache_hit', 'consulta_oficial_autorizada']
                : ['zapay_request_pending_webhook', 'consulta_oficial_autorizada'],
            'resolved_vehicle' => $vehicle,
            'best_vehicle' => $vehicle,
        ];

        return [
            'vehicle' => $vehicle,
            'endpoint' => $sourceUrl,
            'source_kind' => 'official_authorized',
            'source_label' => $sourceLabel,
            'candidates' => [[
                'vehicle' => $vehicle,
                'endpoint' => $sourceUrl,
                'source_kind' => 'official_authorized',
                'source_label' => $sourceLabel,
                'official_validation' => $validation,
                'lookup_score' => $scoreData['score'],
                'lookup_reasons' => $scoreData['reasons'] ?? [],
                'public_fields_count' => $scoreData['public_fields_count'] ?? 0,
                'sensitive_fields_count' => $scoreData['sensitive_fields_count'] ?? 0,
            ]],
            'summary' => $summary,
            'source_count' => 1,
            'source_limit' => 1,
            'source_limit_applied' => false,
        ];
    }

    private static function fetchUseZapayVehicleData(string $normalizedPlate): array
    {
        if (!self::useZapayConfigured() || $normalizedPlate === '') {
            return [];
        }

        $cacheRecord = [];
        if (class_exists('UseZapayWebhookStore')) {
            $cacheRecord = UseZapayWebhookStore::findLatestByPlate($normalizedPlate);
            if (!empty($cacheRecord)) {
                return self::buildUseZapayLookupResult($cacheRecord, $normalizedPlate, true);
            }
        }

        $timeout = max(5, min(self::envInt('GROM_OCR_USEZAPAY_TIMEOUT', 25), 60));
        $response = self::httpPostJson(
            self::useZapayBaseUrl() . '/',
            ['license_plate' => $normalizedPlate],
            $timeout,
            self::useZapayBasicAuthHeaders()
        );

        if (empty($response)) {
            return [];
        }

        $requestId = trim((string) ($response['request_id'] ?? $response['id'] ?? $response['data']['request_id'] ?? ''));
        if ($requestId !== '' && class_exists('UseZapayWebhookStore')) {
            UseZapayWebhookStore::registerPendingRequest($normalizedPlate, $requestId, [
                'detail' => 'consulta_enviada_aguardando_webhook',
            ]);
        }

        if (isset($response['data']) && is_array($response['data']) && !empty($response['data'])) {
            $debtSummary = '';
            $debtItems = [];
            if (isset($response['data']['debts']) && is_array($response['data']['debts'])) {
                foreach ($response['data']['debts'] as $debt) {
                    if (!is_array($debt)) {
                        continue;
                    }
                    $label = trim((string) ($debt['name'] ?? $debt['description'] ?? $debt['type'] ?? $debt['detail'] ?? ''));
                    if ($label === '') {
                        continue;
                    }
                    $amount = trim((string) ($debt['amount'] ?? $debt['value'] ?? ''));
                    if ($amount !== '') {
                        $label .= ' (' . $amount . ')';
                    }
                    $debtItems[] = $label;
                    if (count($debtItems) >= 4) {
                        break;
                    }
                }
                if (!empty($debtItems)) {
                    $debtSummary = implode(' | ', $debtItems);
                }
            }

            $event = [
                'event' => (string) ($response['event'] ?? 'vehicle_debt_result'),
                'status' => (string) ($response['status'] ?? $response['event'] ?? 'resultado_imediato'),
                'detail' => (string) ($response['detail'] ?? ''),
                'request_id' => $requestId,
                'plate' => $normalizedPlate,
                'vehicle' => is_array($response['data']['vehicle'] ?? null) ? $response['data']['vehicle'] : $response['data'],
                'debts' => [
                    'count' => is_array($response['data']['debts'] ?? null) ? count($response['data']['debts']) : 0,
                    'summary' => $debtSummary,
                ],
                'webhook_id' => (string) ($response['webhook']['id'] ?? ''),
                'resource' => (string) ($response['webhook']['resource'] ?? 'vehicle_debt'),
                'version' => (string) ($response['webhook']['version'] ?? 'v2'),
            ];
            return self::buildUseZapayLookupResult($event, $normalizedPlate, true);
        }

        if ($requestId !== '') {
            return self::buildUseZapayLookupResult([
                'event' => 'vehicle_debt_requested',
                'status' => 'pending_async',
                'detail' => 'consulta_enviada_aguardando_webhook',
                'request_id' => $requestId,
                'plate' => $normalizedPlate,
                'vehicle' => [
                    'license_plate' => $normalizedPlate,
                    'placa' => $normalizedPlate,
                ],
                'debts' => [
                    'count' => 0,
                    'summary' => '',
                ],
                'webhook_id' => '',
                'resource' => 'vehicle_debt',
                'version' => 'v2',
            ], $normalizedPlate, false);
        }

        return [];
    }

    private static function fetchPrimaryVehicleData(string $normalizedPlate): array
    {
        $timeout = max(2, min(self::envInt('GROM_OCR_VEHICLE_LOOKUP_TIMEOUT', 8), 30));
        $maxSources = max(1, min(self::envInt('GROM_OCR_VEHICLE_LOOKUP_MAX_SOURCES', 5), 12));
        $sourceRequests = self::buildConfiguredSourceRequests($normalizedPlate);
        $sourceLimitApplied = false;
        if (count($sourceRequests) > $maxSources) {
            $sourceRequests = array_slice($sourceRequests, 0, $maxSources);
            $sourceLimitApplied = true;
        }

        $candidates = [];

        $useZapay = self::fetchUseZapayVehicleData($normalizedPlate);
        if (!empty($useZapay['candidates']) && is_array($useZapay['candidates'])) {
            foreach ($useZapay['candidates'] as $candidate) {
                if (is_array($candidate) && !empty($candidate)) {
                    $candidates[] = $candidate;
                }
            }
        }

        if (empty($sourceRequests) && empty($candidates)) {
            return [];
        }

        foreach ($sourceRequests as $request) {
            $endpoint = trim((string) ($request['endpoint'] ?? ''));
            if ($endpoint === '') {
                continue;
            }

            $method = strtoupper(trim((string) ($request['method'] ?? 'GET')));
            $headers = is_array($request['headers'] ?? null) ? $request['headers'] : ['Accept: application/json'];
            $payload = is_array($request['payload'] ?? null) ? $request['payload'] : [];
            $decoded = self::httpRequestJson($method, $endpoint, $timeout, $headers, $payload);
            if (empty($decoded)) {
                continue;
            }

            $responsePath = trim((string) ($request['response_path'] ?? ''));
            $payloadPath = $responsePath !== '' ? self::extractPathPayload($decoded, $responsePath) : [];
            $vehiclePayload = !empty($payloadPath) ? self::pickLikelyVehiclePayload($payloadPath) : self::pickLikelyVehiclePayload($decoded);
            if (empty($vehiclePayload)) {
                continue;
            }

            $vehicle = self::mapVehicleFields($vehiclePayload);
            if (empty($vehicle)) {
                continue;
            }

            if (empty($vehicle['placa'])) {
                $vehicle['placa'] = $normalizedPlate;
            }

            $sourceKind = (string) ($request['source_kind'] ?? self::classifySourceKind($endpoint));
            $sourceLabel = (string) ($request['source_label'] ?? self::endpointSourceLabel($endpoint));
            if (empty($vehicle['fonte'])) {
                $vehicle['fonte'] = $sourceLabel;
            } else {
                $vehicle['fonte'] = trim((string) $vehicle['fonte']) . ' | ' . $sourceLabel;
            }

            $validation = self::buildOfficialValidation(
                $vehicle,
                $endpoint,
                $normalizedPlate,
                [
                    'source_kind' => $sourceKind,
                    'source_label' => $sourceLabel,
                ]
            );
            $scoreData = self::scoreVehicleCandidate($vehicle, $validation, $sourceKind, $normalizedPlate);
            $vehicle['official_validation'] = $validation;

            $candidates[] = [
                'vehicle' => $vehicle,
                'endpoint' => $endpoint,
                'source_kind' => $sourceKind,
                'source_label' => $sourceLabel,
                'official_validation' => $validation,
                'lookup_score' => $scoreData['score'] ?? 0.0,
                'lookup_reasons' => $scoreData['reasons'] ?? [],
                'public_fields_count' => $scoreData['public_fields_count'] ?? 0,
                'sensitive_fields_count' => $scoreData['sensitive_fields_count'] ?? 0,
            ];
        }

        if (empty($candidates)) {
            return [];
        }

        $summary = self::summarizeLookupCandidates($candidates, $normalizedPlate);
        $resolvedVehicle = is_array($summary['resolved_vehicle'] ?? null) ? $summary['resolved_vehicle'] : $candidates[0]['vehicle'];
        $bestEndpoint = (string) ($summary['best_source_endpoint'] ?? ($candidates[0]['endpoint'] ?? ''));
        $bestSourceKind = (string) ($summary['best_source_kind'] ?? ($candidates[0]['source_kind'] ?? 'external_provider'));
        $bestSourceLabel = (string) ($summary['best_source_label'] ?? ($candidates[0]['source_label'] ?? 'provedor_externo'));

        return [
            'vehicle' => $resolvedVehicle,
            'endpoint' => $bestEndpoint,
            'source_kind' => $bestSourceKind,
            'source_label' => $bestSourceLabel,
            'candidates' => $candidates,
            'summary' => $summary,
            'source_count' => count($candidates),
            'source_limit' => $maxSources,
            'source_limit_applied' => $sourceLimitApplied,
        ];
    }

    public static function hasConfiguredLookup(): bool
    {
        $base = trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_URL') ?: ''));
        $list = trim((string) (getenv('GROM_OCR_VEHICLE_LOOKUP_URLS') ?: ''));
        return $base !== '' || $list !== '' || self::useZapayConfigured() || self::senatranConfigured() || self::prodespConfigured();
    }

    private static function enrichWithOpenFipe(array $vehicle): array
    {
        if (!self::envBool('GROM_OCR_OPEN_DATA_ENABLE', true)) {
            return $vehicle;
        }

        $fabricante = trim((string) ($vehicle['fabricante'] ?? ''));
        $modelo = trim((string) ($vehicle['modelo'] ?? ''));
        if ($fabricante === '' || $modelo === '') {
            return $vehicle;
        }

        $baseUrl = rtrim(self::envString('GROM_OCR_OPEN_DATA_FIPE_BASE_URL', 'https://fipe.parallelum.com.br/api/v2'), '/');
        if ($baseUrl === '') {
            return $vehicle;
        }

        $timeout = max(2, min(self::envInt('GROM_OCR_OPEN_DATA_TIMEOUT', 5), 15));
        $token = self::envString('GROM_OCR_OPEN_DATA_FIPE_TOKEN', '');

        $headers = ['Accept: application/json'];
        if ($token !== '') {
            $headers[] = 'X-Subscription-Token: ' . $token;
        }

        $references = self::httpGetJson($baseUrl . '/references', $timeout, $headers);
        if (empty($references) || !is_array($references[0] ?? null)) {
            return $vehicle;
        }

        $referenceCode = (string) ($references[0]['code'] ?? '');
        $referenceMonth = (string) ($references[0]['month'] ?? '');
        if ($referenceCode === '') {
            return $vehicle;
        }

        $vehicleType = self::resolveFipeVehicleType($vehicle);
        $brandsUrl = $baseUrl . '/' . rawurlencode($vehicleType) . '/brands?reference=' . rawurlencode($referenceCode);
        $brands = self::httpGetJson($brandsUrl, $timeout, $headers);
        $brand = self::pickBestByName(is_array($brands) ? $brands : [], $fabricante);
        if (empty($brand)) {
            return $vehicle;
        }

        $brandCode = (string) ($brand['code'] ?? '');
        if ($brandCode === '') {
            return $vehicle;
        }

        $modelsUrl = $baseUrl . '/' . rawurlencode($vehicleType) . '/brands/' . rawurlencode($brandCode) . '/models?reference=' . rawurlencode($referenceCode);
        $models = self::httpGetJson($modelsUrl, $timeout, $headers);
        $model = self::pickBestByName(is_array($models) ? $models : [], $modelo);
        if (empty($model)) {
            return $vehicle;
        }

        $modelCode = (string) ($model['code'] ?? '');
        if ($modelCode === '') {
            return $vehicle;
        }

        $yearsUrl = $baseUrl . '/' . rawurlencode($vehicleType) . '/brands/' . rawurlencode($brandCode) . '/models/' . rawurlencode($modelCode) . '/years?reference=' . rawurlencode($referenceCode);
        $years = self::httpGetJson($yearsUrl, $timeout, $headers);
        if (!is_array($years) || empty($years)) {
            return $vehicle;
        }

        $yearId = self::pickBestYearId($years, (string) ($vehicle['ano'] ?? ''));
        if ($yearId === '') {
            return $vehicle;
        }

        $detailUrl = $baseUrl . '/' . rawurlencode($vehicleType) . '/brands/' . rawurlencode($brandCode) . '/models/' . rawurlencode($modelCode) . '/years/' . rawurlencode($yearId) . '?reference=' . rawurlencode($referenceCode);
        $detail = self::httpGetJson($detailUrl, $timeout, $headers);
        if (empty($detail) || !is_array($detail)) {
            return $vehicle;
        }

        $complement = [
            'fipe_preco_medio' => (string) ($detail['price'] ?? ''),
            'fipe_mes_referencia' => (string) ($detail['referenceMonth'] ?? $referenceMonth),
            'fipe_codigo' => (string) ($detail['codeFipe'] ?? ''),
            'fipe_combustivel' => (string) ($detail['fuel'] ?? ''),
            'fipe_ano_modelo' => (string) ($detail['modelYear'] ?? ''),
            'fipe_modelo_encontrado' => (string) ($detail['model'] ?? ''),
            'fipe_tipo_veiculo' => (string) ($detail['vehicleType'] ?? ''),
        ];
        $complement = array_filter($complement, static function ($value) {
            return $value !== '';
        });

        foreach ($complement as $key => $value) {
            $vehicle[$key] = $value;
        }

        $vehicle['fonte_complementar'] = self::FIPE_SOURCE_LABEL;
        $vehicle['fonte_complementar_url'] = self::FIPE_DOC_URL;

        $primarySource = trim((string) ($vehicle['fonte'] ?? 'provedor_externo'));
        $vehicle['fontes_utilizadas'] = 'consulta_placa=' . $primarySource . ' | complemento=' . self::FIPE_SOURCE_LABEL;

        return $vehicle;
    }

    public static function searchByPlate($plate): array
    {
        $normalizedPlate = self::sanitizePlate((string) $plate);
        if (strlen($normalizedPlate) < 7) {
            return [];
        }

        $lookup = self::fetchPrimaryVehicleData($normalizedPlate);
        if (empty($lookup) || !is_array($lookup)) {
            return [];
        }

        $vehicle = is_array($lookup['vehicle'] ?? null) ? $lookup['vehicle'] : [];
        if (empty($vehicle)) {
            return [];
        }

        $lookupSummary = is_array($lookup['summary'] ?? null) ? $lookup['summary'] : [];
        $vehicle = self::enrichWithOpenFipe($vehicle);
        $vehicle['official_validation'] = self::buildOfficialValidation(
            $vehicle,
            (string) ($lookup['endpoint'] ?? ''),
            $normalizedPlate,
            $lookup
        );

        $vehicle['sensitive_policy'] = self::envBool('GROM_OCR_VEHICLE_REVEAL_SENSITIVE_FIELDS', false)
            ? 'revelado_por_configuracao'
            : 'mascarado_por_padrao';
        $consultedLabels = is_array($lookupSummary['source_labels'] ?? null) ? $lookupSummary['source_labels'] : [];
        $officialLabels = is_array($lookupSummary['official_labels'] ?? null) ? $lookupSummary['official_labels'] : [];
        $sourceParts = [];
        if (!empty($consultedLabels)) {
            $sourceParts[] = 'consulta_multifonte=' . implode(' / ', array_map('strval', $consultedLabels));
        }
        $existingSources = trim((string) ($vehicle['fontes_utilizadas'] ?? ''));
        if ($existingSources !== '') {
            $sourceParts[] = $existingSources;
        }
        $validationLabel = trim((string) ($vehicle['official_validation']['source_label'] ?? ''));
        if ($validationLabel !== '') {
            $sourceParts[] = 'validacao_oficial=' . $validationLabel;
        }
        $vehicle['fontes_utilizadas'] = !empty($sourceParts)
            ? implode(' | ', array_values(array_unique(array_filter($sourceParts))))
            : 'consulta_placa=' . (string) ($vehicle['fonte'] ?? 'provedor_externo');

        $vehicle['consulta_multifonte_status'] = (string) ($lookupSummary['status'] ?? 'indefinido');
        $vehicle['consulta_multifonte_candidatos'] = (int) ($lookupSummary['candidates_count'] ?? 0);
        $vehicle['consulta_multifonte_oficiais'] = !empty($officialLabels) ? implode(' | ', array_map('strval', $officialLabels)) : 'nenhuma';
        $vehicle['consulta_multifonte_fontes'] = !empty($consultedLabels) ? implode(' | ', array_map('strval', $consultedLabels)) : (string) ($vehicle['fonte'] ?? 'provedor_externo');
        $vehicle['consulta_multifonte_confianca'] = number_format((float) ($lookupSummary['confidence'] ?? 0.0), 1, '.', '');
        $vehicle['consulta_multifonte_taxa_consenso'] = number_format((float) ($lookupSummary['consensus_ratio'] ?? 0.0), 1, '.', '');
        $vehicle['consulta_multifonte_consenso'] = is_array($lookupSummary['consensus_fields'] ?? null) && !empty($lookupSummary['consensus_fields'])
            ? implode(', ', array_map('strval', $lookupSummary['consensus_fields']))
            : 'sem_campos_consolidados';
        $vehicle['consulta_multifonte_divergencias'] = is_array($lookupSummary['divergent_details'] ?? null) && !empty($lookupSummary['divergent_details'])
            ? implode(' | ', array_map('strval', $lookupSummary['divergent_details']))
            : 'sem_divergencias_relevantes';
        $vehicle['consulta_multifonte_resumo'] = (string) ($lookupSummary['summary_text'] ?? 'Consulta nao consolidada.');
        $vehicle['consulta_multifonte_score'] = number_format((float) ($lookupSummary['best_score'] ?? 0.0), 1, '.', '');
        $vehicle['consulta_multifonte_fonte_principal'] = (string) ($lookupSummary['best_source_label'] ?? $vehicle['fonte'] ?? 'provedor_externo');
        $vehicle['consulta_multifonte_fonte_tipo'] = (string) ($lookupSummary['best_source_kind'] ?? 'external_provider');
        $vehicle['consulta_multifonte_alertas'] = is_array($lookupSummary['notes'] ?? null) && !empty($lookupSummary['notes'])
            ? implode(' | ', array_map('strval', $lookupSummary['notes']))
            : 'sem_alertas';
        $vehicle['consulta_multifonte_limite'] = (int) ($lookup['source_limit'] ?? 0);
        $vehicle['consulta_multifonte_limite_aplicado'] = !empty($lookup['source_limit_applied']) ? 'Sim' : 'Nao';

        if (!empty($lookupSummary['source_count'])) {
            $vehicle['consulta_multifonte_candidatos'] = (int) $lookupSummary['source_count'];
        }
        return $vehicle;
    }

    public static function sanitizeForDisplay(array $vehicle): array
    {
        if (empty($vehicle)) {
            return [];
        }

        $display = $vehicle;
        $fieldsToMask = [
            'chassi' => 4,
            'renavam' => 4,
            'proprietario' => 0,
            'cpf_cnpj' => 0,
            'endereco' => 0,
            'estampador' => 0,
            'codigo_seguranca_crv' => 3,
            'serial_qrcode' => 4,
        ];

        foreach ($fieldsToMask as $field => $visibleTail) {
            if (!isset($display[$field]) || trim((string) $display[$field]) === '') {
                continue;
            }

            $display[$field] = $visibleTail > 0
                ? self::maskSensitiveValue((string) $display[$field], $visibleTail)
                : '[restrito]';
        }

        return $display;
    }
}
