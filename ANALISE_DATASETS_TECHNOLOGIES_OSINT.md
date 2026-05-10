# Análise de Datasets, Tecnologias e Plataformas para Identificação Veicular
**Objetivo:** Avaliar viabilidade para treinamento, calibração e pesquisa OSINT do sistema GROM OCR  
**Data:** 10 de maio de 2026  
**Foco:** Veículos brasileiros em cenários reais (placa, modelo, cor, tipo, vigilância)

---

## 1. DATASETS BRASILEIROS ESPECIALIZADOS

### 1.1 UFPR-VeSV-Dataset
**Descrição:** Dataset de vigilância de veículos da Universidade Federal do Paraná  
**Especialidade:** Cenários reais de vigilância, captura de veículos  
**Características:**
- Imagens em múltiplos ângulos
- Anotações de pose e viewpoint
- Variações de iluminação/clima
- Foco em desempenho em vigilância

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Aberta | Uso acadêmico/pesquisa (verificar termos específicos) |
| Cobertura Brasil | ✓ Alta | Dataset construído no Brasil |
| Modelos Nacionais | ✓ Sim | Veículos em circulação no Brasil |
| Placa | ✗ Parcial | Foco em identificação visual, não placa |
| API | ✗ Não | Download direto ou repositório |
| Tamanho | ~ 15k+ imagens | Adequado para fine-tuning |
| Integração GROM | ✓ Alta | Compatível com pipeline de vigilância |

**Recomendação:** ✓ **USAR PARA:**
- Treinamento de detector de veículos em pose/ângulo
- Calibração de qualidade de frame em vídeo
- Validação de robustez em cenários reais

---

### 1.2 BRCars Dataset
**Descrição:** Base brasileira grande derivada de anúncios Webmotors  
**Especialidade:** Modelos, fabricantes, cores, tipos de veículos brasileiros  
**Características:**
- Catálogo estruturado de centenas de modelos
- Imagens de alta qualidade (cenários de anúncio)
- Metadados: marca, modelo, ano, cor, tipo
- Cobertura completa de mercado nacional

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ⚠ Limitada | Verificar termos Webmotors (possivelmente apenas pesquisa) |
| Cobertura Brasil | ✓ Muito Alta | Mercado automotivo nacional |
| Modelos Nacionais | ✓ Completo | Todos modelos vendidos no Brasil |
| Placa | ✓ Sim | Imagens com placa visible |
| Imagens Vigilância | ✗ Não | Imagens de catálogo (qualidade alta, ângulos padrão) |
| API | ✗ Não | Download estático |
| Tamanho | ~500k+ imagens | Muito grande, exige seleção/filtro |
| Integração OSINT | ✓ Muito Alta | Perfeito para database de modelos/cores para matching |

**Recomendação:** ✓ **USAR PARA:**
- **OSINT matching:** Comparação visual de candidatos (marca/modelo/ano/cor)
- Treinamento de classificador de marca/modelo
- Calibração de palette de cores por modelo
- Construir tabela de lookup: (cor_detectada, forma_corpo) → modelos_candidatos

**Ação:** Solicitar acesso ou verificar licença Creative Commons

---

### 1.3 gpupo/brazilian-cars
**Descrição:** Lista estruturada de veículos comercializados no Brasil  
**Especialidade:** Tabela de referência de modelos/anos/especificações  
**Características:**
- Estrutura JSON/CSV de modelos
- Metadados: marca, modelo, categoria, geração
- Sem imagens, mas lista completa

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Open | Tipicamente GitHub (MIT/Apache) |
| Cobertura Brasil | ✓ Total | Base de vendas nacional |
| Uso Principal | ✓ Lookup | Não é dataset, é referência estruturada |
| Tamanho | Pequeno | JSON estruturado, carregável em memória |
| Integração OSINT | ✓ Excelente | Usar para validar candidatos + correlação temporal |

**Recomendação:** ✓ **USAR PARA:**
- Tabela de referência para pesquisa OSINT
- Validação de candidatos (se modelo + ano são válidos?)
- Filtro de modelos impossíveis
- Contexto temporal (geração 2020-2025, por exemplo)

---

## 2. DATASETS INTERNACIONAIS (Veículos, Partes, Luzes)

### 2.1 VMMRdb (Vehicle Make and Model Recognition)
**Descrição:** Base internacional grande para reconhecimento de marca/modelo/ano  
**Especialidade:** Pré-treinamento robusto em marca/modelo em múltiplos países  
**Características:**
- Centenas de milhares de imagens
- Múltiplos ângulos, iluminações, backgrounds
- Anotações de marca, modelo, ano
- Diversidade geográfica (inclui Brasil)

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ⚠ Acadêmica | Pesquisa apenas (verificar publicação) |
| Cobertura Global | ✓ Alta | Inclui modelos vendidos no Brasil |
| Imagens Vigilância | ✓ Sim | Mix de vigilância, rua, catálogo |
| Tamanho | ~300k imagens | Adequado para transfer learning |
| Pre-treinamento | ✓ Sim | Pode usar como modelo base |
| Integração | ✓ Alta | Compatível com pipeline de classificação |

**Recomendação:** ✓ **USAR PARA:**
- Transfer learning: fine-tuning com BRCars/UFPR
- Pré-treinar backbone de classificador (marca/modelo)
- Validação de robustez cross-country
- Benchmarking de desempenho

**Nota:** Procurar publicação original + repositório oficial

---

### 2.2 dsmlr/Car-Parts-Segmentation
**Descrição:** Segmentação de partes do veículo (farol, lanterna, para-choque, etc.)  
**Especialidade:** Detecção de componentes externos  
**Características:**
- Anotações de pixel-level (partes)
- ~1k-10k imagens anotadas
- Foco em componentes diagnósticos

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Open (GitHub) | Verificar license file |
| Aplicação GROM | ⚠ Indireta | Útil para extrair features de forma, mas não direto para placa/modelo |
| Segmentação | ✓ Sim | Pixel-level masks |
| Integração | ✓ Média | Pode usar SAM/Detectron2 em lugar de recriar |

**Recomendação:** ⚠ **USAR COM MODERAÇÃO PARA:**
- Análise de dano/condição do veículo (contexto de cena)
- Feature extraction de componentes diagnósticos
- Validação de posição de placa (relação com para-choque/vidro)

---

### 2.3 Detection-car-exterior-components
**Descrição:** Detecção de componentes externos (headlight, taillight, bumper, hood, grille)  
**Especialidade:** Object detection de partes  
**Características:**
- Bounding boxes de partes
- Imagens de múltiplos ângulos
- COCO-format ou YOLO-format

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | Verificar | Tipicamente GitHub |
| YOLO Compatível | ✓ Sim | Pode treinar YOLOv8 nesse dataset |
| Aplicação Direta | ⚠ Média | Útil para contexto espacial, não identificação |
| Integração | ✓ Média | Complementar a detector de placa |

**Recomendação:** ⚠ **USAR PARA:**
- Entender pose do veículo (se headlight visível = frente)
- Contexto espacial para relativizar posição de placa
- Validação de geometria de veículo

---

### 2.4 Vehicle Lights Dataset / CERV
**Descrição:** Máscaras específicas de faróis e lanternas  
**Especialidade:** Detecção de luzes (diagnóstico de estado)  
**Características:**
- Imagens de luzes ligadas/desligadas
- Anotações de máscara
- Variações de clima/iluminação

| Critério | Status | Detalhes |
|----------|--------|----------|
| Aplicação GROM | ⚠ Indireta | Útil para análise forense de cenário (noite/dia) |
| Recomendação | ⚠ Baixa Prioridade | Complementar, não essencial para ID de modelo |

---

## 3. TECNOLOGIAS E PLATAFORMAS IA

### 3.1 YOLO / Ultralytics
**Descrição:** Detector de objetos em tempo real (detecção de veículos, placas)  
**Status no GROM:** ✓ **JÁ INTEGRADO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Open | YOLOv8 com AGPLv3 (verificar redistribuição) |
| Uso Atual | ✓ Ativo | Detector de veículos + placa |
| Versão Recomendada | ✓ YOLOv8n/s | Nano/small para inference rápido |
| Fine-tuning | ✓ Viável | Combinar UFPR-VeSV + BRCars para detector brasileiro |
| Manutenção | ✓ Ativa | Ultralytics mantém atualizado |

**Recomendação:** ✓ **MANTER + EXPANDIR**
- Fine-tuning com UFPR-VeSV para robustez de vigilância
- Fine-tuning com BRCars para cobertura de modelos nacionais
- Considerar YOLOv9/10 conforme amadurece

---

### 3.2 SAM / Segment Anything (Meta)
**Descrição:** Segmentação universal (zero-shot segmentation)  
**Aplicação:** Extrair contorno preciso de veículo a partir de imagem de vigilância  
**Status no GROM:** ⚠ **PODE SER INTEGRADO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Open | Apache 2.0 |
| Zero-shot | ✓ Sim | Funciona sem treinamento em veículos |
| Inference | ⚠ Pesado | Computacionalmente intensivo (pode usar SAM-Fast) |
| Aplicação | ✓ Alta | Complementar YOLO para contorno de veículo |
| Integração | ✓ Viável | Usar prompt automático de YOLO bbox |

**Recomendação:** ✓ **CONSIDERAR PARA:**
- Extração de máscara de veículo para análise de contexto
- Input adicional para CLIP embeddings (refinar busca)
- Análise de background para verificação de contexto de cena

---

### 3.3 CLIP / OpenCLIP (OpenAI/Open)
**Descrição:** Vision-language model para embeddings semânticos (imagem ↔ texto)  
**Aplicação:** Busca semântica visual para matching de modelos  
**Status no GROM:** ⚠ **PODE SER INTEGRADO PARA OSINT**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Open | OpenCLIP (MIT) |
| Uso em OSINT | ✓ Muito Alto | Embeddings visuais para query "Toyota Corolla branco 2020" |
| Sem treinamento | ✓ Sim | Funciona zero-shot em descrições textuais |
| Viés Brasil | ⚠ Limitado | Treinado em dados globais, pode perder nuances locais |
| Custo | ✓ Grátis | Open source / self-hosted |
| Performance | ⚠ Média | Não tão preciso quanto fine-tuned, mas robusto |

**Recomendação:** ✓ **USAR PARA:**
- **OSINT semantic search:** "veículo branco 2020-2025, modelo popular Brasil"
- Reranking de candidatos (CLIP scores de imagem real vs catálogo)
- Busca textual em atributos (cor + tipo + período + marca)

---

### 3.4 OpenAI Image Embeddings / Busca Semântica Visual
**Descrição:** Embeddings de imagem via API OpenAI Vision  
**Aplicação:** Busca visual em base de dados de modelos  
**Status no GROM:** ⚠ **REQUER CUSTO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✗ Propriedário | OpenAI, uso via API |
| Custo | ✗ Pago | ~$0.02 por imagem |
| Qualidade | ✓ Muito Alta | Modelos proprietários sofisticados |
| Escala | ⚠ Cara | Milhares de queries = custo significativo |
| Alternativa | ✓ OpenCLIP | Open source, performance comparável |
| Recomendação | ⚠ Apenas Premium | Se orçamento permite + volume baixo |

**Recomendação:** ⚠ **NÃO RECOMENDAR COMO DEFAULT**
- Usar OpenCLIP (open) como padrão
- OpenAI apenas como fallback premium se necessário

---

### 3.5 Google Vision Product Search
**Descrição:** API Google para busca visual de produtos em e-commerce  
**Aplicação:** Busca de veículos em base pública  
**Status no GROM:** ✗ **NÃO RECOMENDADO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✗ Propriedário | Google Cloud |
| Custo | ✗ Muito Alto | ~$1-10 por consulta dependendo do volume |
| Aplicação | ⚠ Vaga | Não especializado em veículos de vigilância |
| Alternativa | ✓ Melhor | Usar BRCars + OpenCLIP (gratuito) |

**Recomendação:** ✗ **EVITAR PELA CUSTO-EFETIVIDADE**

---

### 3.6 AWS Rekognition Custom Labels
**Descrição:** Classificador customizado treinado em AWS  
**Aplicação:** Classificação de marca/modelo/cor de veículo  
**Status no GROM:** ⚠ **POSSÍVEL, MAS CARO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✗ Propriedário | AWS |
| Custo | ✗ Pago | Treinamento + inference (~$1+ por imagem) |
| Treinamento | ✓ Automático | Precisa de labeled dataset (BRCars?) |
| Manutenção | ⚠ Vendor Lock-in | Dependência de AWS |
| Alternativa | ✓ Local | YOLOv8 fine-tuned (gratuito, controle total) |

**Recomendação:** ⚠ **NÃO PRIORITÁRIO**
- Usar YOLOv8 + fine-tuning local em lugar de AWS Rekognition

---

### 3.7 Azure Custom Vision
**Descrição:** Custom classifier no Azure  
**Aplicação:** Similar AWS Rekognition  
**Status no GROM:** ✗ **NÃO RECOMENDAR**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Custo | ✗ Proprietário | Similar AWS |
| Alternativa Melhor | ✓ Local | YOLOv8 open source |

---

### 3.8 Roboflow
**Descrição:** Plataforma de gerenciamento de datasets + treinamento de YOLO  
**Aplicação:** Anotação, versionamento, e treinamento de modelos YOLO  
**Status no GROM:** ⚠ **ÚTIL COMO FERRAMENTA**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✓ Freemium | Versão free adequada para pesquisa |
| Uso | ✓ Excelente | Treinamento YOLO com uma clicada (Roboflow → YOLOv8) |
| Datasets Públicos | ✓ Sim | Acesso a datasets YOLO + COCO |
| Integração | ✓ Fácil | Export como COCO, YOLO, VOC |
| Recomendação | ✓ Usar para | Organizar fine-tuning de BRCars/UFPR-VeSV |

**Recomendação:** ✓ **USAR COMO FERRAMENTA DE SUPORTE**
- Importar UFPR-VeSV/BRCars em Roboflow
- Treinar YOLOv8 detector com dataset brasileiro
- Versionar modelos treinados
- Exportar para GROM OCR

---

### 3.9 Sighthound ALPR+ / Vehicle Analytics
**Descrição:** Plataforma comercial para ALPR (Automatic License Plate Recognition) + Vehicle Analytics  
**Aplicação:** API pronta para reconhecimento de placa + análise de veículo  
**Status no GROM:** ✗ **PROPRIETÁRIO, CARO**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ✗ Proprietário | Comercial |
| Custo | ✗ Alto | ~$99-999/mês dependendo volume |
| Qualidade | ✓ Muito Alta | Especialista em ALPR |
| Integração | ✓ API REST | Fácil integração |
| Competidor | ✓ Sim | Concorrente direto ao GROM OCR |
| Recomendação | ✗ Para GROM | Usando como referência de features, não integração |

**Recomendação:** ✗ **NÃO INTEGRAR**
- Usar como benchmarking de desempenho
- Estudar features oferecidas (modelo, cor, tipo) como inspiração

---

### 3.10 CarNet.ai
**Descrição:** IA especializada em análise de veículos (marca, modelo, atributos)  
**Aplicação:** API ou modelo local para classificação de veículos  
**Status no GROM:** ⚠ **VERIFICAR DISPONIBILIDADE**

| Critério | Status | Detalhes |
|----------|--------|----------|
| Licença | ? Verificar | Provavelmente proprietário |
| Documentação | ? | Verificar site atual |
| Alternativa | ✓ Melhor | YOLOv8 + fine-tuning (open source) |

**Recomendação:** ⚠ **INVESTIGAR ANTES DE USAR**
- Se open source, avaliar
- Se proprietário, não prioritário

---

## 4. MATRIZ CONSOLIDADA DE RECOMENDAÇÕES

### Prioridade 1: USAR IMEDIATAMENTE
| Recurso | Tipo | Licença | Custo | Razão |
|---------|------|---------|-------|-------|
| BRCars Dataset | Dataset | ⚠ Verificar | Grátis/Limitado | Database de modelos brasileiros para OSINT |
| gpupo/brazilian-cars | Referência | ✓ Open | Grátis | Lookup estruturado de modelos nacionais |
| YOLO/Ultralytics | Tecnologia | ✓ Open | Grátis | Já integrado, melhorar com fine-tuning |
| UFPR-VeSV-Dataset | Dataset | ✓ Aberta | Grátis | Treinamento robusto em vigilância |
| OpenCLIP | Tecnologia | ✓ Open | Grátis | OSINT semantic search |

### Prioridade 2: CONSIDERAR PARA FASE 2
| Recurso | Tipo | Razão |
|---------|------|-------|
| VMMRdb | Dataset | Transfer learning internacional |
| SAM | Tecnologia | Segmentação de contexto |
| Roboflow | Ferramenta | Gerenciamento de fine-tuning |
| dsmlr/Car-Parts-Segmentation | Dataset | Contexto de posição de placa |

### Prioridade 3: NÃO RECOMENDAR (CARO/PROPRIETÁRIO)
| Recurso | Razão |
|---------|-------|
| OpenAI Image Embeddings | Custo alto (~$0.02/imagem) |
| Google Vision Product Search | Caro + não especializado |
| AWS Rekognition Custom Labels | Vendor lock-in, melhor local |
| Azure Custom Vision | Vendor lock-in, melhor local |
| Sighthound ALPR+ | Proprietário, concorrente direto |

---

## 5. ROADMAP DE INTEGRAÇÃO PROPOSTO

### Fase 1: Base Sólida (Semanas 1-2)
```
✓ Importar BRCars Dataset
  └─ Estruturar tabela: (marca, modelo, ano, cor) → imagens
  
✓ Importar gpupo/brazilian-cars
  └─ Usar como lookup de validação de candidatos
  
✓ Fine-tuning YOLOv8 com UFPR-VeSV
  └─ Melhorar detector em cenários de vigilância
  
✓ Integrar OpenCLIP
  └─ Semantic search em descrições textuais
  
Saída: Detector + OSINT database robusto em português/Brasil
```

### Fase 2: Refinamento (Semanas 3-4)
```
⚠ Avaliar VMMRdb para transfer learning
  └─ Se desempenho melhora, incorporar pré-treinamento
  
⚠ Integrar SAM para contexto espacial
  └─ Análise forense de posição de placa
  
⚠ Setup Roboflow para versionamento
  └─ Controle de modelos treinados
```

### Fase 3: Produção (Semanas 5+)
```
→ Monitorar desempenho em produção
→ Retraining semestral com novos dados de vigilância
→ Documentar performance por modelo/marcas
```

---

## 6. CHECKLIST DE AÇÕES IMEDIATAS

- [ ] **Solicitar/verificar acesso BRCars Dataset** (contato Webmotors ou repositório)
- [ ] **Clone gpupo/brazilian-cars** → integrar como lookup_table
- [ ] **Download UFPR-VeSV** → estruturar em formato YOLO
- [ ] **Criar pipeline de fine-tuning YOLOv8** com BRCars + UFPR-VeSV
- [ ] **Implementar OpenCLIP para semantic search** na camada OSINT
- [ ] **Documentar termos de uso** de cada dataset no README
- [ ] **Benchmark:** Testar desempenho novo vs anterior em dataset test real

---

## 7. CONCLUSÃO

**Recomendação Geral:**
✓ **Usar stack open source + datasets brasileiros**
- BRCars (database visual de modelos)
- gpupo/brazilian-cars (referência estruturada)
- UFPR-VeSV (treinamento em vigilância)
- YOLO (detection + classificação)
- OpenCLIP (semantic search)

**Evitar:**
✗ Plataformas proprietárias caras (AWS, Azure, Google, Sighthound)
✗ Dependências de APIs pagas (OpenAI Vision)

**Benefício:**
- 100% controle sobre dados + modelos
- Zero custo de inference em produção
- Customização para contexto brasileiro
- Conformidade LGPD (dados não enviados a terceiros)

---

**Próximo Passo:** Confirmar qual dataset você quer começar a integrar primeiro.
