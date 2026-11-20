# ADR 002: Pós-venda (Tela 2): ruptura de peças com forecast (ML) e serving operacional (Lakebase)

- **Status:** ACEITO (T1) e IMPLEMENTADO (T7, 2026-11-20; resultado na seção 9). Os contratos estão **congelados** em
  [`docs/data-model/aftersales.md`](../data-model/aftersales.md) (v1). Qualquer mudança de nome, tipo ou PK passa
  pelo tech lead `pos1-tech-lead`.
- **Escopo:** dados sintéticos de pós-venda → pipeline SDP → forecast (MLflow + UC model) → risco de ruptura e
  recomendação → Lakebase (synced tables + tabela OLTP de pedidos) → tela `/pos-venda`. Fora do escopo: redeploy
  do app (a validação é local), Genie e Lumi.
- **Critérios FEBAR desta run:** **Lakebase (serving operacional)** e **ML (forecast)**, integrados ao Lakeflow,
  ao UC e ao app que já existem.
- **Evidência usada** (run `.team/runs/2026-11-20-pos1/`), em spikes só de leitura de 2026-11-20:
  - Perfil da origem: `market_synthetic_registrations` tem 279 linhas, só AURORA MOTORS/automóveis, modelos IPE
    (171.545), JATOBA (132.608) e AROEIRA (76.105), de 2019-01 a 2026-09, sem nenhuma coluna geográfica. As tags
    de UC estão vazias no schema inteiro.
  - Spike de Lakebase: `databricks postgres list-projects` lista só `canvas-ideacao`, que não tem relação com
    esta run. `list-database-instances` devolve `[]`. O `bundle schema` do CLI v1.24 tem as chaves
    `postgres_projects`, `postgres_synced_tables`, `postgres_catalogs` e `postgres_snapshot_schedules`. A skill
    databricks-lakebase avisa que as synced tables via DAB ainda não são suportadas.
  - Survey do repo: os padrões de `resources/market_*.yml`, de `app/server/market/*` e do ADR 001.
  - Rascunho do contrato da API do backend (`app/shared/aftersales.ts`, a4a4df9).
- **Quem decidiu:** todas as escolhas de julgamento abaixo foram **decididas com a opção recomendada pelo tech lead, que a Leticia pré-aprovou** para esta run.
- **Substitui:** o item de `tasks/todo.md` (Tela 2) que diz "reaproveitar `pecas.csv`, `lojas.csv`,
  `estoque.csv`" está **superado**. Essas CSVs têm dados de marca e de concessionárias reais e **não** podem ser
  usadas, nem como base. O QA faz uma checagem de vazamento contra elas.

## 1. Requisitos

| # | Requisito |
|---|---|
| R1 | Dado 100% sintético: lojas fictícias (cidades reais são permitidas), peças genéricas, nenhuma marca ou código real |
| R2 | Frota da Aurora derivada da Tela 1 (`market_synthetic_registrations`), o que torna a integração visível no lineage do UC |
| R3 | Medalhão SDP no bundle raiz, tabelas `aftersales_*` com comentário e tags de UC (`synthetic=true`, `aid_domain=aftersales`) |
| R4 | Forecast honesto: backtest em holdout posterior ao corte, comparado com um baseline, MLflow + UC model com alias `@champion` |
| R5 | Risco de ruptura e recomendação (reposição × transferência entre lojas) como regras determinísticas e testáveis por oráculo SQL |
| R6 | Lakebase: synced tables para leitura do app e uma tabela OLTP de pedidos escrita pelo app, com o SP do app em menor privilégio |
| R7 | Orquestração automatizável de ponta a ponta: job `generate → pipeline → train → score → govern → sync` |
| R8 | Evidência em TEXTO em `evidence/aftersales/`, mais o notebook de treino commitado com os outputs |

## 2. Visão geral

```
job aftersales_daily (agenda PAUSADA, max_concurrent_runs 1, serverless)
  generate ─▶ pipeline ─▶ train ─▶ score ─▶ govern ─▶ sync
  │            │           │        │        │         └─ refresh SNAPSHOT das 5 synced tables (Lakebase)
  │            │           │        │        └─ SET TAGS em todas as aftersales_* (idempotente)
  │            │           │        └─ aftersales_forecast_weekly, aftersales_stockout_risk (@champion)
  │            │           └─ backtest + baseline, registro UC, gate do @champion, aftersales_model_metrics
  │            └─ SDP: raw (Auto Loader) → silver → gold, + frota a partir de market_synthetic_registrations
  └─ CSV determinísticos → /Volumes/.../raw_landing/aftersales/
App /pos-venda (AppKit) ─▶ Lakebase: SELECT em auto_intelligence.aftersales_lb_*, INSERT em aftersales_app.aftersales_replenishment_requests
```

## 3. Decisões

### D1. Domínio sintético: gerador Python determinístico que grava CSV no Volume
- O gerador fica em `src/aftersales/synthetic/` e é uma tarefa `spark_python_task` do job, com código
  sincronizado pelo bundle (fato: Volume não serve como `python_file`). A tarefa lê
  `market_synthetic_registrations` com Spark e passa a frota a um núcleo **puro** em Python, que é testável sem
  Spark.
- **Lojas:** 12 (`D001`..`D012`) em 4 regiões, com pelo menos 2 lojas por região para que a transferência seja
  possível. O nome segue o formato "Aurora Motors <Cidade>", e as cidades são brasileiras reais. O
  `fleet_share` é fixo por loja e soma 1.
- **Peças:** 60 (`P001`..`P060`) em 8 categorias (seção 2 do modelo de dados), com nomes genéricos em pt-BR, como
  "Pastilha de freio dianteira". O preço e o custo são inventados, e `is_critical` marca as peças que imobilizam o
  veículo.
- **Demanda diária** por loja × peça: o processo de Poisson com sobredispersão (binomial negativa) tem taxa =
  frota ativa da loja × taxa de desgaste da peça × fator de idade da frota × sazonalidade da categoria × fator do
  dia da semana. A sazonalidade da categoria é, por exemplo: freios e iluminação sobem na estação de chuva
  (dez–mar), o ar-condicionado sobe no verão, a bateria e o elétrico sobem no inverno (jun–jul), e a revisão tem
  picos em jan/jul. O fator do dia da semana zera o domingo e reduz o sábado.
- **Estoque:** a simulação diária usa uma política (s, S) com parâmetros **imperfeitos** por loja. Algumas lojas
  ficam subdimensionadas e outras sobre-estocadas, o que gera ruptura real (`lost_units`) e excesso transferível.
  O lead time de fornecedor fica entre 3 e 30 dias, e as peças críticas, que são importadas, têm o lead time mais
  longo.
- **Metas de plausibilidade** em `forecast_date` com `horizon_days=28`, que o QA verifica:
  - critical + high entre 3% e 12% das 720 combinações. **Meta revisada para 3% a 15%** em 2026-11-20 (decidido,
    recomendado, pré-aprovado). Com o forecast real (v3) e o evento de baixa de estoque de 2026-11-15, o resultado
    foi **14,2%** (102/720, oráculo do QA). Os dois caminhos eram regenerar os dados e retreinar, ou registrar o
    desvio. Escolhemos registrar: a meta de 12% era um julgamento do tech lead, e não uma regra de negócio, e 14%
    das peças em risco em 4 semanas, numa rede com uma baixa de inventário, ainda é plausível. O valor medido e a
    revisão ficam registrados aqui, sem esconder o desvio;
  - pelo menos 5 linhas `critical` (o proxy local do data-eng tinha 0 `critical`, e a tela perderia o nível mais
    importante);
  - pelo menos 10 recomendações `transfer`;
  - fill rate das últimas 4 semanas entre 0,88 e 0,97;
  - os picos sazonais visíveis na série semanal.
- **Idempotência:** com o mesmo `seed` e a mesma `generator_version`, os arquivos saem idênticos byte a byte e
  com os mesmos nomes, e o gerador **sobrescreve** os arquivos em vez de acrescentar linhas. O Auto Loader ignora
  arquivo reescrito com o mesmo nome (`cloudFiles.allowOverwrites=false`, que é o padrão), e por isso o rerun
  não duplica nada. Uma mudança de `generator_version` exige o *full refresh* do pipeline, e isso fica
  documentado no README do gerador.
- Alternativas rejeitadas:
  - *Reaproveitar `pecas/lojas/estoque.csv`*: têm dados reais, o que é proibido.
  - *Gerar dentro do pipeline, como na Aurora de mercado (D4 do ADR 001)*: a simulação de estoque é
    sequencial no tempo (o estado de um dia depende do anterior) e não se encaixa bem em MV. Além disso, perderia
    o passo de "ingestão de arquivo bruto" via Auto Loader, que é o que o critério Lakeflow mostra.
  - *Faker/dbldatagen*: dependência nova sem ganho, já que os nomes são poucos e fixos.

### D2. Calendário e granularidade: semanal por loja × peça
- Vendas diárias de 2019-01-01 a **2026-11-15** (domingo). `forecast_date` = **2026-11-16**.
- O registro de frota termina em 2026-09. Outubro e novembro de 2026 usam a frota de 2026-09 congelada, sem
  extrapolar registros.
- O forecast, o backtest e o risco usam a semana (de segunda a domingo) por `dealer_id × part_id`, o que dá 720
  séries.
- **Horizontes da tela:** 14, 28 e 56 dias, que equivalem a H = 2, 4 e 8 semanas. O padrão é **28**. O forecast
  futuro sempre vai até h = 8.
- Alternativas rejeitadas:
  - *Diário*: a demanda de peça por dia é intermitente (com muitos zeros), e o WAPE diário fica ruidoso e pouco
    honesto.
  - *Horizontes 7/14/28* (o rascunho do backend): 7 dias é menor que a maioria dos lead times, então não cabe
    nenhuma ação. Além disso, 7 não é múltiplo da granularidade semanal útil.

### D3. Forecast: modelo global de gradient boosting (estratégia direta) contra o seasonal-naive
- Um único `sklearn.ensemble.HistGradientBoostingRegressor` (que já vem no ambiente serverless, sem dependência
  nova), com `random_state` fixo.
- **Estratégia direta:** cada linha é (origem t, horizonte h ∈ 1..13), e o alvo é a demanda em t + h.
- **Features** (somente informação ≤ t; implementação em `src/aftersales/ml/forecast.py`):
  - as 4 últimas semanas, `y_0`..`y_3`;
  - médias móveis de 4, 13 e 52 semanas até t;
  - lags sazonais **alinhados ao alvo**, `y(t+h−52)` e `y(t+h−52±1)`. Para h ≤ 13, eles são sempre ≤ t;
  - semana do ano e mês do alvo;
  - h;
  - frota ativa da loja na semana de origem;
  - categoria, criticidade e região (códigos determinísticos).
  - O treino usa origens com passo de 2 semanas, no máximo 156 por horizonte, para limitar a memória.
- **Backtest:** treina com as origens ≤ **2026-08-16** (o corte) e prevê as 13 semanas do holdout
  (2026-08-17 a 2026-11-15) a partir do corte. O treino nunca vê alvo posterior ao corte. Um teste unitário
  confirma que alterar o futuro não muda a previsão.
- **Métrica:** WAPE = `Σ|y − ŷ| / Σy` sobre todas as séries × semanas do holdout. A run também registra o bias.
- **Baseline:** seasonal-naive com estação de 52 semanas (`ŷ(t+h) = y(t+h−52)`).
- **Rerun do `train`:** cada execução registra uma versão nova. Uma versão que ficou de um `train` interrompido,
  sem métricas e sem alias, não é reaproveitada: permanece órfã e não aparece em `aftersales_model_metrics`.
  As versões 1 e 2 do run 2 são esse caso.
- **Gate do `@champion`:** WAPE do modelo < **0,95 ×** WAPE do baseline (o modelo precisa ganhar por pelo menos
  5%). Se o modelo passa, ele é **refeito com todo o histórico**, registrado como
  `classic_stable.auto_intelligence.aftersales_demand_forecaster`, e o alias `@champion` passa para a nova versão.
  Se perde, a versão é registrada **sem** alias, a tarefa `train` falha com uma mensagem clara e o `@champion`
  anterior continua valendo. O `score` sempre usa `models:/...@champion` para as semanas futuras. As linhas do holdout vêm do modelo do
  backtest, que é treinado só até o corte e não é registrado. Elas levam o **mesmo** `model_version` N da versão
  registrada pelo procedimento, para que exista uma única chave de join.
  `aftersales_model_metrics.wape` da versão N é o WAPE do backtest desse procedimento, recalculável a partir das
  linhas do holdout.
- **Exógenas sem vazamento:** a frota ativa entra no valor do mês da origem t, nunca do mês do alvo. Nas origens
  posteriores a 2026-09, ela fica congelada em 2026-09.
- **Incerteza:** `σ` da série = `max(RMSE do holdout, 0,5)` unidades por semana. O intervalo de 80% é
  `forecast ± 1,2816·σ`, truncado em 0.
- **MLflow:** o experimento é um recurso DAB, `/Shared/auto-intelligence-demo/aftersales_demand_forecast_${bundle.target}`.
  A run registra os parâmetros, os WAPE (modelo e baseline), o bias, o WAPE por categoria e uma assinatura.
- **Reprodutibilidade:** com a mesma versão do modelo e os mesmos dados, `aftersales_forecast_weekly` sai idêntica
  (fora `scored_at`).
- Alternativas rejeitadas:
  - *Prophet/ARIMA por série*: 720 ajustes, dependências novas e fracos em séries intermitentes.
  - *`ai_forecast`*: não gera um modelo registrado no UC/MLflow e não passa pelo critério ML.
  - *LightGBM*: pacote extra no ambiente sem ganho relevante em 720 séries.
  - *Estratégia recursiva*: o erro se acumula e o código fica mais complexo.

### D4. Saídas do ML: uma tabela de série para o gráfico e uma de risco para o ranking
- `aftersales_forecast_weekly` junta as 26 semanas reais, o backtest nas 13 últimas e as 8 semanas futuras. Com
  ela, o app desenha o "previsto × realizado" e recalcula o WAPE de qualquer seleção a partir de uma única tabela
  (o pedido do backend e do QA).
- `aftersales_model_metrics` traz o WAPE do modelo e do baseline por versão, para o selo de confiança da tela.
- O KPI `previous` é `null` nesta run, porque não guardamos snapshots de forecast anteriores.
- Alternativas rejeitadas: *tabelas separadas de forecast futuro e de backtest* (mais synced tables e mais joins
  no app sem ganho); *sincronizar `aftersales_demand_weekly` inteira* (≈296 mil linhas só para o gráfico).

### D5. Risco de ruptura e recomendação: fórmulas (oráculo do QA)
Para cada (loja d, peça p, horizonte `D` ∈ {14, 28, 56} dias, H = D/7 semanas), com `f_k` = `forecast_units` da
semana futura k e `L` = `lead_time_days`:

| Campo | Fórmula |
|---|---|
| `stock_units` | `on_hand_units` de `aftersales_stock_position` |
| `available_units` | `on_hand_units + on_order_units` (o pedido em trânsito é tratado como garantido) |
| `forecast_units` (μ) | `Σ_{k=1..H} f_k` |
| `forecast_sigma_units` | `σ · √H` |
| `safety_stock_units` | `1,65 · σ · √(L/7)` (nível de serviço de 95% sobre o lead time) |
| `days_of_stock` | `stock_units / (μ / D)`; nulo quando μ = 0 |
| `days_to_stockout` | o menor dia `n ∈ 1..56` em que `Σ_{i=1..n} f_{⌈i/7⌉}/7 > available_units`; nulo se não houver |
| `stockout_probability` | `1 − Φ((available − μ) / (σ√H))`. Quando σ√H = 0, vale 1 se μ > available e 0 caso contrário. `Φ` é a CDF normal padrão (`0,5·(1+erf(x/√2))`) |
| `shortfall_units` | `ceil(max(0, μ + safety_stock − available))` |
| `lost_sales_brl` | `max(0, μ − available) · unit_price_brl` (receita perdida se nada for feito) |
| `risk_level` | `critical` se `days_to_stockout ≤ min(D, L)` (a ruptura vem antes de uma compra feita hoje chegar); senão `high` se `days_to_stockout ≤ D`; senão `medium` se `shortfall_units > 0`; senão `low` |

**Regra numérica** (para o ML e o oráculo do QA darem o mesmo resultado):
- O consumo acumulado é calculado em forma fechada, sem somar dia a dia:
  `cum(n) = Σ_{k<w} f_k + (n − 7(w−1)) · f_w / 7`, com `w = ⌈n/7⌉`.
- Antes de qualquer comparação, `ceil` ou `floor` (`days_to_stockout`, `shortfall_units`, `excess`), o valor é
  arredondado para **6 casas decimais** (`round(x, 6)`).
- `μ` soma `f_k` na ordem k = 1..H.
- `Φ` usa `0,5·(1+erf(x/√2))`.

**Recomendação.** É independente por horizonte e greedy, com ordem determinística.
1. As linhas com `shortfall_units = 0` recebem `action='monitor'` e `recommended_qty=0`.
2. Os doadores são as lojas da **mesma região** com a mesma peça e o mesmo horizonte, e com
   `excess = min(on_hand_units, floor(available − μ − safety_stock)) > 0`. Só é possível transferir o que está em
   mão (revisão do QA). O doador nunca fica abaixo da própria demanda prevista
   somada ao estoque de segurança, ou seja, nunca vira `medium`.
3. As demais linhas são processadas em ordem de `lost_sales_brl` desc, `stockout_probability` desc, `dealer_id`
   asc e `part_id` asc. Em cada linha, entra o doador com o **maior excesso restante** (o desempate é pelo
   `dealer_id` asc).
   - Se esse excesso é ≥ `shortfall_units`, o resultado é `action='transfer'`, `recommended_qty=shortfall_units`,
     `transfer_from_dealer_id`=doador e `transfer_from_excess_units` = o excesso restante do doador **antes**
     desta alocação. O excesso restante do doador diminui em `shortfall_units`.
   - Caso contrário, o resultado é `action='reorder'` e `recommended_qty=shortfall_units`. Não existe
     transferência parcial: a ação sempre cobre o gap inteiro.
4. Não há MOQ nem embalagem, só arredondamento para cima ao inteiro.

**KPIs da tela** (sobre a seleção de loja, categoria e horizonte):
- `partsAtRisk` = nº de linhas com `risk_level ∈ {critical, high}`.
- `lostSalesAvoidedBrl` = `Σ lost_sales_brl` das linhas com `action ≠ 'monitor'`. O contrafactual é não fazer
  nada, e a ação recomendada cobre o gap inteiro.
- `fillRate` = `Σ sold_units / Σ actual_units` das 4 últimas semanas reais (2026-10-19 a 2026-11-15, ou seja, 28
  dias) em `aftersales_forecast_weekly`.
- `daysOfStock` = `Σ stock_units / (Σ forecast_units / D)`, a razão das somas ponderada pela demanda. É nulo
  quando `Σ forecast_units = 0`.
- Na tela, `stock_units` aparece como "estoque em mão", e `on_order_units` aparece ao lado, porque o nível de
  risco considera o pedido em trânsito.
- O ranking ordena por `lost_sales_brl` desc, depois `stockout_probability` desc, depois a chave `dealer_id:part_id` asc.

- Alternativas rejeitadas:
  - *Simulação de Monte Carlo da probabilidade*: não é reprodutível por SQL e fica cara.
  - *Transferência parcial combinada com compra*: duas ações por linha deixam a tela e o oráculo mais
    complexos.
  - *Distância entre cidades*: não há geografia na origem, e a região basta para a demo.

### D6. Lakebase: Autoscaling, um projeto dedicado, synced tables SNAPSHOT e OLTP próprio do app
- **Projeto** `auto-intelligence-aftersales` (Lakebase Autoscaling, Postgres 17, uid f551c63d), branch
  `production`, endpoint `primary` de leitura e escrita (ACTIVE) com 0,5 a 1 CU e suspensão após 300 s, e o banco
  `databricks_postgres`. O lead o **criou** em 2026-11-20 por volta das 17:15Z. O Provisioned foi descontinuado.
  O `canvas-ideacao` é de outra demo e não é reutilizado.
- **Restrição descoberta:** `create-catalog aftersales_lakebase` falhou com *"does not have CREATE CATALOG on
  Metastore"*. A usuária não é admin do metastore, então o design **não pode depender de um catálogo novo**.
- **Serving (somente leitura):** as 5 tabelas `auto_intelligence.aftersales_lb_{dealers, parts, forecast_weekly,
  stockout_risk, model_metrics}` no Postgres, que somam cerca de 27 mil linhas. A PK é igual à da origem.
  - **Plano A (ADOTADO, comprovado pelo probe de 2026-11-20):** o `aftersales_lb_probe` foi criado em SNAPSHOT no
    catálogo comum e chegou a `SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE` (pipeline d4634a74). Depois, foi apagado.
    Não é preciso catálogo novo. synced tables **SNAPSHOT** criadas pelo CLI (`postgres create-synced-table`) com o
    ID `classic_stable.auto_intelligence.aftersales_lb_<entidade>`, no catálogo comum, com `branch` e
    `postgres_database` explícitos no spec e os metadados da pipeline em `classic_stable.auto_intelligence`.
    - O SNAPSHOT dispensa CDF e combina com as tabelas de ML, que são reescritas inteiras a cada `score`.
    - O sufixo `_lb_` evita colisão de nome com a origem no mesmo schema do UC.
    - A doc da skill diz que o catálogo registrado é necessário, mas o spec aceita `branch` e `postgres_database`.
      Por isso, um **probe** decide (D8, passo 1b).
  - **Plano B (descartado, fica como contingência):** a tarefa `sync` do job lê as 5 tabelas Delta e grava no Postgres
    com `psycopg` mais o token OAuth do runtime (`generate-database-credential`).
    - Para cada tabela, numa só transação: `CREATE TABLE IF NOT EXISTS`, `TRUNCATE` e `COPY`.
    - O resultado é atômico para o leitor e idempotente.
    - A dependência `psycopg[binary]` fica só no ambiente do job.
    - Perde o recurso gerenciado "synced table", mas mantém o Lakebase como camada de serving operacional, que é o
      critério do FEBAR.
  - Nos dois planos, o **app lê os mesmos nomes** (schema e tabelas). O contrato do app não muda.
  - **Os scripts de CLI** (`scripts/lakebase/*.sh`, idempotentes, chamados pelo `deploy.sh`) cuidam da
    infraestrutura, e **não** um recurso DAB. Motivos:
    - O DAB ainda não suporta `postgres_synced_tables`.
    - `postgres_projects` no bundle, junto com o script, causaria criação dupla. Um deploy feito de outro branch
      **apagaria** o projeto.
    - Por isso, `resources/aftersales_lakebase.yml` **sai** do branch do backend.
- **Frescor:** a tarefa `sync` do job atualiza as 5 tabelas e espera a conclusão. No Plano A, ela chama
  `pipelines.start_update` na pipeline de cada synced table. No Plano B, ela mesma faz a cópia.
  - SLA: tudo concluído em até **30 min** após o `score`, com a contagem de linhas do Postgres igual à da origem
    e o mesmo `max(scored_at)`.
  - O app mostra `syncedAt`, que é o `max(scored_at)` da tabela de risco servida.
- **OLTP:** `aftersales_app.aftersales_replenishment_requests`. As colunas, os checks, o ciclo de status e o
  índice único parcial estão no modelo de dados.
  - A tabela é criada por uma **migração idempotente na inicialização do app** (`CREATE SCHEMA/TABLE/INDEX IF
    NOT EXISTS`), e o schema pertence ao role que a executa.
  - O nome do schema vem da env `AFTERSALES_APP_SCHEMA`, com padrão `aftersales_app`. **A validação local usa
    `aftersales_app_dev`**. Assim, o SP do app cria e é dono de `aftersales_app` no primeiro start deployado, e o
    usuário de desenvolvimento nunca toma posse do schema de produção (revisão do QA).
  - O duplo clique e o POST concorrente são resolvidos pelo índice único parcial (`23505` vira HTTP 409), sem
    checagem no app, que teria condição de corrida.
- **Menor privilégio do SP do app (o que o QA verifica):**
  - Lakebase: `CAN_CONNECT_AND_CREATE` no banco (o recurso do app), `USAGE` no schema `auto_intelligence` e
    `SELECT` nas 5 tabelas `aftersales_lb_*` (com `ALTER DEFAULT PRIVILEGES` para as futuras). Ele é dono só de
    `aftersales_app`. **Não** é membro de `databricks_superuser` e não tem nenhum privilégio de escrita em
    `auto_intelligence`.
  - Sem PII: `requested_by` grava `'app'` ou `'local-dev'`, nunca um e-mail.
  - No código, o app só emite `SELECT` e `INSERT`. Não há `UPDATE`, `DELETE` nem DDL fora da migração.
  - UC: nada muda, porque o SP já tem `SELECT` no nível do schema (`scripts/grant_app_sp.sh`).
- **Ambiente local:** `PGHOST`, `PGDATABASE`, `PGPORT=5432`, `PGSSLMODE=require` e `LAKEBASE_ENDPOINT`. O token
  OAuth vem do perfil `classic-stable-new`. O app reconecta quando o endpoint estava suspenso.
- Alternativas rejeitadas:
  - *TRIGGERED/CONTINUOUS*: exigem CDF, e CONTINUOUS deixa o compute sempre ligado, o que custa sem necessidade
    numa demo com um batch por dia.
  - *DDL da tabela OLTP feita pelo deployer e GRANT de INSERT/SELECT ao SP*: dá menos privilégio, mas exige psql
    na máquina e um passo manual para cada ambiente. Ficou registrada como follow-up.
  - *Ler o forecast pelo SQL warehouse*: não exercita o Lakebase.

### D7. Orquestração: um job `aftersales_daily` no bundle raiz
`resources/aftersales_job.yml` (dono: ML), serverless, agenda diária às 06:00 America/Sao_Paulo **PAUSADA**,
`max_concurrent_runs: 1` e parâmetros `catalog` e `schema` (padrão nas variáveis do bundle).

| Tarefa | Tipo | Código (dono) |
|---|---|---|
| `generate` | `spark_python_task` | `src/aftersales/synthetic/main.py` (data-eng) |
| `pipeline` | `pipeline_task` `${resources.pipelines.aftersales_pipeline.id}`, `full_refresh: false` | `src/aftersales/pipeline/**` (data-eng) |
| `train` | `spark_python_task` (ou notebook) | `src/aftersales/ml/train.py` (ml) |
| `score` | `spark_python_task` | `src/aftersales/ml/score.py` (ml): forecast + risco |
| `govern` | `spark_python_task` | `src/aftersales/governance/apply_tags.py` (data-eng): `SET TAGS` e comentários de coluna das tabelas de ML |
| `sync` | `spark_python_task` | `src/aftersales/serving/refresh_synced_tables.py` (backend): SDK `pipelines.start_update` nas pipelines das synced tables, com espera |

- Pipeline `aftersales_pipeline` (`resources/aftersales_pipeline.yml`, dono: data-eng): serverless,
  `root_path ../src/aftersales/pipeline` e configuração `aftersales.landing_path`.
  - Os fatos do ADR 001 valem aqui: nada de `spark.catalog` dentro das funções de dataset; UDF só a partir de um
    módulo registrado *by value*; nenhuma MV privada.
- O `deploy.sh` ganha os passos de Lakebase (o backend entrega os scripts, e o tech lead integra no fim):
  `create_project.sh` (antes) e `sync_tables.sh` (só no Plano A) mais `grant_app_sp.sh` (depois do primeiro `score`).
- Alternativas rejeitadas: *jobs separados para os dados e o ML*, porque exigiriam acoplamento por gatilho e
  deixariam o fluxo ponta a ponta menos legível.

### D8. Ordem dos passos no workspace (o tech lead encaminha cada um ao lead `workspace-b1`)
1. `scripts/lakebase/create_project.sh`: o projeto foi **criado** (2026-11-20, por volta das 17:15Z), mas o
   catálogo **falhou** por falta de CREATE CATALOG. O script deixa de registrar catálogo.
   - 1b. **Probe do Plano A:** `create-synced-table` de uma tabela de mercado pequena (279 linhas) no catálogo
     comum. O resultado decide entre o Plano A e o Plano B, e o probe é apagado em seguida.
2. Fazer o merge dos branches revisados num branch de integração e rodar `bundle validate --strict -t demo`.
3. Rodar `bundle deploy -t demo` só a partir do branch integrado, **nunca** de um branch isolado, e sem
   `bundle run app`.
4. Rodar `bundle run aftersales_daily` até o `score`. Na primeira execução, o `sync` falha porque as synced
   tables ainda não existem. Para evitar isso, o passo 5 roda antes do `sync` (o `sync` pula as tabelas
   inexistentes com um aviso).
5. Rodar `scripts/lakebase/sync_tables.sh` (cria as synced tables) e depois o reparo/rerun do `sync`.
6. **Fora desta run (decisão do lead, 2026-11-20):** o app **não** é redeployado nem tem a config alterada nesta run.
   O deploy desta run usa `resources/app.yml` igual ao da `main`. O trecho de Lakebase fica em
   `scripts/lakebase/app.lakebase.hunk.yml`, fora do glob do bundle, e entra só no follow-up F1 (seção 7).
7. Rerun do job inteiro, que serve de prova de idempotência (as contagens e os conteúdos precisam ficar
   estáveis).

### D9. Governança de UC
- Tags em **todas** as 16 tabelas Delta `aftersales_*` (as synced `aftersales_lb_*` ficam no follow-up F7):
  `synthetic=true`, `aid_domain=aftersales` e
  `layer ∈ {raw, silver, gold, ml}`. São aplicadas pela tarefa `govern`, de forma idempotente. As SDP não
  aplicam tags de UC, por isso esta tarefa existe.
- *Decidido (recomendado, pré-aprovado), em 2026-11-20 após o reparo do run 2:* a chave `domain` é uma **tag
  governada** nesta conta, com a lista de valores permitidos vazia. O UC rejeita `domain=aftersales` com
  `INVALID_PARAMETER_VALUE`. Por isso a chave passou a ser **`aid_domain`** (aid = auto-intelligence-demo).
  `synthetic` e `layer` são livres e continuam como estão. Isso vale para as tabelas, o UC model e as versões
  dele.
- `COMMENT` de tabela em todas as tabelas. As tabelas raw são isentas de comentário de coluna. `COMMENT` de
  coluna nas tabelas silver e gold (no schema da MV) e
  nas de ML (gravado pelo `govern`). Os comentários são em inglês e mencionam *synthetic*.
- O UC model `aftersales_demand_forecaster` recebe `synthetic=true`, `aid_domain=aftersales` e a descrição na
  tarefa **`train`**, a única dona do model. O `govern` cuida só das tabelas. O experimento MLflow fica em
  `/Shared`.

### D10. Plano de evidência (`evidence/aftersales/`, só texto)

| Pasta | Conteúdo | Dono |
|---|---|---|
| `data/` | manifesto, contagens, oráculo da frota (seção D1), metas de plausibilidade, checagem de vazamento contra as CSVs antigas | data-eng + QA |
| `pipeline/` | IDs dos updates, expectativas, rerun idempotente | data-eng + QA |
| `ml/` | WAPE × baseline, bias, versão e alias no UC, reprodutibilidade do score | ml + QA |
| `notebooks/` | o notebook de treino com os outputs | ml |
| `risk/` | o diff linha a linha do oráculo SQL contra `aftersales_stockout_risk` | QA |
| `lakebase/` | status das synced tables, contagens e `max(scored_at)` da origem contra a synced, grants do role do SP | backend + QA |
| `app/` | curl das APIs, a ida e volta do POST (a linha no Postgres e a UI), os 409 de concorrência, a checagem visual local | backend, frontend e QA |

## 4. Contratos congelados

Os contratos estão em [`docs/data-model/aftersales.md`](../data-model/aftersales.md): arquivos de entrada, tabelas,
PKs e a tabela OLTP. O contrato da API é `app/shared/aftersales.ts` (dono: backend) e precisa refletir este ADR:
- horizontes em dias: **14 / 28 / 56**, com padrão 28;
- `risk_level` com 4 níveis;
- `action` = `reorder` | `transfer` | `monitor`;
- o tipo do pedido em `type`, e a origem da transferência em `fromDealerId`;
- `lostSalesBrl` vem de `unit_price_brl` (receita), e **não** da margem;
- `fillRate` em 28 dias;
- `/forecast` com 26 semanas reais e 8 futuras, independente do horizonte.

## 5. Atribuições

| Task | Dono | Escopo exclusivo |
|---|---|---|
| T2 | pos1-data-eng | `src/aftersales/synthetic/**`, `src/aftersales/pipeline/**`, `src/aftersales/governance/**`, `resources/aftersales_pipeline.yml`, `tests/unit/aftersales_data/**` |
| T3 | pos1-ml | `src/aftersales/ml/**`, `resources/aftersales_job.yml`, `tests/unit/aftersales_ml/**`, `evidence/aftersales/notebooks/**` |
| T4 | pos1-backend | `src/aftersales/serving/**`, `scripts/**`, `resources/app.yml`, `app/server/**`, `app/shared/**`, `app/config/**` |
| T5 | pos1-frontend | `app/client/**` |
| T6 | pos1-qa | `tests/aftersales/**`, `evidence/aftersales/**` (exceto `notebooks/`) |
| T7 | pos1-tech-lead | revisão final, `deploy.sh` (integração dos passos de Lakebase), `docs/**` |

Interfaces: o job (T3) referencia o pipeline (T2) e os entrypoints de `govern` (T2) e `sync` (T4). Os nomes dos
arquivos acima são parte do contrato. Python local: cada dono cria a própria `.venv` (regra do projeto), e os
testes rodam com `python -m pytest` ou `unittest`, sem Spark.

## 6. Validação local desta run

- **Leituras:** o app local lê as tabelas **reais** `auto_intelligence.aftersales_lb_*` com o OAuth do usuário. É só
  leitura, e o dono continua sendo a pipeline de sync.
- **Escrita:** o app local grava em `aftersales_app_dev`, **nunca** em `aftersales_app`. Se o usuário criasse o
  schema de produção, ele viraria o dono, e o SP do app ficaria sem acesso depois do deploy (revisão do QA).
  Antes da ida e volta do QA, o schema `aftersales_app_dev` é truncado.

## 7. Follow-ups (deploy do app, quando a Leticia pedir)

- **F1. Deploy do app com Lakebase:**
  1. Aplicar o trecho `scripts/lakebase/app.lakebase.hunk.yml` (a env `LAKEBASE_ENDPOINT` e o recurso
     `postgres`) em `resources/app.yml`, seguindo `scripts/lakebase/README.md`, e rodar
     `./deploy.sh --profile classic-stable-new`. O passo `bundle run app` cria a deployment, e o SP recebe o role de
     Postgres com `CAN_CONNECT_AND_CREATE`.
  2. Abrir `/pos-venda` uma vez. A migração cria `aftersales_app`, que passa a pertencer ao SP.
  3. Rodar `bash scripts/lakebase/grant_app_sp.sh`, que dá `USAGE` e `SELECT` em `auto_intelligence.aftersales_lb_*`
     e define os default privileges.
  4. Verificar com SQL como dono do projeto:
     `select nspname, pg_get_userbyid(nspowner) from pg_namespace where nspname='aftersales_app';` e
     `select grantee, privilege_type, table_name from information_schema.role_table_grants where table_schema='auto_intelligence' and table_name like 'aftersales_lb_%';`.
  5. Fazer um POST de fumaça pela URL do app.
- **F2. Limpeza:** `drop schema aftersales_lb_dev cascade; drop schema aftersales_app_dev cascade; drop schema aftersales_app_qa_dev cascade;` depois do QA, e
  `drop table auto_intelligence.aftersales_lb_probe;` agora.
- **F3. (Opcional)** DDL da tabela OLTP feita pelo deployer e GRANT de INSERT/SELECT ao SP, para ter menos
  privilégio que `CAN_CONNECT_AND_CREATE`.
- **F4.** Valores `previous` dos KPIs: exige guardar o risco por `forecast_date` (tabela de histórico).
- **F5.** Ajustar o comentário de `syncedAt` em `app/shared/aftersales.ts` para "horário do score dos dados
  servidos" (é o `max(scored_at)`, como diz o D6).
- **F6.** Ranking em telas de 1200 px ou menos: a coluna de ação fica cortada (104 px). Falta indicar o scroll
  horizontal, ou fixar a coluna.
- **F7.** Tags e comentários de coluna nos 5 objetos de UC `aftersales_lb_*` (as synced tables), se o UC aceitar
  `SET TAGS` em online tables. Nesta run, o D9 vale para as 16 tabelas Delta. Os `aftersales_lb_*` são cópias
  gerenciadas pela pipeline de sync, e a origem delas tem tags (achado do QA, 2026-11-20).

## 8. Riscos

1. As metas de plausibilidade (D1) podem exigir ajuste dos parâmetros do gerador depois do primeiro run real.
   A mitigação é o QA verificar as metas antes da revisão final.
2. O gate pode reprovar o modelo, se a demanda sintética for previsível demais e o seasonal-naive ganhar. A
   mitigação é o ruído e as tendências de frota do gerador favorecerem um modelo com features. Se o gate
   reprovar, o resultado é reportado honestamente e não se força a promoção.
3. O role de Postgres do SP só existe depois do deploy do app com o recurso `postgres`, e esse deploy fica fora
   desta run. A mitigação é o follow-up F1, com comandos exatos e verificação.
4. O wake-up do endpoint depois da suspensão: o app faz retry de conexão.

## 9. Resultado da implementação (T7, 2026-11-20)

Código em `main`. Os runs do job `[demo] aftersales-daily` (id 59628329788041, agenda **PAUSADA**) foram três:
- 590689110157213: FAILED;
- 150449632535344: SUCCESS, depois de 5 reparos;
- 1069050395869220: SUCCESS, o rerun completo de idempotência.

Evidência em texto em `evidence/aftersales/`, e o relatório do QA está em
`.team/runs/2026-11-20-pos1/reports/qa.md` (T6 PASS).

| Critério | Resultado | Evidência |
|---|---|---|
| Dado sintético e sem vazamento | 0/176 códigos, 0/9 nomes de loja da demo antiga e 0/89 marcas reais em todas as tabelas | QA `data/` |
| Integração com a Tela 1 | Frota = registros da Aurora: 380.258 no total, por modelo, com erro ≤ 5e-10 | QA `data/sql-checks-data.txt` |
| Volumes | 2.070.720 vendas diárias, 295.200 linhas semanais, 720 posições de estoque | conferência do tech lead (SQL só de leitura) |
| Forecast honesto | WAPE **0,2004** contra o baseline seasonal-naive **0,3015** (33,5% de ganho; razão 0,665 < 0,95). Ganha nos 13/13 horizontes e nas 8/8 categorias. Holdout depois do corte, WAPE e bias recalculados das linhas | QA `ml/`, `evidence/aftersales/notebooks/` |
| UC model | `aftersales_demand_forecaster@champion` = **v4**. v1 e v2 são órfãs (D3). v3 e v4 têm WAPE idêntico (determinismo) | conferência do tech lead, QA |
| Risco e recomendação | O oráculo D5 independente bate com 2.160 × 17 campos e 0 divergências (em v3 e em v4). Em 28d: 13 critical, 89 high, 54 medium e 564 low; 133 transfer, 23 reorder e 564 monitor | QA `risk/`, conferência do tech lead |
| Meta D1 | fill rate de 4 semanas = 0,903 ✔; ≥5 critical ✔ (13); ≥10 transfers ✔ (133); critical+high = 14,2%, com **desvio aceito** (meta revisada para 3–15%) | QA |
| Governança | As 16 tabelas Delta têm `synthetic`, `aid_domain` e `layer`, mais comentários. As `aftersales_lb_*` ficaram para o F7 | `govern` "16/16", QA |
| Lakebase | 5 synced tables SNAPSHOT ONLINE. Contagens, somas, PKs e `max(scored_at)` iguais ao Delta antes e depois do rerun. O `sync` do job concluiu ×5 | QA `lakebase/` |
| OLTP | POST ↔ Postgres ↔ UI ok. 10 POSTs paralelos dão 1×201 e 9×409 (índice único parcial). Sem PII. Grava só em `aftersales_app_dev` (D8 passo 6) | QA `app/`, backend |
| Tela `/pos-venda` | Local, com as tabelas reais: KPIs = oráculo, gráfico desenhado, `/forecast` = Delta (0 divergências), console limpo | QA `app/ui-real-data.md` |
| Idempotência | Rerun completo: 16 tabelas Delta e 5 Postgres idênticas (fora as colunas de execução), landing idêntico byte a byte (194 arquivos), 0 linhas raw novas, `@champion` 3→4 | QA `pipeline/snapshots/` |
| App em produção | **Não** redeployado. A deployment ativa é de 2026-11-20 às 12:22Z, anterior a esta run | conferência do tech lead |

**Problemas encontrados no workspace e corrigidos** (todos registrados nas decisões acima):
1. Sem CREATE CATALOG no metastore: as synced tables usam o catálogo comum (D6, Plano A).
2. `__file__` indefinido no serverless: o `generate` usa o fallback de cwd, e o `train`/`score` recebem `--src`.
3. pandas do serverless mais antigo, sem `groupby.apply(include_groups=...)`: o WAPE por categoria passou a ser
   calculado com somas.
4. O registro de model no UC exigiu USE CATALOG explícito para a usuária (grant feito pelo lead).
5. A chave de tag `domain` é governada na conta: passou a ser `aid_domain` (D9).
6. `SHOW MODELS` não é Spark SQL válido aqui: o `govern` ficou só com as tabelas, e o `train` é o dono das tags do
   model.
7. Qualquer `sys.exit` (até `sys.exit(0)`) falha a tarefa, porque o IPython faz exec do arquivo: os entrypoints
   agora levantam exceção só em caso de erro.

**Pendências:** F1 (deploy do app com Lakebase e verificação do role do SP), F2 (limpeza dos schemas de
desenvolvimento, que o tech lead encaminhou), F3 a F7 (seção 7). As tags do UC model foram definidas pelo `train`
(`synthetic`, `aid_domain`), mas a leitura delas não foi confirmada pela API (o `registered-models get` não as
retorna).
