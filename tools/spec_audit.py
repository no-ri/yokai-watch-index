#!/usr/bin/env python3
"""SPEC.md §15 の実測値を再現する（着手前レビューの計測の出典）。

    python3 tools/spec_audit.py

数値を疑ったときにここで再現する。パイプラインではないので、
`scripts/parse_fandom.py` の動作には影響しない。
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from wikitext import (  # noqa: E402
    extract_braced,
    extract_categories,
    find_template,
    load_pages,
    load_titles,
    normalize_spaces,
    parse_template_params,
    split_params,
)

RAW = ROOT / "raw" / "fandom"


def rule(label: str) -> None:
    print(f"\n--- {label} " + "-" * max(0, 60 - len(label)))


def main() -> int:
    if not RAW.exists():
        print(f"ERROR: {RAW} がない", file=sys.stderr)
        return 2

    result = load_pages(RAW)
    titles = load_titles(RAW / "titles.txt")
    pages = result.pages

    rule("§5.13 ページ数の照合")
    print(f"  <page> の総数        {result.raw_count:,}")
    print(f"  重複タイトル         {len(result.duplicates)} 件 {result.duplicates}")
    print(f"  重複排除後           {len(pages):,}")
    print(f"  titles.txt           {len(titles):,}")
    print(f"  本文が空（<text />） {len(result.empty_text)} 件")
    print(f"  集合差               titles.txt のみ {len(set(titles) - set(pages))} / "
          f"XML のみ {len(set(pages) - set(titles))}")

    rule("§15.1 種別の内訳（排他分類。妖怪優先）")
    kinds: dict[str, str] = {}
    ns_skipped = 0
    NS = {"File", "Category", "Template", "Help", "User", "Module",
          "MediaWiki", "Talk", "Board", "Forum", "Blog"}
    both_templates: list[str] = []
    for title, text in pages.items():
        if ":" in title and title.split(":", 1)[0] in NS:
            ns_skipped += 1
            continue
        is_redirect = bool(re.match(r"\s*#\s*REDIRECT", text, re.I))
        y = bool(re.search(r"\{\{\s*yo-?kai\s*[|}]", text, re.I))
        c = bool(re.search(r"\{\{\s*character\s*[|}]", text, re.I))
        e = bool(re.search(r"\{\{\s*episode\s*[|}]", text, re.I))
        if y and c and not is_redirect:
            both_templates.append(title)
        if is_redirect:
            kinds[title] = "redirect"
        elif y:
            kinds[title] = "yokai"
        elif c:
            kinds[title] = "character"
        elif e:
            kinds[title] = "episode"
        else:
            kinds[title] = "unclassified"
    counts = Counter(kinds.values())
    for key in ("yokai", "character", "episode", "redirect", "unclassified"):
        print(f"  {key:<14} {counts[key]:>6,}")
    print(f"  {'namespace_skipped':<14} {ns_skipped:>6,}")
    print(f"  {'合計':<13} {sum(counts.values()) + ns_skipped:>6,}")
    print(f"\n  {{yo-kai}} と {{character}} を両方持つページ: {len(both_templates)} 件")
    for t in both_templates:
        print(f"    {t}")
    print("  → 妖怪優先で数えると人間キャラは 154。SPEC.md §15.1 の 160 は"
          "\n    {{character}} を単独で数えた値で、内訳の合計が titles.txt と合わない。")

    rule("§5.11 エピソードの prefix")
    infobox_prefix: Counter[str] = Counter()
    anywhere_prefix: Counter[str] = Counter()
    for title, kind in kinds.items():
        if kind != "episode":
            continue
        text = pages[title]
        block = find_template(text, r"episode")
        params = parse_template_params(block) if block else {}
        infobox_prefix[normalize_spaces(params.get("prefix", "")) or "(none)"] += 1
        m = re.search(r"\|\s*prefix\s*=\s*([^\n|}]*)", text)
        anywhere_prefix[normalize_spaces(m.group(1)) if m else "(none)"] += 1
    print("  {{episode}} 本体のみ:", dict(sorted(infobox_prefix.items())))
    print("  ページ全体（{{episode/nav}} を含む）:",
          dict(sorted(anywhere_prefix.items())))
    print("  → 両者は一致しない。nav 側にしか prefix がない話が実在するため、")
    print("    prefix を必須にすると♪が32話落ちる（SPEC.md §5.11 / D-20260815-06）。")

    rule("§15.6 セグメント数（lead 段落の {{translation}}）")
    seg: Counter[str] = Counter()
    eps: Counter[str] = Counter()
    for title in pages:
        m = re.fullmatch(r"(EP|MN)(\d{3})", title)
        if not m or kinds.get(title) != "episode":
            continue
        text = pages[title]
        lead = text[: text.index("\n==")] if "\n==" in text else text
        n = len(re.findall(r"\{\{\s*translation\s*\|", lead, re.I))
        seg[m.group(1)] += n
        eps[m.group(1)] += 1
    total_seg = sum(seg.values())
    for key in ("EP", "MN"):
        per = seg[key] / eps[key] if eps[key] else 0
        print(f"  {key}  放送回 {eps[key]:>3}  セグメント {seg[key]:>4}  "
              f"1話あたり {per:.2f}")
    print(f"  計  セグメント {total_seg:,}")

    rule("§15.6 presence 注記")
    notes: Counter[str] = Counter()
    for title in pages:
        if not re.fullmatch(r"(EP|MN)\d{3}", title):
            continue
        m = re.search(r"\n==+\s*Characters\s*==+(.*?)(?=\n==[^=]|\Z)",
                      pages[title], re.S | re.I)
        if not m:
            continue
        for line in m.group(1).splitlines():
            for note in re.findall(r"\]\]\s*\(([^)]*)\)", line):
                notes[note.strip().lower()] += 1
    print(f"  注記の種類 {len(notes)}")
    for note, count in notes.most_common(12):
        print(f"    ({note:<22}) {count:>5}")

    rule("§15.1 infobox パラメータと材料の充足率")
    params_all: Counter[str] = Counter()
    lang_ja = ja_param = etymology = medallium = biology = 0
    yokai_titles = [t for t, k in kinds.items() if k == "yokai"]
    for title in yokai_titles:
        text = pages[title]
        block = find_template(text, r"yo-?kai")
        if block:
            for part in split_params(block[2:-2])[1:]:
                if "=" in part:
                    params_all[normalize_spaces(part.split("=", 1)[0]).lower()] += 1
        lang = find_template(text, r"language")
        if lang and "ja-name" in parse_template_params(lang):
            lang_ja += 1
        if re.search(r"\|\s*japanese name\s*=\s*\S", text, re.I):
            ja_param += 1
        if re.search(r"==+\s*Etymology\s*==+", text, re.I):
            etymology += 1
        if re.search(r"\{\{\s*medallium", text, re.I):
            medallium += 1
        if re.search(r"==+\s*Biology\s*==+", text, re.I):
            biology += 1
    n = len(yokai_titles)
    print(f"  infobox パラメータ   {len(params_all)} 種類")
    print(f"  {{language}} ja-name  {lang_ja:>5} / {n} = {lang_ja / n:.1%}")
    print(f"  japanese name        {ja_param:>5} / {n} = {ja_param / n:.1%}")
    print(f"  Etymology 節         {etymology:>5} / {n} = {etymology / n:.1%}")
    print(f"  {{medallium}}         {medallium:>5} / {n} = {medallium / n:.1%}")
    print(f"  Biology 節           {biology:>5} / {n} = {biology / n:.1%}")

    rule("§5.15 劇場版")
    movies = [t for t in pages if re.fullmatch(r"M\d{2}", t)]
    print(f"  M\\d\\d 形式のページ    {len(movies)} 件  {movies}")
    print("  → export に劇場版は含まれていない。overrides/movies.csv から構成する。")

    rule("カテゴリ軸の実測")
    cats: Counter[str] = Counter()
    for text in pages.values():
        for cat in extract_categories(text):
            cats[cat] += 1
    for label, pattern in [
        ("種族", r"[Tt]ribe$"), ("ランク", r"^Rank "),
        ("属性", r"-attribute Yo-kai$"), ("役割", r" Role Yo-kai$"),
        ("派生", r"'s Variants$"),
    ]:
        hits = sorted(((c, v) for c, v in cats.items() if re.search(pattern, c)),
                      key=lambda kv: -kv[1])
        print(f"  {label}: {len(hits)} 種  {hits[:8]}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
