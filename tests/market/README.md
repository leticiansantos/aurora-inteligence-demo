# Suíte de validação dos dados de mercado (Fenabrave)

Verifica, só com leituras (`SELECT`), as tabelas `market_*` descritas no ADR
`docs/architecture/market-ingestion.md` (contratos da seção 4) e grava evidência em texto em `evidence/market/`.

| Peça | O que faz |
|---|---|
| `oracle/` | Oráculo independente: totais da página 1 de cada PDF (Autos e Com. Leves), extraídos com `pdftotext`, sem o parser em teste. `pdf_totals_visual_override.csv` guarda os 5 PDFs sem camada de texto (2020-04/05/06, 2023-09, 2024-01), lidos à mão. |
| `sql/NN_*.sql` | Consultas de violação: 0 linhas = PASS. Cobertura de meses, chaves únicas, nulos, residual 0–3%, gold = total publicado (exato), isolamento da Aurora (`is_synthetic`), views real × com Aurora, documentos por mês. |
| `reconcile.py` | Compara totais por mês × segmento do pipeline com o oráculo (exato; os 5 meses de OCR só entram no relatório). |
| `run_market_checks.sh` | Roda tudo e grava `checks/`, `reconciliation.md`, `coverage.txt`, `manifest.txt`, `synthetic-isolation.txt`, `quality.txt`, `row-counts.txt` e `summary.txt`. Também tira *snapshots* e compara dois deles (idempotência). |
| `collect_run_evidence.sh` | Evidência de uma execução do job: estados das tarefas, resultado de `has_new_files`, update do pipeline, expectations e agenda `PAUSED`. |
| `fixtures/run_fixture_checks.py` | Prova as consultas sem tabelas reais: substitui cada tabela por `VALUES` (dados limpos → 0 linhas; defeitos semeados → ≥ 1 linha). |

## Como rodar

```bash
# checks + reconciliação (target demo; dev usa auto_intelligence_dev)
tests/market/run_market_checks.sh classic-stable-new demo

# idempotência: snapshot antes e depois do 2º run manual do job, depois o diff
tests/market/run_market_checks.sh classic-stable-new demo snapshot before
tests/market/run_market_checks.sh classic-stable-new demo snapshot after
tests/market/run_market_checks.sh classic-stable-new demo diff before after

# evidência de cada execução do job (run1 = primeira carga, run2 = reexecução)
tests/market/collect_run_evidence.sh classic-stable-new <job_run_id> run1

# testes das próprias consultas (só SELECT com dados inline)
python3 -I tests/market/fixtures/run_fixture_checks.py

# regenerar o oráculo a partir dos PDFs locais
python3 -I tests/market/oracle/extract_pdf_totals.py <pasta_dos_pdfs> tests/market/oracle/pdf_totals.csv
```

As listas permitidas espelham a configuração do pipeline: `MARKET_KNOWN_MISSING_MONTHS` (padrão: vazia) e
`MARKET_KNOWN_NO_BRAND_TABLE_MONTHS` (padrão: `2004-01-01`). `MARKET_OCR_MONTHS` define os meses cuja
reconciliação é só relatório.
