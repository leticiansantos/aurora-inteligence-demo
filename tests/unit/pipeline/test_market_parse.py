"""Unit tests for market_parse. Fixtures are synthetic (fictional brands) and mimic the layout dialects
seen in the T3 spike. An optional test replays real spike output when MARKET_SPIKE_DIR is set.

Run: python3 -m unittest discover -s tests/unit/pipeline -v
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/market/pipeline/utilities"))
import market_parse as mp  # noqa: E402


def table(rows, header):
    def tr(cells, tag):
        return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
    return "<table>" + tr(header, "th") + "".join(tr(r, "td") for r in rows) + "</table>"


def el(page, kind, content):
    return {"bbox": [{"page_id": page, "coord": [0, 0, 1, 1]}], "type": kind, "content": content}


def summary(header, autos, light):
    return el(0, "table", table([["A) Autos", autos, "1", "1"], ["B) Com. Leves", light, "1", "1"],
                                 ["A + B", "0", "0", "0"]], header))


def doc(month_hdr="Jun/18", glued=True, with_label=True, brand_hdr="Fabricante"):
    """Page 0 totals + title, page 5 models (autos, lc), page 7 brands (autos, lc, mix)."""
    rk = (lambda i, n: [f"{i}° {n}"]) if glued else (lambda i, n: [f"{i}°", n])
    mh = [month_hdr] if glued else ["", "Modelo", month_hdr]
    models_a = [rk(1, "ALFA/UNO") + ["1.000"], rk(2, "ALFA/UNO/CROSS") + ["13,632"],
                rk(3, "BETA /SEDAN") + ["500"], rk(4, "GAM/X") + ["20"], rk(5, "ZETA/Z") + ["9"]]
    models_l = [rk(1, "ALFA/CARGO") + ["300"], rk(2, "BETA/VAN") + ["100"]]
    bh = ["Fabricante", "Quant.", "Part."] if glued else ["", "Fabricante", "Quant.", "Part."]
    brands_a = [rk(1, "ALFA") + ["14.632", "70%"], rk(2, "BETA") + ["500", "20%"], rk(3, "GAMMA") + ["20", "1%"]]
    brands_l = [rk(1, "ALFA") + ["300", "75%"], rk(2, "BETA") + ["100", "25%"]]
    lab = (lambda s: [el(p, "figure", s)]) if with_label else (lambda s: [])
    out = [el(0, "title", "Resumo Mensal Junho de 2018"), summary(["Segmentos", "2018 Jun (A)", "x", "y"], "16.200", "400")]
    out += [el(5, "section_header", "AUTOMÓVEIS")] if with_label else []
    out += [el(5, "table", table(models_a, ["Modelo"] + mh[-1:] if glued else mh))]
    out += [el(5, "section_header", "COMERCIAIS LEVES")] if with_label else []
    out += [el(5, "table", table(models_l, ["Modelo"] + mh[-1:] if glued else mh))]
    for text, rows in (("AUTOMÓVEIS", brands_a), ("COMERCIAIS LEVES", brands_l), ("AUTOMÓVEIS + COMERCIAIS LEVES", brands_a)):
        out += [el(7, "figure", text)] if with_label else []
        out += [el(7, "table", table(rows, bh if not glued else [brand_hdr, "Quant.", "Part."]))]
    return out


class Cells(unittest.TestCase):
    def test_numbers_pt_br_and_ocr_comma(self):
        self.assertEqual(mp.digits("13.632"), 13632)
        self.assertEqual(mp.digits("13,632"), 13632)
        self.assertIsNone(mp.digits("-"))

    def test_table_rows_strips_tags(self):
        rows = mp.table_rows("<table><tr><th>2024<br>Fev<br>(A)</th></tr><tr><td>-12,09<mark>✓</mark></td></tr></table>")
        self.assertEqual(rows, [["2024 Fev (A)"], ["-12,09✓"]])

    def test_brand_model_split_on_first_slash(self):
        self.assertEqual(mp.split_brand_model("alfa/Uno/Cross fox"), ("ALFA", "UNO/CROSS FOX"))
        self.assertEqual(mp.split_brand_model("BETA /SEDÃO"), ("BETA", "SEDAO"))

    def test_brand_table_cells_are_never_split(self):
        rows = [["Fabricante", "Quant."], ["12° ALFA/CARGO", "176"], ["13° ALFA", "144"]]
        d = doc()
        d = [e for e in d if e["bbox"][0]["page_id"] != 7]
        d.append(el(7, "figure", "COMERCIAIS LEVES"))
        d.append(el(7, "table", table([r for r in rows[1:]], rows[0])))
        d.append(el(5, "table", table([["1° ALFA/CARGO/BIG", "50"], ["2° ALFA/SMALL", "40"]], ["Modelo", "Jun/18"])))
        r = mp.parse_document(d)
        self.assertEqual({(b["brand"], b["rank"]) for b in r["brands"]}, {("ALFA/CARGO", 12), ("ALFA", 13)})

    def test_model_brand_uses_longest_published_brand(self):
        brand, raw, model, matched = mp.resolve_brand_model("ALFA/CARGO/BIG", {"ALFA", "ALFA/CARGO"})
        self.assertEqual((brand, raw, model, matched), ("ALFA/CARGO", "ALFA/CARGO", "BIG", True))
        self.assertEqual(mp.resolve_brand_model("ALFA/SMALL", {"ALFA", "ALFA/CARGO"}), ("ALFA", "ALFA", "SMALL", True))

    def test_canonical_brand(self):
        names = {"KOROLE", "ALFA", "ALFAMAR"}
        self.assertEqual(mp.canonical_brand("KOROL", names), ("KOROLE", True))
        self.assertEqual(mp.canonical_brand("ALFA", names), ("ALFA", True))   # equality first
        self.assertEqual(mp.canonical_brand("ALF", names), ("ALF", False))    # ambiguous prefix
        self.assertEqual(mp.canonical_brand("ZZZ", names), ("ZZZ", False))


class Document(unittest.TestCase):
    def check(self, d):
        r = mp.parse_document(d)
        self.assertEqual((r["ref_month"], r["month_source"], r["parse_status"]), ("2018-06-01", "p6_header", "ok"))
        self.assertFalse(r["month_conflict"])
        self.assertEqual({t["segment"]: t["units"] for t in r["totals"]}, {"automoveis": 16200, "comerciais_leves": 400})
        autos = {m["model"]: m for m in r["models"] if m["segment"] == "automoveis"}
        self.assertEqual(autos["UNO/CROSS"]["units"], 13632)            # OCR comma, split on first '/'
        self.assertEqual(autos["SEDAN"]["brand"], "BETA")               # 'BETA /SEDAN' spacing
        self.assertEqual(autos["X"]["brand"], "GAMMA")                  # unique prefix -> table brand
        self.assertTrue(autos["X"]["brand_matched"])
        self.assertFalse(autos["Z"]["brand_matched"])                   # not in the brand table
        self.assertEqual(sorted(r["brand_segments"]), ["automoveis", "comerciais_leves"])
        self.assertEqual(len([b for b in r["brands"] if b["segment"] == "automoveis"]), 3)
        self.assertEqual(len([b for b in r["brands"] if b["segment"] == "comerciais_leves"]), 2)  # 3rd table ignored
        self.assertEqual({m["page_id"] for m in r["models"]}, {5})
        self.assertEqual({b["page_id"] for b in r["brands"]}, {7})

    def test_glued_rank_with_labels(self):
        self.check(doc())

    def test_separate_rank_cell(self):
        self.check(doc(glued=False))

    def test_no_labels_falls_back_to_order(self):
        self.check(doc(with_label=False))

    def test_month_header_lowercase_portuguese_abbreviation(self):
        d = doc("set/23")
        d[1] = summary(["Segmentos", "2023 Set (A)"], "16.200", "400")
        d[0] = el(0, "title", "RESUMO MENSAL SETEMBRO 2023")
        r = mp.parse_document(d)
        self.assertEqual(r["ref_month"], "2023-09-01")
        self.assertFalse(r["month_conflict"])

    def test_ocr_accent_in_month_header(self):
        """'Maí/16' (OCR artefact) must still match: the table cannot be dropped."""
        d = doc("Maí/18")
        d[1] = summary(["Segmentos", "2018 Maí (A)"], "16.200", "400")
        d[0] = el(0, "title", "x")
        r = mp.parse_document(d)
        self.assertEqual(r["ref_month"], "2018-05-01")
        self.assertEqual(sorted(r["model_segments"]), ["automoveis", "comerciais_leves"])
        self.assertEqual(len([m for m in r["models"] if m["segment"] == "automoveis"]), 5)

    def test_conflicting_month_sources_are_flagged(self):
        d = doc()
        d[1] = summary(["Segmentos", "2018 Mai (A)"], "16.200", "400")
        r = mp.parse_document(d)
        self.assertEqual(r["ref_month"], "2018-06-01")   # p6 header wins
        self.assertTrue(r["month_conflict"])

    def test_month_column_chosen_by_header_not_position(self):
        d = doc()
        d[3] = el(5, "table", table([["1° ALFA/UNO", "777", "1.000"]], ["Modelo", "Mai/18", "Jun/18"]))
        autos = [m for m in mp.parse_document(d)["models"] if m["segment"] == "automoveis"]
        self.assertEqual([m["units"] for m in autos], [1000])

    def test_previa_edition_uses_title_totals_and_rejects_headerless_models(self):
        d = [el(0, "title", "PRÉVIA DOS EMPLACEMENTOS"), el(0, "title", "RESUMO MENSAL JANEIRO 2004"),
             el(0, "table", table([["a) Autos¹", "87.489"], ["b) Com. Leves¹", "13.620"]], ["Segmentos", "2004 Jan"])),
             el(5, "table", table([["1º", "ALFA/CARGO", "2.200", "2.200"]], ["", "Modelos", "Jan", "Acumulado (jan/dez)"]))]
        r = mp.parse_document(d)
        self.assertEqual((r["ref_month"], r["month_source"], r["parse_dialect"]), ("2004-01-01", "title", "previa"))
        self.assertEqual({t["segment"]: t["units"] for t in r["totals"]}, {"automoveis": 87489, "comerciais_leves": 13620})
        self.assertEqual((r["models"], r["brands"], r["model_segments"], r["brand_segments"]), ([], [], [], []))

    def test_2003_order_without_labels_uses_sums_against_p1_totals(self):
        """p8 order Autos, Autos+CL, CL and no labels: the mix table must never become light commercial."""
        d = doc(with_label=False)
        b = [i for i, e in enumerate(d) if e["bbox"][0]["page_id"] == 7]
        d[b[1]], d[b[2]] = (el(7, "table", table([["1° ALFA", "14.932"], ["2° BETA", "600"], ["3° GAMMA", "20"]],
                                                  ["Fabricante", "Quant."])),
                            el(7, "table", table([["1° ALFA", "300"], ["2° BETA", "100"]], ["Fabricante", "Quant."])))
        r = mp.parse_document(d)
        light = [x for x in r["brands"] if x["segment"] == "comerciais_leves"]
        self.assertEqual(sum(x["units"] for x in light), 400)   # <= p1 light-commercial total (400)
        self.assertEqual(sum(1 for x in r["brands"] if x["segment"] == "automoveis"), 3)

    def test_tokens_label_variants(self):
        self.assertEqual(mp._label_segment("AUTOMÓVEIS"), "automoveis")
        self.assertEqual(mp._label_segment("Comerciais Leves"), "comerciais_leves")
        self.assertEqual(mp._label_segment("AUTOMÓVEIS + COM. LEVES"), "mix")
        self.assertIsNone(mp._label_segment("Ranking por marca Junho/2025"))

    def test_row_with_empty_first_cell_is_kept(self):
        rows = [["", "Fabricante", "Quant.", "Part."], ["", "1°", "ALFA", "300", "9%"], ["", "2° BETA", "100", "3%"]]
        got = mp.parse_ranking(rows, "brand")
        self.assertEqual([(g["rank"], g["name"], g["units"]) for g in got], [(1, "ALFA", 300), (2, "BETA", 100)])

    def test_first_quant_column_wins(self):
        rows = [["Fabricante", "Quant.", "Quant. acum."], ["1° ALFA", "10", "99"]]
        self.assertEqual(mp.parse_ranking(rows, "brand")[0]["units"], 10)

    def test_no_month_and_empty_inputs(self):
        self.assertEqual(mp.parse_document([])["parse_status"], "error")
        self.assertEqual(mp.parse_document([el(0, "text", "nothing")])["parse_status"], "no_month")
        self.assertEqual(mp.parse_document_json(None)["parse_status"], "error")
        self.assertEqual(mp.parse_document_json("not json")["parse_status"], "error")


@unittest.skipUnless(os.environ.get("MARKET_SPIKE_DIR"), "set MARKET_SPIKE_DIR to replay real spike output")
class RealSpike(unittest.TestCase):
    """Totals must equal the PDF's own p1 totals (QA oracle values), brand tables cover >= 98%."""
    EXPECTED = {"2003_01_2": ("2003-01-01", 96383, 10224), "2013_01_2": ("2013-01-01", 253429, 43423),
                "2023_02_3": ("2023-03-01", 146174, 40409), "2025_06_02": ("2025-06-01", 159128, 43036),
                "2004_01_2": ("2004-01-01", 87489, 13620)}

    def test_expected(self):
        for name, (month, autos, light) in self.EXPECTED.items():
            with self.subTest(file=name):
                r = mp.parse_document(json.load(open(Path(os.environ["MARKET_SPIKE_DIR"]) / f"{name}.json")))
                self.assertEqual(r["ref_month"], month)
                tot = {t["segment"]: t["units"] for t in r["totals"]}
                self.assertEqual((tot["automoveis"], tot["comerciais_leves"]), (autos, light))
                for seg, total in tot.items():
                    listed = sum(b["units"] for b in r["brands"] if b["segment"] == seg)
                    if r["brands"]:
                        self.assertTrue(0.98 * total <= listed <= total, (seg, listed, total))


if __name__ == "__main__":
    unittest.main()
