# Auto Intelligence Demo (Aurora Motors): plano por tela

Base: demo automotiva anterior (JS puro + Express, 4 telas, PAT fixo no `app.yaml`), usada só como referência funcional.
Workspace: profile `classic-stable-new` (`adb-7405606279083366.6.azuredatabricks.net`).
Usos: (1) submissão FEBAR, (2) demo reutilizável para clientes.

## Decisões tomadas
- Marca **fictícia Aurora Motors**, assistente **Lumi**, manual **sintético** do modelo fictício (nada de material do cliente original)
- Visão de Mercado: dados públicos Fenabrave de todas as marcas + Aurora Motors com share simulado (documentado como sintético)
- Stack: AppKit (React + TS) + Declarative Automation Bundle; app autenticado por **service principal** (sem PAT)
- O KA será substituído (não é mais uma solução suportada)
- Avançar passo a passo; a Leticia decide cada etapa

## Problema de negócio (proposta para o FEBAR)
> **Ruptura de peças no pós-venda das concessionárias Aurora Motors**: falta peça no balcão e o carro fica parado
> na oficina, enquanto outra loja tem excesso de estoque. A demo prevê a demanda por loja e peça,
> antecipa o risco de ruptura, sugere a reposição e conecta a oficina ao motorista (alertas + manual).
KPIs do comprador: fill rate de peças, vendas perdidas (R$), dias de estoque e tempo de veículo parado.

## Mapa de critérios do FEBAR → onde cada um aparece
| Critério | Onde |
|---|---|
| Lakeflow (ingestão do dado bruto) | Pipeline SDP: PDFs Fenabrave (público) + CSVs sintéticos (vendas, estoque, alertas) via Auto Loader |
| Unity Catalog (governança) | Catálogo/schema dedicados, tags, comentários, lineage, grants para o SP do app, (opcional) column mask |
| Lakebase (serving operacional) | Synced tables de forecast/estoque para o app + escrita de pedidos de reposição e histórico do Lumi |
| ML ou GenAI | Forecast de demanda de peças (MLflow) + Lumi (RAG do manual sintético com imagens) |
| Genie Agent | Agent sobre as tabelas gold (mercado + pós-venda), embutido no app via API |
| Databricks App | AppKit com as 4 telas, autenticado por service principal |
| Evidência em texto | Notebooks commitados com outputs, logs dos jobs, `evidence/` com resultados de queries, métricas e respostas do agente |
| Deck | `deck/`: resultado de negócio primeiro, KPIs quantificados, visão do sponsor e do dono do domínio |

## Marca e repositório público (resolvido)
- Demo inteira com a marca fictícia Aurora Motors; nenhum material do cliente original no repositório.
- O primeiro commit (be51c88) ainda cita o cliente original: o repositório público será publicado com histórico novo.

---

## Tela 0: Fundação (pré-requisito de todas)
Hoje: Express + `index.html`, PAT no `app.yaml`, SQL seeds manuais, schema em outro workspace.
Muda:
- [x] Schema `classic_stable.auto_intelligence` (decidido: 1 schema, tabelas prefixadas market_/aftersales_/driver_) + volumes
- [x] Bundle (`databricks.yml`) com targets `dev`/`demo`; `deploy.sh` ponta a ponta
- [x] Scaffold AppKit, shell com navegação, tema Aurora Motors via `brand.config`
- [x] SP automático do App (decidido) com grants mínimos (warehouse, schema, depois endpoints/Lakebase)
- [x] Pasta `evidence/` + convenção de salvar outputs
Decisões tomadas: catálogo classic_stable; marca fictícia Aurora Motors (sem overlay); pronto = deploy real + smoke test + evidence/

## Tela 1: Visão de Mercado
Hoje: iframe de um dashboard AI/BI.
Muda:
- [x] Ingestão Fenabrave (PDFs públicos) via Lakeflow → bronze/silver/gold de emplacamentos por marca, modelo, segmento e mês (job `market_monthly` + pipeline SDP; Aurora sintética somada por cima)
- [x] Tela nativa `/mercado`: KPIs, série histórica com share da Aurora, ranking de marcas (Aurora fixa), top modelos, filtros (segmento, período, visão, mês)
- [ ] (opcional) manter um dashboard AI/BI publicado como artefato extra
Decisões tomadas: gráficos nativos (AppKit); cortes por segmento, período, visão real/com Aurora e mês

## Tela 2: Pós-venda (Forecast de peças)
Hoje: forecast estático (tabelas seed), filtros, tabela e gráfico por loja e por produto.
Muda:
- [x] Dados 100% sintéticos de concessionárias, peças, frota (a partir dos emplacamentos da Aurora), vendas e estoque (os CSVs antigos não são usados: contêm dados de marca real)
- [x] **ML**: job de forecast por loja × peça, registrado no MLflow/UC, com picos sazonais
- [x] Risco de ruptura = forecast × estoque → recomendação de reposição/transferência entre lojas
- [x] **Lakebase** (projeto `auto-intelligence-aftersales`): synced tables SNAPSHOT `aftersales_lb_*` no catálogo existente (sem CREATE CATALOG) + tabela OLTP de pedidos de reposição (escrita pelo app)
- [x] Tela: filtros, forecast × realizado, ranking de risco e botão "solicitar reposição"
Decisões tomadas (ADR `docs/architecture/aftersales.md`): forecast semanal concessionária × peça com HistGradientBoosting, holdout de 13 semanas, WAPE vs. sazonal-ingênuo de 52 semanas (gate @champion < 0,95 × baseline); escrita = pedidos de reposição/transferência

## Tela 3: Visão do Motorista + Lumi (REMOVIDA do app em 2026-11-20 a pedido da Leticia)
Hoje: busca por veículo/CEP, alertas de clima, via e manutenção, chat do assistente via KA.
Muda:
- [ ] Alertas vindos das tabelas gold (clima e via por CEP + manutenção prevista)
- [ ] **Substituir o KA**: agente RAG próprio (parse do manual com `ai_parse_document`, Vector Search
      com busca híbrida, rerank, retorno de figuras), servido via Model Serving e avaliado com MLflow
- [ ] Histórico de conversas no Lakebase
- [ ] Tela: card do veículo, alertas, chat Lumi com as figuras do manual
Decisões: arquitetura do agente substituto; LLM; o que reaproveitar do notebook de RAG anterior; geração dos manuais sintéticos

## Tela 4: Genie
Hoje: iframe (frágil, X-Frame-Options).
Muda:
- [x] Genie Agent "Aurora Motors · Mercado automotivo" sobre as gold de mercado (space 01f1e51fb8bb1e7d93d9f4b25aab7517), com descrições, instruções, exemplos e benchmarks (5/5)
- [x] Tela Genie nativa (plugin genie do AppKit + useGenieChat): resposta, SQL gerado e tabela; perguntas sugeridas
Decisões: escopo de tabelas; perguntas de exemplo

## Tela 5: Benefícios / narrativa (popup atual)
- [ ] Revisar o conteúdo para alinhar com os KPIs do deck

## Entregáveis FEBAR
- [ ] Repositório público no GitHub (sem dados de cliente)
- [ ] `evidence/` com os outputs em texto
- [ ] Deck em PDF/MD
- [ ] ID da conversa (opcional)

## Revisão
### Tela 2, Pós-venda (2026-11-20): concluída
- Job `aftersales_daily` (PAUSADO) verde e idempotente; forecast @champion v4 WAPE 20,0% vs 30,1%; risco 2160 linhas validadas; Lakebase 5 synced tables + pedidos OLTP; tela `/pos-venda` local. Evidência `evidence/aftersales/`.
- Pendências: F1 (deploy do app com Lakebase), F4 (janela anterior), F7 (tags nas synced tables).

### Tela 1, tela (2026-11-20): concluída
- `/mercado` local, API = gold (1411/1411), UI = SQL em 5 meses, 37 testes; evidência `evidence/app-market/`. Sem deploy.

### Tela 1, dados (2026-11-20): concluída
- 285 meses (2003-01..2026-09), reconciliação exata 570/570, 14/14 checagens, job e pipeline idempotentes; agenda PAUSADA.
- Evidência: `evidence/market/`; arquitetura: `docs/architecture/market-ingestion.md`; modelo: `docs/data-model/market.md`.
- Pendências: despausar agenda (F1), medir custo do backfill (F5), publicar com histórico novo (F6); tela da Visão de Mercado.

### Tela 0 (2026-11-20): concluída
- App `auto-intelligence` no ar; `/api/health` consulta o UC como o SP do app; `deploy.sh` idempotente; grants mínimos (incluindo CAN_USE explícito no warehouse).
- Evidência em texto: `evidence/foundation/` (11 arquivos).
- Pendências: validação visual só local (sem SSO no Chrome separado); remover a lista de palavras da marca antiga dos scripts de checagem antes de publicar; publicar com histórico novo.
