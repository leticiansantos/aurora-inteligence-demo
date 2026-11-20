#!/usr/bin/env python3
"""Build the serialized_space payload for the market Genie Agent.

Deterministic: ids are derived from content, so re-running produces the same payload (idempotent updates).
Usage: python3 scripts/genie/build_space.py [catalog] [schema] > /tmp/market_space.json
"""
import hashlib
import json
import sys

CATALOG = sys.argv[1] if len(sys.argv) > 1 else "classic_stable"
SCHEMA = sys.argv[2] if len(sys.argv) > 2 else "auto_intelligence"
FQ = f"{CATALOG}.{SCHEMA}"


def hid(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def col(name, description=None, synonyms=None, match=False, exclude=False):
    c = {"column_name": name}
    if description:
        c["description"] = [description]
    if synonyms:
        c["synonyms"] = synonyms
    if match:
        c["enable_format_assistance"] = True
        c["enable_entity_matching"] = True
    if exclude:
        c["exclude"] = True
    return c


COMMON = [
    col("ref_month", "Mês de referência dos emplacamentos (1º dia do mês, lido do PDF da Fenabrave).",
        ["mês", "data", "período", "competência"]),
    col("segment", "Segmento: 'automoveis' (carros de passeio) ou 'comerciais_leves' (picapes e furgões leves).",
        ["segmento", "automóveis", "carros", "comerciais leves"], match=True),
    col("brand", "Marca/fabricante como publicado pela Fenabrave (maiúsculas, sem acento). "
                 "'AURORA MOTORS' é a marca fictícia da demo.", ["marca", "fabricante", "montadora"], match=True),
    col("units", "Emplacamentos (unidades) no mês.", ["emplacamentos", "unidades", "vendas", "volume"]),
    col("rank", "Posição no ranking do mês (1 = maior volume). Nula na linha residual.", ["posição", "ranking"]),
    col("is_synthetic", "true apenas para as linhas da Aurora Motors (dado sintético somado ao mercado real).",
        ["sintético", "aurora"]),
    col("is_residual", "true na linha 'OUTRAS (NAO PUBLICADAS)': volume das marcas fora do ranking publicado.",
        ["outras", "resíduo"]),
]
SHARE = [
    col("share", "Participação de mercado como FRAÇÃO (0,03 = 3%). Denominador = total do segmento no mês.",
        ["share", "participação", "fatia", "market share"]),
    col("segment_total_units", "Total de emplacamentos do segmento no mês (denominador do share).",
        ["total do segmento", "tamanho do mercado"]),
]


def table(name, cols, description):
    return {"identifier": f"{FQ}.{name}", "description": [description],
            "column_configs": sorted(cols, key=lambda c: c["column_name"])}


tables = [
    table("market_brand_monthly", COMMON,
          "Emplacamentos mensais por marca (marcas reais publicadas + linha residual + Aurora Motors)."),
    table("market_model_monthly",
          [c for c in COMMON if c["column_name"] != "is_residual"]
          + [col("model", "Modelo do veículo como publicado (top 50 do mês) ou modelo fictício da Aurora.",
                 ["modelo", "carro", "veículo"], match=True)],
          "Ranking mensal de modelos: top 50 publicado pela Fenabrave + modelos da Aurora Motors. "
          "A soma dos modelos fica abaixo do total do mercado."),
    table("market_segment_totals",
          [c for c in COMMON if c["column_name"] in ("ref_month", "segment", "units")],
          "Tamanho do mercado: total publicado de emplacamentos por mês e segmento (sem a Aurora Motors)."),
    table("market_share_real", COMMON + SHARE,
          "Share e ranking de marcas só com o mercado REAL (sem a Aurora Motors)."),
    table("market_share_with_aurora", COMMON + SHARE,
          "Share e ranking de marcas INCLUINDO a Aurora Motors (fictícia), somada ao mercado real."),
]

SQLS = [l.replace("classic_stable.auto_intelligence", FQ)
        for l in open(__file__.rsplit("/", 1)[0] + "/queries.sql").read().splitlines()
        if l and not l.startswith("--")]
QUESTIONS = [
    "Qual foi o share da Aurora Motors em automóveis nos últimos 12 meses?",
    "Quais as 10 marcas que mais emplacaram em setembro de 2026?",
    "Como evoluiu o mercado de comerciais leves de 2019 a 2026?",
    "Quais os modelos mais vendidos da Aurora Motors em 2025?",
    "Quais marcas de automóveis mais cresceram de janeiro a setembro de 2026 em relação a 2025?",
]
# Benchmarks are paraphrases of the questions (same canonical SQL), so the eval does not just replay examples.
BENCH_QUESTIONS = [
    "Como ficou a participação da Aurora Motors no segmento de carros no último ano, mês a mês?",
    "Ranking das 10 maiores marcas em emplacamentos no mês de setembro de 2026",
    "Total anual de emplacamentos de comerciais leves entre 2019 e 2026",
    "Volume de cada modelo da Aurora Motors no ano de 2025",
    "Top 10 marcas de automóveis por crescimento em unidades, acumulado jan-set 2026 vs jan-set 2025",
]
# Example SQL teaches 4 query shapes (incl. the no-segment default); the other question are only sample questions + benchmarks.
EXAMPLE_IDX = [0, 1, 2, 4]
assert len(SQLS) == len(QUESTIONS) == len(BENCH_QUESTIONS)

INSTRUCTIONS = """## PURPOSE
- Responder perguntas sobre o mercado brasileiro de emplacamentos (Fenabrave, 2003 em diante) para o time comercial e de planejamento da Aurora Motors.

## DISAMBIGUATION
- Se a pergunta citar a Aurora Motors (ou "nós", "nossa marca"), use market_share_with_aurora; caso contrário, use market_share_real.
- Sem segmento informado (inclusive em rankings de marcas), use o mercado total: some automóveis e comerciais leves, e diga isso na resposta.
- Sem período informado, use o mês mais recente disponível e diga qual é.

## DATA QUALITY NOTES
- A linha 'OUTRAS (NAO PUBLICADAS)' (is_residual) não é uma marca: exclua-a de rankings de marcas.
- 2004-01 é uma edição prévia: só tem totais, sem ranking de marcas ou modelos.
- market_model_monthly traz só o top 50 de cada mês.

## Instructions you must follow when providing summaries
- Mostre share em porcentagem com uma casa decimal.
- Sempre diga o período usado.
- Quando a Aurora Motors aparecer, lembre que ela é uma marca fictícia com dados sintéticos.
- Responda em português do Brasil."""

space = {
    "version": 2,
    "config": {"sample_questions": sorted(
        [{"id": hid("sq", q), "question": [q]} for q in QUESTIONS], key=lambda x: x["id"])},
    "data_sources": {"tables": sorted(tables, key=lambda t: t["identifier"])},
    "instructions": {
        "text_instructions": [{"id": hid("ti", "v1"), "content": [INSTRUCTIONS]}],
        "example_question_sqls": sorted(
            [{"id": hid("ex", QUESTIONS[i]), "question": [QUESTIONS[i]], "sql": [SQLS[i]]} for i in EXAMPLE_IDX],
            key=lambda x: x["id"]),
    },
    "benchmarks": {"questions": sorted(
        [{"id": hid("bm", q), "question": [q], "answer": [{"format": "SQL", "content": [s]}]}
         for q, s in zip(BENCH_QUESTIONS, SQLS)], key=lambda x: x["id"])},
}
print(json.dumps(space, ensure_ascii=False))
