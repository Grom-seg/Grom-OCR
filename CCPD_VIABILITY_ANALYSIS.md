# Avaliacao de Viabilidade do Dataset CCPD no GROM OCR

## Decisao Executiva
Uso RECOMENDADO com escopo controlado para validacao tecnica de pipeline.
Uso NAO RECOMENDADO como base principal para reconhecimento de placas brasileiras/Mercosul.

Justificativa central:
- O CCPD foi construido para placas chinesas (layout, tipografia, distribuicao de caracteres e contexto urbano diferentes).
- Treinar OCR final para Brasil/Mercosul com CCPD tende a aumentar viés de dominio e falso positivo em padroes locais.

## Onde o CCPD agrega valor (uso permitido)
1. Testar arquitetura de deteccao de placa (recall de bbox em cenas dificeis).
2. Treinar/validar pre-processamento (blur, contraste, iluminacao, angulo, ruído).
3. Validar pipeline OCR ponta-a-ponta (latencia, estabilidade, controle de erro).
4. Testar recorte automatico e pos-processamento geometricamente robusto.
5. Validar metricas de confianca e politicas de aceite/revisao.
6. Testar robustez operacional em cenarios degradados (blur, perspectiva, low light, overexposure).

## Onde NAO usar CCPD
1. Nao usar como corpus principal de OCR para reconhecer padroes brasileiros/mercosul.
2. Nao usar como referencia unica para calibrar regex/padroes de placa BR.
3. Nao usar para definir limiares finais de aceitacao sem validacao em dataset local.

## Riscos de usar CCPD como base primaria
1. Domain shift alto: fonte, espaco entre caracteres, moldura e distribuicao nao equivalentes ao Mercosul.
2. Overfitting de detector para pistas visuais especificas de ambiente chines.
3. Regressao de OCR em casos reais locais (placas envelhecidas, reflexo, sujeira, compressao de camera brasileira).
4. Confidencia inflada por padroes visuais nao transferiveis para producao local.

## Estrategia recomendada de integracao
1. Fase A - Benchmark de robustez
- Rodar CCPD apenas para estresse de deteccao/preprocess.
- Medir: recall@IoU, taxa de crop valido, latencia media, falhas por condicao.

2. Fase B - Pre-treinamento tecnico
- Usar CCPD para pre-treino de blocos de pre-processamento e detector (separado do OCR final).
- Congelar ou reduzir peso do aprendizado antes de fine-tuning local.

3. Fase C - Fine-tuning local obrigatorio
- Ajustar detector/OCR com dados brasileiros/mercosul anotados.
- Aplicar validacao cruzada por cidade/camera/iluminacao local.

4. Fase D - Gate de producao
- So promover modelo se melhorar no conjunto local (nao apenas no CCPD).
- Regras de gate:
  - Nao piorar precision/recall local.
  - Nao piorar taxa de revisao manual.
  - Nao piorar confianca calibrada em casos dificeis BR.

## KPIs sugeridos para aceitar ganho real
1. Deteccao: Recall@0.5 IoU e Recall@0.75 IoU em dataset BR.
2. Crop: taxa de recorte util para OCR.
3. OCR: CER/WER local + taxa de placa completa correta.
4. Operacional: latencia P50/P95 e taxa de erro por imagem.
5. Confianca: curva de calibracao (ECE/Brier) e qualidade de threshold de aceite.

## Conclusao
- CCPD e viavel e util como acelerador tecnico de engenharia de robustez.
- CCPD nao deve ser base principal do reconhecimento final para Brasil/Mercosul.
- A abordagem correta e: CCPD para estresse e pre-treino tecnico + fine-tuning e validacao final em dados locais.
