ANALYSIS_REPORT_OUTLINE = [
    {
        'number': '1',
        'title': 'Identificação da captura',
        'summary': (
            'Apresenta a imagem original, o recorte bruto, o recorte tratado, a cadeia de '
            'custódia digital, a integridade de entrada, os metadados e a descrição técnica '
            'da cena.'
        ),
        'subitems': [
            {
                'number': '1.1',
                'title': 'Imagem original, recorte bruto e recorte tratado',
                'summary': (
                    'Exibe a fonte documental em escala reduzida, o recorte bruto extraído e '
                    'o recorte tratado, com comparação visual para conferência pericial.'
                ),
            },
            {
                'number': '1.2',
                'title': 'Cadeia de custódia digital',
                'summary': (
                    'Registra origem, preservação, encadeamento da prova digital e '
                    'rastreabilidade da análise.'
                ),
            },
            {
                'number': '1.3',
                'title': 'Integridade de entrada',
                'summary': (
                    'Confere assinatura, formato, consistência do arquivo e alertas de '
                    'segurança na entrada.'
                ),
            },
            {
                'number': '1.4',
                'title': 'Metadados da imagem',
                'summary': (
                    'Resume EXIF, resolução, data, dispositivo de captura e parâmetros '
                    'técnicos disponíveis.'
                ),
            },
            {
                'number': '1.5',
                'title': 'Descrição técnica da imagem',
                'summary': (
                    'Descreve o contexto visual observado, como baixa luminosidade, excesso de '
                    'luz, chuva, cena externa ou outras condições relevantes.'
                ),
            },
        ],
    },
    {
        'number': '2',
        'title': 'Tratamento técnico da imagem',
        'summary': (
            'Explica o modelo de tratamento, os procedimentos de pré-processamento, a '
            'calibração aplicada e os refinamentos usados para maximizar repetibilidade e '
            'acurácia.'
        ),
        'subitems': [
            {
                'number': '2.1',
                'title': 'Modelo e estratégia de tratamento',
                'summary': (
                    'Descreve a família de software, a estratégia de seleção do ROI e a linha '
                    'pericial adotada para preservar a evidência.'
                ),
            },
            {
                'number': '2.2',
                'title': 'Pré-processamento e recorte',
                'summary': (
                    'Documenta equalização, contraste, nitidez, alinhamento e demais ajustes '
                    'visuais utilizados.'
                ),
            },
            {
                'number': '2.3',
                'title': 'Calibração e parâmetros técnicos',
                'summary': (
                    'Registra versões, parâmetros e critérios empregados no tratamento '
                    'automatizado.'
                ),
            },
        ],
    },
    {
        'number': '3',
        'title': 'OCR, consenso e ambiguidade',
        'summary': (
            'Consolida os motores utilizados, as probabilidades de acerto, os percentuais '
            'apresentados e os pontos de ambiguidade entre leituras.'
        ),
        'subitems': [
            {
                'number': '3.1',
                'title': 'Motores empregados',
                'summary': (
                    'Lista os motores OCR acionados e o papel de cada um no ensemble.'
                ),
            },
            {
                'number': '3.2',
                'title': 'Percentuais e confiança',
                'summary': (
                    'Resume as pontuações, confidências e índices de concordância obtidos.'
                ),
            },
            {
                'number': '3.3',
                'title': 'Ambiguidades e hipótese aceita',
                'summary': (
                    'Expõe leituras conflitantes e a hipótese final escolhida pelo consenso.'
                ),
            },
            {
                'number': '3.4',
                'title': 'Fragmentos parciais e confronto',
                'summary': (
                    'Preserva leituras curtas de um ou dois caracteres para eventual '
                    'confronto com veículo suspeito, sem promovê-las a placa final.'
                ),
            },
        ],
    },
    {
        'number': '4',
        'title': 'Correção e conferência humana',
        'summary': (
            'Registra correções eventuais e a conferência humana obrigatória antes da '
            'consolidação final.'
        ),
        'subitems': [
            {
                'number': '4.1',
                'title': 'Revisão das hipóteses',
                'summary': (
                    'Aponta se houve ajuste manual na leitura e quais hipóteses foram '
                    'confrontadas.'
                ),
            },
            {
                'number': '4.2',
                'title': 'Conferência humana obrigatória',
                'summary': (
                    'Declara a conferência humana como etapa de validação antes da aprovação '
                    'do laudo.'
                ),
            },
            {
                'number': '4.3',
                'title': 'Aprovação final',
                'summary': (
                    'Indica se o resultado foi consolidado para impressão documental ou '
                    'mantido em correção em tela.'
                ),
            },
        ],
    },
    {
        'number': '5',
        'title': 'Conclusão',
        'summary': (
            'Fecha o documento com síntese técnica, em linguagem clara e credível, sobre as '
            'tecnologias usadas no tratamento, na captura da tela e no processamento da '
            'imagem.'
        ),
        'subitems': [
            {
                'number': '5.1',
                'title': 'Síntese documental',
                'summary': (
                    'Resume o caminho percorrido entre a fonte, o tratamento, o OCR e a '
                    'validação humana.'
                ),
            },
            {
                'number': '5.2',
                'title': 'Resultado consolidado',
                'summary': (
                    'Apresenta o resultado final com o nível de confiabilidade alcançado.'
                ),
            },
            {
                'number': '5.3',
                'title': 'Observações finais',
                'summary': (
                    'Mantém o tom técnico, mas acessível, para leitura por operadores e '
                    'interessados leigos.'
                ),
            },
        ],
    },
]


def get_analysis_report_outline():
    return [
        {
            **section,
            'subitems': [dict(subitem) for subitem in section.get('subitems', [])],
        }
        for section in ANALYSIS_REPORT_OUTLINE
    ]
