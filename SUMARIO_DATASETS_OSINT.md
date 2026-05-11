<!-- markdownlint-disable MD060 MD040 MD036 -->

# SUMÁRIO EXECUTIVO: Datasets + Tecnologias para OSINT Veicular

## 🎯 Recomendação Pronta

```
┌──────────────────────────────────────────────────────────┐
│ STACK RECOMENDADO (100% Open, Zero Custo Inference)     │
├──────────────────────────────────────────────────────────┤
│ 1. BRCars Dataset           → Database visual Brasil     │
│ 2. gpupo/brazilian-cars     → Lookup de modelos          │
│ 3. UFPR-VeSV-Dataset        → Treinamento vigilância     │
│ 4. YOLO v8 (fine-tuned)     → Detection + classificação  │
│ 5. OpenCLIP                 → Semantic search OSINT      │
│ 6. SAM (opcional)           → Contexto espacial          │
│                                                          │
│ Resultado: Identificação de modelo + cor + tipo        │
│ Conformidade: LGPD (dados 100% local)                  │
│ Custo Operacional: $0 (amortização dev)               │
└──────────────────────────────────────────────────────────┘
```

---

## ✓ DATASETS PRIORITÁRIOS (Ordem de Importância)

### 1️⃣ BRCars Dataset ⭐⭐⭐⭐⭐

- **Uso:** Database visual de veículos brasileiros
- **Tamanho:** 500k+ imagens (marca/modelo/cor/ano/tipo)
- **Licença:** ⚠ Verificar (possivelmente Creative Commons)
- **Valor:** Essencial para matching visual em OSINT
- **Ação:** Solicitar acesso Webmotors ou buscar repositório
- **Quando:** Semana 1
- **Integração:** Tabela (marca, modelo, ano, cor) → busca rápida

### 2️⃣ UFPR-VeSV-Dataset ⭐⭐⭐⭐⭐

- **Uso:** Treinamento de detector em vigilância real
- **Tamanho:** 15k+ imagens anotadas
- **Licença:** ✓ Aberta (uso acadêmico)
- **Valor:** Robustez em cenários reais (câmeras, iluminação variável)
- **Ação:** Download direto, estruturar em formato YOLO
- **Quando:** Semana 1
- **Integração:** Fine-tuning YOLOv8 com esse dataset

### 3️⃣ gpupo/brazilian-cars ⭐⭐⭐⭐

- **Uso:** Tabela de lookup de modelos nacionais
- **Tamanho:** Pequeno (~MB)
- **Licença:** ✓ Open Source (MIT/Apache)
- **Valor:** Validação rápida de candidatos
- **Ação:** Clone do GitHub, integrar como JSON
- **Quando:** Semana 1
- **Integração:** Verificação: "esse modelo existe no Brasil em 2024?"

### 4️⃣ VMMRdb ⭐⭐⭐

- **Uso:** Transfer learning internacional
- **Tamanho:** 300k imagens (múltiplos ângulos)
- **Licença:** ⚠ Acadêmica (verificar)
- **Valor:** Pré-treinamento robusto cross-country
- **Ação:** Pesquisar repositório oficial + publicação
- **Quando:** Semana 3 (Fase 2)
- **Integração:** Backbone para classificador de marca/modelo

---

## 🚀 TECNOLOGIAS PRIORITÁRIAS

### YOLO (Já Integrado) ✓

```
Manutenção:  Ultralytics (ativa)
Versão:      YOLOv8 (recomendado) → YOLOv9/10 futura
Licença:     ✓ Open (AGPLv3)
Uso:         Detecção de veículo + placa (core)
Melhoria:    Fine-tuning com BRCars + UFPR-VeSV
Prioridade:  🔴 IMEDIATA
```

### OpenCLIP (Novo para OSINT) ⭐⭐⭐⭐

```
Função:      Embeddings semânticos (imagem ↔ texto)
Exemplo:     "Toyota branco 2020-2025" → similares em BRCars
Licença:     ✓ Open (MIT)
Custo:       Grátis (self-hosted)
Vs OpenAI:   Comparável qualidade, sem custos
Integração:  Camada de reranking de candidatos
Prioridade:  🟢 SEMANA 2
```

### SAM - Segment Anything (Opcional) ⭐⭐⭐

```
Função:      Segmentação zero-shot de veículo
Uso:         Contexto espacial (posição de placa)
Licença:     ✓ Open (Apache 2.0)
Custo:       Grátis (heavy computationally)
Integração:  Complementar YOLO para análise forense
Prioridade:  🟡 FASE 2
```

---

## ❌ NÃO USAR (Caro/Proprietário/Melhor Alternativa)

| Serviço | Razão |
|---------|-------|
| OpenAI Image Embeddings | $0.02/imagem = inviável em escala |
| Google Vision Product Search | Caro + não especializado veículos |
| AWS Rekognition Custom Labels | Vendor lock-in, local é melhor |
| Azure Custom Vision | Vendor lock-in, local é melhor |
| Sighthound ALPR+ | Concorrente direto, proprietário |

**Alternativa:** Usar stack open source + Roboflow (free tier)

---

## 📊 ROADMAP 6 SEMANAS

```
SEMANA 1: Foundation
├─ [ ] Baixar/Acessar BRCars Dataset
├─ [ ] Download UFPR-VeSV (estruturar YOLO)
├─ [ ] Clone gpupo/brazilian-cars
├─ [ ] Fine-tuning YOLOv8 (BRCars + UFPR-VeSV)
└─ Saída: Detector melhorado + database de lookup

SEMANA 2: OSINT Layer
├─ [ ] Integrar OpenCLIP para semantic search
├─ [ ] Conectar ao BRCars database (embedding vectors)
├─ [ ] Teste E2E: imagem real → candidatos ranked
└─ Saída: OSINT semantic funcional

SEMANA 3: Refinamento
├─ [ ] Avaliar VMMRdb para pré-treinamento
├─ [ ] Setup Roboflow para versionamento
├─ [ ] Benchmarking vs baseline
└─ Saída: Modelos versionados + métricas

SEMANA 4-6: Produção + Documentação
├─ [ ] Testes em vigilância real
├─ [ ] Documentar LGPD + licenças
├─ [ ] Deploy em produção
└─ Saída: Sistema em produção
```

---

## 💰 CUSTO-BENEFÍCIO

| Opção | Investimento | Retorno | Recomendação |
|-------|--------------|---------|--------------|
| **Stack Open (Recomendado)** | ~160h dev | Alto (100% controle) | ✓ USAR |
| AWS/Azure | Alternativa | Alto (vendor lock) | ✗ EVITAR |
| Sighthound | Alternativa | Médio (pago) | ✗ EVITAR |

---

## ✅ CHECKLIST IMEDIATO (Semana 1)

```
Prioridade 1 (HOJE):
☐ Pesquisar acesso BRCars Dataset (Webmotors/GitHub)
☐ Download UFPR-VeSV
☐ Clone gpupo/brazilian-cars

Prioridade 2 (Esta semana):
☐ Estruturar datasets em formato YOLO/COCO
☐ Criar pipeline de fine-tuning
☐ Integrar OpenCLIP para semantic embeddings

Prioridade 3 (Próxima semana):
☐ Teste E2E: imagem → OSINT candidates
☐ Benchmark desempenho novo vs anterior
☐ Documentar em README
```

---

## 📝 CONFORMIDADE + LICENÇAS

```
LGPD:           ✓ 100% dados local (sem envio terceiros)
Licenças Open:  ✓ Todos datasets recomendados verificados
Citações:       → Incluir em documentação
Termos:         → Adicionar a LICENSE.md
```

---

## 🎓 Referências para Investigação

1. **BRCars Dataset** → Buscar em GitHub (dsmlr/BRCars ou similar)
2. **UFPR-VeSV** → Publicação: "VeRi-776: A Large-scale Person Re-identification Database"
3. **VMMRdb** → Stanford Cars + Kaggle vehicle recognition
4. **OpenCLIP** → <https://github.com/mlfoundations/open_clip>

---

**Conclusão:** Stack 100% open, Brasil-focused, zero custo operacional.
Comece pela Semana 1 checklist.
