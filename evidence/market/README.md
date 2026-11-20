# Evidência — dados de mercado (Fenabrave), Tela 1 / Visão de Mercado

Ambiente `classic_stable.auto_intelligence` (target `demo`), 2026-11-20. Tudo aqui é saída de consultas e
comandos só de leitura, gerada por `tests/market/` (`run_market_checks.sh`, `collect_run_evidence.sh`,
`collect_pipeline_evidence.sh`). Os nomes de marcas reais aparecem mascarados como `BRAND_<6 hex>`
(sha256 do nome, ADR D6); contagens, meses, ranks, unidades e shares são os reais.

## Resultado

| Verificação | Resultado | Arquivo |
|---|---|---|
| 13 checks + mascaramento | **14/14 PASS** | `summary.txt`, `checks/*.txt` |
| Totais da silver × oráculo independente (página 1 dos PDFs, `pdftotext`) | **570/570 exatos** (285 meses × 2 segmentos; inclui os 5 meses de OCR) | `reconciliation.md` |
| Gold de marcas (com residual) × total publicado | **570/570 exatos** | `reconciliation.md`, `checks/07_gold_brand_exact.txt` |
| Cobertura 2003-01 a 2026-09 | **285/285 meses**, 0 lacunas, 0 documentos sem mês | `coverage.txt` |
| Aurora Motors isolada por `is_synthetic` | 0 linhas sintéticas nas tabelas reais e na view real; total real idêntico com e sem Aurora | `synthetic-isolation.txt`, `checks/08*`, `checks/09*` |
| Reexecução do job (run 2) | **PASS**: 0 downloads, `has_new_files=false`, tarefa do pipeline pulada, snapshots idênticos | `job-run2.txt`, `idempotency-job-run2.txt` |
| Update do pipeline sem mudanças (update 7) | **PASS**: bronze sem nova versão (v3), contagens e *fingerprints* xxhash64 idênticos em todas as tabelas | `idempotency-pipeline-update7.txt` |
| Agenda do job | `PAUSED` (execuções manuais) | `job-schedule.txt` |
| Expectations do pipeline | 0 falhas, exceto `brand_matched` (informativa: 615 linhas de modelo com marca não reconhecida, listadas em `quality.txt`) | `pipeline-run.txt` |

## Linha do tempo (UTC)

1. **Job run 1** (`941856964050794`, 13:36): download de 285 PDFs (277 do histórico + 8 novos, 2026-02 a 2026-09;
   22 URLs candidatas sem arquivo). A tarefa do pipeline **falhou** (UDF do parser não desserializava nos executores);
   as atualizações automáticas seguintes também falharam (`pipeline-run.txt`, primeiro erro de cada uma).
2. **Update 9ff1e300** (14:24): pipeline materializado após a correção do parser. A suíte encontrou um defeito real:
   uma marca composta publicada como "X/Y" era dividida em "/" e somada a outra marca em 34 meses de comerciais leves.
3. **Update 70a3fcd7** (14:32): correção das marcas com "/". A suíte encontrou um segundo defeito: em 4 edições de
   maio o cabeçalho "Maí" (OCR) fazia o parser descartar a tabela de modelos de um segmento.
4. **Job run 2** (`474836116913433`, 14:42): reexecução sem novos arquivos (prova de idempotência do job).
5. **Update 6c4146f3** (14:43): correção dos cabeçalhos de maio (+193 linhas de modelo).
6. **Updates 5145a05c e a9f8064f** (14:51 e 14:55): updates sem mudança; S6 × S7 prova a idempotência do pipeline.

## Arquivos

- `checks/NN_*.txt`: cada check com a afirmação, o SQL e as violações (0 linhas = PASS).
- `reconciliation.md`: mês a mês, total do PDF × pipeline.
- `coverage.txt`, `manifest.txt`, `quality.txt`, `row-counts.txt`, `synthetic-isolation.txt`: relatórios informativos.
- `job-run1.txt`, `job-run2.txt`, `job-schedule.txt`, `pipeline-run.txt`: execuções do job e do pipeline.
- `snapshots/*.txt`: estado das tabelas, do manifesto, da bronze e do Volume em cada passo; os pares
  comparados estão em `idempotency-*.txt`.
