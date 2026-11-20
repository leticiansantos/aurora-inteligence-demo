# Genie Agent: transcrição dos benchmarks

- Space: `01f1e51fb8bb1e7d93d9f4b25aab7517` (Aurora Motors · Mercado automotivo), profile `classic-stable-new`.
- Gerado em 2026-11-20T20:30Z por `scripts/genie/ask_benchmarks.py` (Conversation API, só leitura), sobre a configuração de `scripts/genie/build_space.py`.
- Resultado: 5/5 perguntas COMPLETED. Os números batem com o SQL canônico de `scripts/genie/queries.sql`, validado à parte no warehouse.
- Nomes de marcas reais aparecem mascarados como `BRAND_<sha6>` (`scripts/genie/mask_brands.py`). AURORA MOTORS é a marca fictícia da demo.

```text
====================================================================================================
PERGUNTA: Como ficou a participação da Aurora Motors no segmento de carros no último ano, mês a mês?
STATUS: COMPLETED (16s)
SQL GERADO:
WITH `max_month_cte` AS (
  SELECT MAX(`ref_month`) AS `max_ref_month`
  FROM `classic_stable`.`auto_intelligence`.`market_share_with_aurora`
), `base` AS (
  SELECT
    `ref_month`,
    `share`,
    `units`
  FROM `classic_stable`.`auto_intelligence`.`market_share_with_aurora`
  CROSS JOIN `max_month_cte`
  WHERE `is_synthetic` = true
    AND `segment` = 'automoveis'
    AND `ref_month` BETWEEN add_months(`max_ref_month`, -11) AND `max_ref_month`
)
SELECT
  `ref_month`,
  ROUND(100 * `share`, 1) AS `share_pct`,
  `units`
FROM `base`
WHERE `ref_month` IS NOT NULL
ORDER BY `ref_month`
DESCRIÇÃO: Você quer ver a participação de mercado da Aurora Motors no segmento de automóveis, mês a mês, nos últimos 12 meses até o mês mais recente disponível.
RESULTADO (12 linhas): ref_month | share_pct | units
  2025-10-01 | 3.0 | 5961
  2025-11-01 | 3.1 | 5833
  2025-12-01 | 3.1 | 6776
  2026-01-01 | 3.2 | 4172
  2026-02-01 | 3.5 | 5088
  2026-03-01 | 3.5 | 7557
  2026-04-01 | 3.6 | 6936
  2026-05-01 | 3.6 | 8104
  2026-06-01 | 3.4 | 7564
  2026-07-01 | 3.3 | 7358
  2026-08-01 | 3.2 | 7118
  2026-09-01 | 3.0 | 6692
RESPOSTA: No período de **out/2025 a set/2026**, a participação da **Aurora Motors** no segmento de **automóveis** (marca fictícia com dados sintéticos) variou de **3,0% a 3,6%** mês a mês. Exemplos incluem:
- **out/2025:** **3,0%** (**5.961** unidades)
- **jan/2026:** **3,2%** (**4.172** unidades)
- **mar/2026:** **3,5%** (**7.557** unidades)
- **mai/2026:** **3,6%** (**8.104** unidades)
- **set/2026:** **3,0%** (**6.692** unidades)

Ao longo dos 12 meses, o share subiu gradualmente até **mai/2026** e depois recuou, encerrando **set/2026** no mesmo patamar de **out/2025**.
====================================================================================================
PERGUNTA: Ranking das 10 maiores marcas em emplacamentos no mês de setembro de 2026
STATUS: COMPLETED (15s)
SQL GERADO:
WITH brand_totals AS (
  SELECT
    `brand`,
    SUM(`units`) AS `units`
  FROM `classic_stable`.`auto_intelligence`.`market_share_real`
  WHERE `ref_month` = DATE'2026-09-01'
    AND `is_residual` = false
    AND `brand` IS NOT NULL
  GROUP BY `brand`
), ranked AS (
  SELECT
    `brand`,
    `units`,
    RANK() OVER (ORDER BY `units` DESC, `brand` ASC) AS `rank`
  FROM brand_totals
)
SELECT
  `rank`,
  `brand`,
  `units`
FROM ranked
WHERE `rank` <= 10
ORDER BY `rank` ASC, `brand` ASC;
DESCRIÇÃO: Você quer ver o ranking das 10 maiores marcas em emplacamentos no mês de setembro de 2026, considerando o mercado real e somando os segmentos de automóveis e comerciais leves, excluindo o volume residual.
RESULTADO (10 linhas): rank | brand | units
  1 | BRAND_38215b | 53586
  2 | BRAND_4c8e5b | 42372
  3 | BRAND_a66864 | 27526
  4 | BRAND_6e1d76 | 22218
  5 | BRAND_d6ab95 | 14907
  6 | BRAND_b1e3c4 | 13994
  7 | BRAND_af6c59 | 11947
  8 | BRAND_4a3dce | 10463
  9 | BRAND_d19014 | 9608
  10 | BRAND_d04bfe | 8964
RESPOSTA: No período de **setembro de 2026**, o ranking das 10 maiores marcas em emplacamentos no mercado total (automóveis + comerciais leves) foi:
- **1º BRAND_38215b**: **53.586**
- **2º BRAND_4c8e5b**: **42.372**
- **3º BRAND_a66864**: **27.526**
- **4º BRAND_6e1d76**: **22.218**
- **5º BRAND_d6ab95**: **14.907**

Entre as 10 marcas exibidas, a liderança da **BRAND_38215b** ficou **11.214** unidades à frente da **BRAND_4c8e5b**, e a **BRAND_d04bfe** fechou o top 10 com **8.964** emplacamentos.
====================================================================================================
PERGUNTA: Total anual de emplacamentos de comerciais leves entre 2019 e 2026
STATUS: COMPLETED (10s)
SQL GERADO:
SELECT YEAR(`ref_month`) AS `ano`, SUM(`units`) AS `units`
FROM `classic_stable`.`auto_intelligence`.`market_segment_totals`
WHERE `segment` = 'comerciais_leves'
  AND YEAR(`ref_month`) BETWEEN 2019 AND 2026
  AND `ref_month` IS NOT NULL
GROUP BY YEAR(`ref_month`)
ORDER BY `ano`
DESCRIÇÃO: Você quer ver o total anual de emplacamentos no segmento de comerciais leves entre os anos de 2019 e 2026.
RESULTADO (8 linhas): ano | units
  2019 | 397136
  2020 | 335300
  2021 | 416557
  2022 | 380021
  2023 | 458547
  2024 | 536649
  2025 | 552500
  2026 | 428233
RESPOSTA: Período usado: **2019 a 2026**. Exemplos dos totais anuais de emplacamentos de **comerciais leves** incluem:
- **2019:** **397.136**
- **2020:** **335.300**
- **2021:** **416.557**
- **2022:** **380.021**
- **2023:** **458.547**
Nos 8 anos retornados, o menor volume foi em **2020** (**335.300**) e o maior em **2025** (**552.500**).
====================================================================================================
PERGUNTA: Volume de cada modelo da Aurora Motors no ano de 2025
STATUS: COMPLETED (15s)
SQL GERADO:
SELECT `model`, SUM(`units`) AS `units`
FROM `classic_stable`.`auto_intelligence`.`market_model_monthly`
WHERE `brand` = 'AURORA MOTORS'
  AND `is_synthetic` = TRUE
  AND `ref_month` >= DATE'2025-01-01'
  AND `ref_month` < DATE'2026-01-01'
  AND `model` IS NOT NULL
GROUP BY `model`
ORDER BY `units` DESC, `model` ASC;
DESCRIÇÃO: Você quer ver o volume total de emplacamentos para cada modelo da marca Aurora Motors no ano de 2025.
RESULTADO (3 linhas): model | units
  IPE | 31130
  JATOBA | 23674
  AROEIRA | 13424
RESPOSTA: Em **2025**, a Aurora Motors (marca fictícia com dados sintéticos) teve volume em **3 modelos**. **IPE** liderou com **31.130** unidades, seguido por **JATOBA** com **23.674** e **AROEIRA** com **13.424**; o **IPE** vendeu mais que o dobro do **AROEIRA** no ano.
====================================================================================================
PERGUNTA: Top 10 marcas de automóveis por crescimento em unidades, acumulado jan-set 2026 vs jan-set 2025
STATUS: COMPLETED (16s)
SQL GERADO:
WITH `ytd` AS (
  SELECT
    `brand`,
    SUM(CASE WHEN YEAR(`ref_month`) = 2025 THEN `units` ELSE 0 END) AS `units_2025_jan_sep`,
    SUM(CASE WHEN YEAR(`ref_month`) = 2026 THEN `units` ELSE 0 END) AS `units_2026_jan_sep`
  FROM `classic_stable`.`auto_intelligence`.`market_share_real`
  WHERE `segment` = 'automoveis'
    AND `is_residual` = false
    AND YEAR(`ref_month`) IN (2025, 2026)
    AND MONTH(`ref_month`) BETWEEN 1 AND 9
  GROUP BY `brand`
), `ranked` AS (
  SELECT
    `brand`,
    `units_2025_jan_sep`,
    `units_2026_jan_sep`,
    `units_2026_jan_sep` - `units_2025_jan_sep` AS `growth_units`,
    RANK() OVER (ORDER BY (`units_2026_jan_sep` - `units_2025_jan_sep`) DESC, `brand` ASC) AS `rnk`
  FROM `ytd`
  WHERE `brand` IS NOT NULL
)
SELECT
  `brand`,
  `units_2025_jan_sep`,
  `units_2026_jan_sep`,
  `growth_units`
FROM `ranked`
WHERE `rnk` <= 10
ORDER BY `growth_units` DESC, `brand` ASC;
DESCRIÇÃO: Você quer ver as 10 marcas de automóveis que mais cresceram em unidades vendidas no acumulado de janeiro a setembro de 2026 em comparação com o mesmo período de 2025.
RESULTADO (10 linhas): brand | units_2025_jan_sep | units_2026_jan_sep | growth_units
  BRAND_6e1d76 | 76388 | 168723 | 92335
  BRAND_4c8e5b | 255535 | 308735 | 53200
  BRAND_540786 | 0 | 37818 | 37818
  BRAND_a66864 | 154269 | 188341 | 34072
  BRAND_587781 | 2279 | 35098 | 32819
  BRAND_d04bfe | 26981 | 58121 | 31140
  BRAND_d19014 | 73575 | 82639 | 9064
  BRAND_3b980e | 49093 | 58042 | 8949
  BRAND_de57f1 | 1745 | 10060 | 8315
  BRAND_e88676 | 0 | 7103 | 7103
RESPOSTA: No acumulado de **jan-set de 2026 vs jan-set de 2025** no segmento de **automóveis**, as 10 marcas com maior crescimento em unidades são estas; a líder foi a **BRAND_6e1d76**, com **+92.335** unidades, seguida por **BRAND_4c8e5b** (**+53.200**) e **BRAND_540786** (**+37.818**).

Exemplos incluem:
- **BRAND_6e1d76**: **+92.335** unidades
- **BRAND_4c8e5b**: **+53.200** unidades
- **BRAND_540786**: **+37.818** unidades
- **BRAND_a66864**: **+34.072** unidades
- **BRAND_587781**: **+32.819** unidades

Entre as 10 marcas exibidas, o crescimento vai de **+7.103** a **+92.335** unidades, com forte destaque para marcas chinesas entre os maiores avanços.
```
