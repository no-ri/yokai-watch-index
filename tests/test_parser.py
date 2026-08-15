"""パーサのテスト（標準ライブラリの unittest のみ）。

    python3 -m unittest discover -s tests -v

フィクスチャは実データの**構造上の癖**を再現した合成データ。
取得元の散文は含めない（SPEC.md §2.2。このリポジトリは public のため）。
再現している癖はすべて実データで確認したもので、出典は SPEC.md §15 と
`tools/spec_audit.py`。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from parse_fandom import (  # noqa: E402
    Reports,
    detect_series,
    extract_translations,
    fold_presence,
    lead_section,
    parse_air_date,
    parse_characters_section,
    parse_link_target,
)
from wikitext import (  # noqa: E402
    clean_value,
    extract_braced,
    iter_pages,
    normalize_spaces,
    normalize_title_key,
    parse_template_params,
    split_params,
    strip_ruby,
)


class TestNormalize(unittest.TestCase):
    def test_nbsp_is_normalized(self):
        # 実データ: 'Konbu-san (Shadowside)' と 'Konbu-san (Shadowside)'
        # 見た目が同じなので目視では気づけない（SPEC.md §5.6）
        self.assertEqual(
            normalize_spaces("Konbu-san (Shadowside)"),
            "Konbu-san (Shadowside)",
        )

    def test_ideographic_and_zero_width_space(self):
        self.assertEqual(normalize_spaces("A　B​C"), "A B C")

    def test_strip_ruby_drops_reading_not_base(self):
        self.assertEqual(
            strip_ruby("みちび<ruby>鬼<rt>き</rt></ruby>"), "みちび鬼")

    def test_title_key_unifies_halfwidth_and_fullwidth(self):
        # Fandom は半角 "!"、妖Tube は全角 "！"（SPEC.md §15.3）
        self.assertEqual(
            normalize_title_key("妖怪がいる!"),
            normalize_title_key("妖怪がいる！"),
        )

    def test_title_key_unifies_wave_dash_and_strips_brackets(self):
        self.assertEqual(
            normalize_title_key("「妖怪しょうぶし」〜前編〜"),
            normalize_title_key("妖怪しょうぶし ～前編～"),
        )


class TestTemplateExtraction(unittest.TestCase):
    def test_balanced_extraction_stops_at_matching_close(self):
        # 非貪欲マッチだと本文まで飲み込む（SPEC.md §5.3）
        text = "{{yo-kai|a={{small|(YW)}}|b=2}}\n\n本文 {{other}}"
        block = extract_braced(text, 0)
        self.assertEqual(block, "{{yo-kai|a={{small|(YW)}}|b=2}}")

    def test_split_params_ignores_pipes_inside_nesting(self):
        parts = split_params("tmpl|a=[[X|Y]]|b={{t|1|2}}|c=3")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[3], "c=3")

    def test_params_are_lowercased_and_first_wins(self):
        params = parse_template_params("{{Yo-kai|Rank = S|rank = A}}")
        self.assertEqual(params["rank"], "S")

    def test_clean_value_expands_small_and_links(self):
        self.assertEqual(clean_value("Seafood {{small|(YW)}}"), "Seafood (YW)")
        self.assertEqual(clean_value("[[Gera Gera Po Song]]"), "Gera Gera Po Song")
        self.assertEqual(clean_value("[[Nathan Adams|Nate]]"), "Nate")

    def test_clean_value_handles_br_variants(self):
        # 実データに <br> <br > <br/> が混在する（SPEC.md §5.6）
        self.assertEqual(
            clean_value("204 (Friend)<br >#B-028 (Boss)").splitlines(),
            ["204 (Friend)", "#B-028 (Boss)"],
        )


class TestSelfClosingText(unittest.TestCase):
    """本文が空のページが丸ごと消えるバグへの回帰テスト（SPEC.md §5.13。実測34件）。"""

    XML = (
        "<mediawiki>"
        "<page><title>Full Page</title><revision>"
        "<text bytes=\"20\" xml:space=\"preserve\">{{yokai|rank=E}}</text>"
        "</revision></page>"
        "<page><title>Empty Page</title><revision>"
        "<text bytes=\"0\" xml:space=\"preserve\" />"
        "</revision></page>"
        "</mediawiki>"
    )

    def test_self_closed_text_page_is_not_dropped(self):
        path = Path(self._tmp())
        pages = list(iter_pages(path))
        self.assertEqual([p.title for p in pages], ["Full Page", "Empty Page"])
        self.assertEqual(pages[1].text, "")

    def _tmp(self) -> str:
        import tempfile

        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".xml", delete=False, encoding="utf-8")
        fh.write(self.XML)
        fh.close()
        self.addCleanup(lambda: Path(fh.name).unlink(missing_ok=True))
        return fh.name


class TestPresence(unittest.TestCase):
    def setUp(self):
        self.reports = Reports()

    def fold(self, note: str):
        return fold_presence(note, self.reports, "EP001", "Jibanyan")

    def test_no_note_is_main(self):
        self.assertEqual(self.fold(""), ("main", False))

    def test_debut_is_separated_from_presence(self):
        # 410件ある。濃淡ではなく初登場なので presence に混ぜない（SPEC.md §5.8）
        self.assertEqual(self.fold("debut"), ("main", True))
        self.assertEqual(self.fold("debut, cameo"), ("cameo", True))

    def test_weaker_token_wins(self):
        self.assertEqual(self.fold("flashback; cameo"), ("flashback", False))
        self.assertEqual(self.fold("cameo; pictured"), ("cameo", False))
        self.assertEqual(self.fold("pictured;mentioned"), ("mentioned", False))

    def test_non_substantive_tokens_fold_to_cameo(self):
        for note in ("medal only", "silhouette only", "non-speaking cameo"):
            self.assertEqual(self.fold(note)[0], "cameo", note)

    def test_slash_is_a_separator(self):
        # 実データ: "anime debut/non-speaking cameo"（D-20260815-07）
        self.assertEqual(self.fold("anime debut/non-speaking cameo"),
                         ("cameo", True))

    def test_unknown_note_falls_back_to_main_and_is_reported(self):
        self.assertEqual(self.fold("wobbling about"), ("main", False))
        self.assertEqual(len(self.reports.unknown_presence), 1)
        self.assertEqual(self.reports.unknown_presence[0]["token"],
                         "wobbling about")


class TestLinks(unittest.TestCase):
    def test_anime_suffix_and_pipe_and_anchor(self):
        self.assertEqual(parse_link_target("Jibanyan (anime)|Jibanyan"),
                         "Jibanyan (anime)")
        self.assertEqual(parse_link_target("Noway|Noways"), "Noway")
        self.assertEqual(parse_link_target("Foo#Bar"), "Foo")

    def test_shadowside_suffix_is_kept(self):
        # (Shadowside) は別キャラなので剥がさない（SPEC.md §5.8）
        self.assertEqual(parse_link_target("Venoct (Shadowside)"),
                         "Venoct (Shadowside)")

    def test_category_and_interwiki_are_discarded(self):
        self.assertIsNone(parse_link_target(":Category:Gemnyans"))
        self.assertIsNone(parse_link_target("w:c:inazuma-eleven:Foo"))

    def test_section_splits_slash_links_and_drops_linkless_lines(self):
        text = (
            "\n== Characters ==\n"
            "=== Humans ===\n"
            "* [[Nathan Adams|Nate]]\n"
            "=== Yo-kai ===\n"
            "* [[Jibanyan]]/[[Sternyan]] (cameo)\n"
            "* Classic Yo-kai Trio\n"
            "** [[Boyclops]]\n"
            "\n== Trivia ==\n* [[NotACharacter]]\n"
        )
        out = parse_characters_section(text)
        self.assertEqual([l for l, _ in out["humans"]], ["Nathan Adams|Nate"])
        self.assertEqual([l for l, _ in out["yokai"]],
                         ["Jibanyan", "Sternyan", "Boyclops"])
        # 注記は行内の全リンクに適用される
        self.assertEqual(out["yokai"][0][1], "cameo")
        self.assertEqual(out["yokai"][1][1], "cameo")
        self.assertEqual(out["yokai"][2][1], "")


class TestEpisode(unittest.TestCase):
    def test_translations_are_limited_to_lead(self):
        # ページ全体で数えると EP001 は 2 ではなく 4 になる（SPEC.md §5.12）
        text = (
            "{{episode|number=EP001}}\n"
            "{{translation|'''A'''|妖怪がいる!|Yokai ga Iru}} and "
            "{{translation|'''B'''|恐怖の交差点|Kyofu}} is the 1st episode.\n"
            "\n== Trivia ==\n"
            "{{translation|'''C'''|別の話|Betsu}}\n"
        )
        self.assertEqual(len(extract_translations(text)), 3)
        self.assertEqual(len(extract_translations(lead_section(text))), 2)

    def test_translation_uses_second_arg_not_romaji(self):
        # 第3引数には別の話のデータが入っている実例がある（SPEC.md §5.12）
        text = "{{translation|'''X'''|トムニャンのジャポン探訪|Jibanyan to itsutsu}}"
        self.assertEqual(extract_translations(text), [("X", "トムニャンのジャポン探訪")])

    def test_series_detection_excludes_ex_without_prefix(self):
        # EX011 / EX012 は prefix を持たない。ページ名で弾く（SPEC.md §5.11）
        self.assertEqual(detect_series("EP001", ""), ("gen1", None))
        self.assertEqual(detect_series("EX011", ""), (None, None))
        self.assertEqual(detect_series("YG001", "YSH"), (None, None))

    def test_series_detection_allows_missing_prefix_on_mn(self):
        # MN090 のように {{episode}} に prefix がない話がある（D-20260815-06）
        self.assertEqual(detect_series("MN001", "MN"), ("uta", None))
        self.assertEqual(detect_series("MN090", ""), ("uta", None))

    def test_series_detection_reports_contradiction(self):
        series, conflict = detect_series("EP050", "SS")
        self.assertIsNone(series)
        self.assertIsNotNone(conflict)

    def test_air_date(self):
        self.assertEqual(parse_air_date("January 8, 2014"), "2014-01-08")
        self.assertEqual(parse_air_date("April 9, 2021"), "2021-04-09")
        self.assertIsNone(parse_air_date("TBA"))


if __name__ == "__main__":
    unittest.main()
