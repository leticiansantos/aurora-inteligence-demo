"""Pure-Python extraction of the Fenabrave monthly registration tables.

Input: the `elements` array produced by `ai_parse_document` (version 2.0) for pages
1, 6 and 8 of a monthly PDF. Output: plain dicts, so the module is unit-testable
without Spark and is wrapped in a UDF by the pipeline.

Rules (ADR docs/architecture/market-ingestion.md, D2/D3):
- tables are selected by `page_id` (0-based) and by order, never by header text;
- the reference month comes from the p6 column header (`Mmm/AA`), cross-checked with
  the p1 header and the "Resumo Mensal <Mes> de <Ano>" title;
- no brand names are hard-coded: model-row brands are matched to the brand table of the
  same month and segment (equality, else unique prefix).
"""
import json
import re
import unicodedata
from html.parser import HTMLParser

SEG_AUTOS = "automoveis"
SEG_LIGHT = "comerciais_leves"

PAGE_TOTALS = 0   # PDF page 1: segment totals + month header + title
PAGE_MODELS = 5   # PDF page 6: monthly model ranking (autos, light commercial)
PAGE_BRANDS = 7   # PDF page 8: monthly brand ranking (autos, light commercial, [autos+lc ignored])

MONTH_ABBR = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
              "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
MONTH_NAMES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
               "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}

_ABBR_ALT = "|".join(MONTH_ABBR)
_NAME_ALT = "|".join(MONTH_NAMES)
HDR_MONTH = re.compile(rf"^({_ABBR_ALT})\s*/\s*(\d{{2}})$", re.I)
RANK = re.compile(r"^(\d+)\s*[º°˚]\s*(.*)$")
P1_YEAR_MONTH = re.compile(rf"(\d{{4}})\s+({_ABBR_ALT})\w*\s*\(A\)", re.I)
P1_MONTH = re.compile(rf"\b({_ABBR_ALT})\w*\s*\(A\)", re.I)
TITLE = re.compile(rf"RESUMO\s+MENSAL\s+({_NAME_ALT})\s+(?:DE\s+)?(\d{{4}})")


def norm(text):
    """Upper case, no accents, collapsed whitespace."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def month_header(cell):
    """`Mmm/AA` header cell -> match (groups: abbreviation, yy) or None. Diacritics are ignored because the
    OCR sometimes returns 'Maí/16' for 'Mai/16'."""
    return HDR_MONTH.match(norm(cell))


def digits(text):
    """pt-BR number to int: drops '.', ',' (OCR comma in 2015-01) and anything else non-numeric."""
    d = re.sub(r"\D", "", text or "")
    return int(d) if d else None


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def table_rows(html):
    """HTML table -> list of rows (list of cell strings), tags stripped."""
    p = _TableParser()
    p.feed(html or "")
    p.close()
    return [r for r in p.rows if r]


def element_page(e):
    if e.get("page") not in (None, ""):
        return int(e["page"])
    try:
        return int(e["bbox"][0]["page_id"])
    except (KeyError, IndexError, TypeError):
        return None


def _label_segment(text):
    """Segment label printed above a ranking table, by tokens: AUTO / COMERCIAIS|COM. / LEVES.
    Both present -> 'mix' (autos + light commercial). Long texts (titles, headers) are not labels."""
    n = norm(text)
    if not n or len(n) > 40:
        return None
    has_auto = "AUTO" in n
    has_light = bool(re.search(r"\bCOMERCIAI?S?\b|\bCOM\b|\bLEVES\b", n))
    if has_auto and has_light:
        return "mix"
    return SEG_AUTOS if has_auto else SEG_LIGHT if has_light else None


def _collect(elements):
    """-> (tables, texts). tables = [(page, rows, label)], label = segment label seen just above on the page.
    A label may be split over two elements ("AUTOMÓVEIS + COMERCIAIS" / "LEVES"): the last two texts are joined."""
    tables, texts, label, last_page, prev = [], [], None, None, ""
    for e in elements or []:
        page, kind, content = element_page(e), e.get("type"), e.get("content") or ""
        if page != last_page:
            label, last_page, prev = None, page, ""
        if kind == "table":
            tables.append((page, table_rows(content), label))
            label, prev = None, ""
        elif content:
            texts.append((page, content))
            pair = _label_segment(f"{prev} {content}") if prev else None
            label = "mix" if pair == "mix" else (_label_segment(content) or label)
            prev = content
    return tables, texts


def _tables_on(tables, page):
    return [rows for p, rows, _ in tables if p == page and rows]


def segment_tables(tables, page, totals=None, listed_sum=None):
    """[(segment, rows)] for a ranking page. Decision order (ADR D2):
    1. label above the table, by tokens (a 'mix' = autos + light commercial table is ignored);
    2. for unlabeled tables, the listed sum against the p1 totals: a light-commercial table never sums
       more than the p1 light-commercial total, the mix table sums more than the p1 autos total;
    3. only then the order (1st = autos, 2nd = light commercial, others ignored)."""
    items = [(lab, rows) for p, rows, lab in tables if p == page and rows]
    out = {lab: rows for lab, rows in reversed(items) if lab in (SEG_AUTOS, SEG_LIGHT)}
    loose = [rows for lab, rows in items if lab is None]
    totals = totals or {}
    if loose and listed_sum and totals.get(SEG_AUTOS) and totals.get(SEG_LIGHT):
        sums = [(listed_sum(r), r) for r in loose]
        cand = [(s, r) for s, r in sums if s <= totals[SEG_AUTOS]]          # drops the mix table
        if SEG_AUTOS not in out:
            pick = next(((s, r) for s, r in cand if s > totals[SEG_LIGHT]), cand[0] if cand else None)
            if pick:
                out[SEG_AUTOS] = pick[1]
                cand = [c for c in cand if c[1] is not pick[1]]
        if SEG_LIGHT not in out:
            pick = next(((s, r) for s, r in cand if s <= totals[SEG_LIGHT]), None)
            if pick:
                out[SEG_LIGHT] = pick[1]
    else:
        free = [s for s in (SEG_AUTOS, SEG_LIGHT) if s not in out]
        for rows in loose:
            if free:
                out[free.pop(0)] = rows
    return [(s, out[s]) for s in (SEG_AUTOS, SEG_LIGHT) if s in out]


# ---------------------------------------------------------------- reference month
def _months_from_p6(model_tables):
    """All `Mmm/AA` header cells of the p6 tables, in order (normally exactly one)."""
    out = []
    for rows in model_tables:
        for cell in rows[0]:
            m = month_header(cell)
            if m and (2000 + int(m.group(2)), MONTH_ABBR[m.group(1).upper()]) not in out:
                out.append((2000 + int(m.group(2)), MONTH_ABBR[m.group(1).upper()]))
    return out


def _totals_table(tables):
    for rows in _tables_on(tables, PAGE_TOTALS):
        if norm(rows[0][0]).startswith("SEGMENT"):
            return rows
    return None


def _month_from_p1(totals):
    if not totals:
        return None
    text = norm(" ".join(" ".join(r) for r in totals[:2]))
    m = P1_YEAR_MONTH.search(text)
    if m:
        return int(m.group(1)), MONTH_ABBR[m.group(2).upper()]
    m = P1_MONTH.search(text)
    y = re.search(r"\b(20\d{2})\b", text)
    if m and y:
        return int(y.group(1)), MONTH_ABBR[m.group(1).upper()]
    return None


def _month_from_title(texts, pattern):
    for _, content in texts:
        m = pattern.search(norm(content))
        if m:
            return int(m.group(2)), MONTH_NAMES[m.group(1)]
    return None


# ---------------------------------------------------------------- ranking tables
def parse_ranking(rows, kind, month_token=None):
    """Parse a ranking table. kind = 'model' (month column by header) or 'brand' (Quant. column).

    Returns a list of {rank, name, units}. Handles both rank shapes (glued `1° NAME` or in its own cell).
    """
    header, body = rows[0], rows[1:]
    idx = None
    for i, cell in enumerate(header):
        if kind == "model":
            m = month_header(cell)
            if m and (month_token is None or (m.group(1).upper(), m.group(2)) == month_token):
                idx = i  # the month column is chosen by header, never by position
        elif kind == "brand" and idx is None and re.match(r"^quant", cell.strip(), re.I):
            idx = i
    if kind == "model" and idx is None:
        return []  # no header for the reference month (e.g. preview edition): table is not accepted
    out = []
    for cells in body:
        f = next((k for k, c in enumerate(cells) if c.strip()), None)  # skip leading empty cells, keep the row
        if f is None:
            continue
        m = RANK.match(cells[f])
        if not m:
            continue
        if m.group(2):
            name, name_idx = m.group(2), f
        elif len(cells) > f + 1:
            name, name_idx = cells[f + 1], f + 1
        else:
            continue
        j = None if idx is None else idx + (len(cells) - len(header))
        if j is None or not (name_idx < j < len(cells)):
            j = next((k for k in range(name_idx + 1, len(cells)) if digits(cells[k]) is not None), None)
        if j is None or not name.strip() or norm(name).startswith("TOTAL"):
            continue
        units = digits(cells[j])
        if units is not None:
            out.append({"rank": int(m.group(1)), "name": name, "units": units})
    return out


def split_brand_model(name):
    n = norm(name)
    if "/" in n:
        brand, model = n.split("/", 1)
        return brand.strip(), model.strip()
    return n, n


def resolve_brand_model(name, brand_names):
    """(brand, brand_raw, model, matched) for a model-row name. A published brand may itself contain '/'
    (e.g. 'X/Y' next to 'X'): the longest brand-table entry that prefixes the name wins; otherwise the
    name is split on the first '/' and the brand is matched by equality or unique prefix."""
    n = norm(name)
    hits = [b for b in brand_names if n.startswith(b + "/")]
    if hits:
        best = max(hits, key=len)
        return best, best, n[len(best) + 1:].strip(), True
    raw, model = split_brand_model(name)
    brand, matched = canonical_brand(raw, brand_names)
    return brand, raw, model, matched


def canonical_brand(raw, brand_names):
    """Equality, else unique prefix (raw is a truncated form of a published brand). -> (brand, matched)."""
    if raw in brand_names:
        return raw, True
    if len(raw) >= 3:
        hits = sorted({b for b in brand_names if b.startswith(raw)})
        if len(hits) == 1:
            return hits[0], True
    return raw, False


def parse_totals(rows):
    """First `a)` / `b)` rows of the p1 summary table -> {segment: units}."""
    out = {}
    for cells in rows[1:]:
        label = cells[0].strip() if cells else ""
        seg = SEG_AUTOS if re.match(r"^[aA]\)", label) else SEG_LIGHT if re.match(r"^[bB]\)", label) else None
        if seg and seg not in out:
            units = next((digits(c) for c in cells[1:] if digits(c) is not None), None)
            if units is not None:
                out[seg] = units
    return out


def dialect_for(year, previa):
    if previa:
        return "previa"
    if year is None:
        return None
    return "A_modelo" if year <= 2014 else "B_upper" if year == 2015 else "C_fabricante" if year <= 2023 else "D_2024"


# ---------------------------------------------------------------- document
def parse_document(elements):
    """elements: list of ai_parse_document elements (dict). Returns the extraction result (plain dict)."""
    res = {"ref_month": None, "month_source": None, "month_conflict": False, "parse_dialect": None,
           "parse_status": "error", "totals": [], "brands": [], "models": [],
           "brand_segments": [], "model_segments": []}
    if not elements:
        return res
    tables, texts = _collect(elements)
    previa = any(re.search(r"PREVIA DOS EMPLAC", norm(c)) for _, c in texts)  # sic: the PDF title is "EMPLACEMENTOS"
    model_tables = _tables_on(tables, PAGE_MODELS)
    totals_rows = _totals_table(tables)

    p6 = _months_from_p6(model_tables)
    p1, title = _month_from_p1(totals_rows), _month_from_title([t for t in texts if t[0] in (0, None)], TITLE)
    # with several month columns, the one that agrees with p1 / the title is the reference month
    p6_pick = next((ym for ym in p6 if ym in (p1, title)), p6[0] if p6 else None)
    found = [("p6_header", p6_pick), ("p1_header", p1), ("title", title)]
    if previa:  # the preview edition has no `Mmm/AA` ranking header: the p1 title wins
        found.sort(key=lambda f: f[0] != "title")
    found = [(s, ym) for s, ym in found if ym]
    if found:
        source, (year, month) = found[0]
        res["ref_month"] = f"{year:04d}-{month:02d}-01"
        res["month_source"] = source
        res["month_conflict"] = len({ym for _, ym in found}) > 1
    res["parse_dialect"] = dialect_for(found[0][1][0] if found else None, previa)
    res["parse_status"] = "ok" if found else "no_month"
    if not found:
        return res

    token = (list(MONTH_ABBR)[month - 1], f"{year % 100:02d}")
    totals = parse_totals(totals_rows) if totals_rows else {}
    brand_sum = lambda rows: sum(r["units"] for r in parse_ranking(rows, "brand"))  # noqa: E731
    model_sum = lambda rows: sum(r["units"] for r in parse_ranking(rows, "model", token))  # noqa: E731
    for seg, rows in segment_tables(tables, PAGE_BRANDS, totals, brand_sum):
        parsed = parse_ranking(rows, "brand")
        if parsed:
            res["brand_segments"].append(seg)
        for r in parsed:
            res["brands"].append({"segment": seg, "brand": norm(r["name"]),  # never split: 'X/Y' is one brand
                                  "units": r["units"], "rank": r["rank"], "page_id": PAGE_BRANDS})
    brand_names = {}
    for b in res["brands"]:
        brand_names.setdefault(b["segment"], set()).add(b["brand"])
    for seg, rows in segment_tables(tables, PAGE_MODELS, totals, model_sum):
        parsed = parse_ranking(rows, "model", token)
        if parsed:
            res["model_segments"].append(seg)
        for r in parsed:
            brand, raw, model, matched = resolve_brand_model(r["name"], brand_names.get(seg, set()))
            res["models"].append({"segment": seg, "brand": brand, "brand_raw": raw, "brand_matched": matched,
                                  "model": model, "units": r["units"], "rank": r["rank"], "page_id": PAGE_MODELS})
    res["totals"] = [{"segment": s, "units": u} for s, u in totals.items()]
    return res


def parse_document_json(elements_json):
    """UDF entry point: JSON text of the `elements` array (None-safe)."""
    try:
        elements = json.loads(elements_json) if elements_json else None
    except ValueError:
        elements = None
    return parse_document(elements)
