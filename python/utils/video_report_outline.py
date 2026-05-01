ANALYSIS_VIDEO_REPORT_OUTLINE = [
    {
        'number': '1',
        'title': 'Identificação da captura',
        'summary': (
            'Apresenta o arquivo-fonte, a imagem original do quadro selecionado, o recorte '
            'da placa, a resolução, a duração, a taxa de quadros, o codec perceptível, a '
            'cadeia de custódia digital, a integridade da entrada e a cobertura integral '
            'do vídeo de até 10 minutos.'
        ),
        'subitems': [
            {
                'number': '1.1',
                'title': 'Imagem original e recorte da placa',
                'summary': (
                    'Resumo do quadro-fonte, do recorte bruto da placa e do recorte tratado '
                    'usado para comparação documental.'
                ),
            },
            {
                'number': '1.2.1',
                'title': 'Cadeia de custódia digital',
                'summary': (
                    'Registro da origem, do encadeamento probatório e dos hashes usados para '
                    'rastreabilidade do material analisado.'
                ),
            },
            {
                'number': '1.2.2',
                'title': 'Integridade de entrada',
                'summary': (
                    'Valida assinatura, extensão, decodificação e compatibilidade do vídeo '
                    'com o ambiente de análise.'
                ),
            },
            {
                'number': '1.3',
                'title': 'Metadados da imagem e do vídeo',
                'summary': (
                    'Explica tamanho, resolução, duração, FPS, codec, padrão da captura e '
                    'demais metadados observados no probe inicial.'
                ),
            },
            {
                'number': '1.4',
                'title': 'Descrição técnica da cena',
                'summary': (
                    'Registra se a cena foi captada em baixa luminosidade, chuva, ângulo '
                    'oblíquo, forte contraste, cena externa ou outro fator que influencie a '
                    'qualidade da leitura pericial.'
                ),
            },
        ],
    },
    {
        'number': '2',
        'title': 'Tratamento técnico da imagem e do vídeo',
        'summary': (
            'Descreve a decodificação frame a frame, a preparação da linha temporal, o '
            'pré-processamento aplicado, a cobertura temporal integral e os critérios '
            'usados para selecionar os alvos de maior valor probatório.'
        ),
        'subitems': [
            {
                'number': '2.1',
                'title': 'Decodificação frame a frame',
                'summary': (
                    'Registra como os quadros foram lidos, estabilizados no tempo lógico da '
                    'varredura e normalizados para OCR.'
                ),
            },
            {
                'number': '2.2',
                'title': 'Seleção dos alvos de interesse',
                'summary': (
                    'Expõe os critérios de nitidez, contraste, confiança textual e apoio do '
                    'consenso para apontar os alvos de maior valor probatório.'
                ),
            },
            {
                'number': '2.3',
                'title': 'Tratamento do quadro selecionado',
                'summary': (
                    'Documenta o recorte bruto da placa, o recorte tratado e os ajustes '
                    'visuais usados para aumentar a legibilidade.'
                ),
            },
        ],
    },
    {
        'number': '3',
        'title': 'OCR, consenso e ambiguidade',
        'summary': (
            'Consolida os motores OCR acionados nos quadros analisados, os percentuais '
            'obtidos e as ambiguidades temporais que influenciaram o resultado final.'
        ),
        'subitems': [
            {
                'number': '3.1',
                'title': 'Motores empregados',
                'summary': 'Lista os motores OCR executados nos quadros extraídos do vídeo.',
            },
            {
                'number': '3.2',
                'title': 'Consenso temporal',
                'summary': (
                    'Resume a leitura mais recorrente ao longo da linha temporal e os quadros '
                    'que mais contribuíram para a decisão.'
                ),
            },
            {
                'number': '3.3',
                'title': 'Ambiguidades e hipótese aceita',
                'summary': (
                    'Aponta caracteres incertos, leituras concorrentes e a hipótese final '
                    'aceita pelo motor de consenso.'
                ),
            },
            {
                'number': '3.4',
                'title': 'Fragmentos parciais e confronto',
                'summary': (
                    'Preserva leituras curtas de um ou dois caracteres ao longo da linha '
                    'temporal para confronto com veículo suspeito, sem convertê-las em '
                    'placa final.'
                ),
            },
        ],
    },
    {
        'number': '4',
        'title': 'Correção e conferência humana',
        'summary': (
            'Registra se houve ajuste manual, revisão humana e validação final antes da '
            'emissão do relatório de apoio à investigação.'
        ),
        'subitems': [
            {
                'number': '4.1',
                'title': 'Revisão das hipóteses',
                'summary': (
                    'Indica quais hipóteses foram confrontadas antes da conferência humana.'
                ),
            },
            {
                'number': '4.2',
                'title': 'Conferência humana obrigatória',
                'summary': (
                    'Declara a revisão humana como etapa obrigatória de controle antes da '
                    'consolidação documental.'
                ),
            },
            {
                'number': '4.3',
                'title': 'Aprovação final',
                'summary': (
                    'Informa se o resultado foi liberado para impressão documental ou '
                    'mantido para correção em tela.'
                ),
            },
        ],
    },
    {
        'number': '5',
        'title': 'Conclusão',
        'summary': (
            'Fecha o documento com síntese técnica clara sobre o vídeo-fonte, a extração '
            'de quadros, o OCR e a leitura pericial consolidada.'
        ),
        'subitems': [
            {
                'number': '5.1',
                'title': 'Síntese documental',
                'summary': (
                    'Resume a cadeia entre o vídeo, os quadros extraídos, o OCR e a validação '
                    'humana.'
                ),
            },
            {
                'number': '5.2',
                'title': 'Resultado consolidado',
                'summary': 'Apresenta o resultado final e o nível de confiabilidade alcançado.',
            },
            {
                'number': '5.3',
                'title': 'Observações finais',
                'summary': (
                    'Mantém linguagem técnica, objetiva e acessível para operadores e leigos.'
                ),
            },
        ],
    },
]


def get_video_analysis_report_outline():
    return [
        {
            **section,
            'subitems': [dict(subitem) for subitem in section.get('subitems', [])],
        }
        for section in ANALYSIS_VIDEO_REPORT_OUTLINE
    ]
