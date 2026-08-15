#!/usr/bin/env python3
"""Fandom の XML をパースして中間 JSON を作る（SPEC.md §5）。

    python3 scripts/parse_fandom.py

入力   raw/fandom/*.xml, raw/fandom/titles.txt, overrides/*.csv
出力   build/fandom.json（中間データ）, reports/*.csv（検証出力）

**このスクリプトは Fandom へアクセスしない。**ローカルファイルを読むだけ
（SPEC.md §2.3）。ネットワークを使うコードをここに足してはならない。

静かに失敗しないこと。処理できなかったものは必ず reports/ に出す。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikitext import (  # noqa: E402
    clean_value,
    extract_braced,
    extract_categories,
    find_template,
    load_pages,
    load_titles,
    normalize_spaces,
    normalize_title_key,
    parse_template_params,
    split_multi,
    split_params,
    strip_ruby,
)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "fandom"
OVERRIDES = ROOT / "overrides"
REPORTS = ROOT / "reports"
BUILD = ROOT / "build"

# ---------------------------------------------------------------------------
# SPEC.md §5.5 infobox パラメータのエイリアス
# 誤記（attribue / triobe / romanji name / apaneseva / foosyw3）を含む。
# ---------------------------------------------------------------------------

RANK_KEYS = [
    "rank", "rank-yk", "rank-yk2", "rank-yk3", "rank-yk4", "rank-ww",
    "rank-yww", "rank-ykb", "rank-ykb2", "rank-kunitori", "rank-sangokushi",
    "rank-w", "rank-ywmw", "rank-yw3",
]
TRIBE_KEYS = ["tribe", "triobe"]
TRIBE_SS_KEYS = ["sstribe"]
ATTRIBUTE_KEYS = ["attribute", "attribue"]
NAME_JA_KEYS = ["japanese name", "japanese", "yo-kai name", "character name"]
NAME_ROMAJI_KEYS = ["romaji name", "romaji", "romanji name"]
FOOD_KEYS = [
    "food", "foodyw", "foodyw1", "foodyw2", "foodyw3", "foodyw4", "foodyws",
    "foodywww", "foodyww", "foodywb", "foodyb", "foodspinoff", "foosyw3",
]
BADFOOD_KEYS = ["badfood", "despised food"]
MEDALLIUM_KEYS = [
    "yw", "yw2", "yw3", "yw4", "yws", "yw s", "ywb", "ywb2", "ywl", "yww",
    "ywww", "yskw", "yg", "wibwob", "wibwobx", "ukiukipedia",
]
TYPE_KEYS = ["type"]

# エイリアス表に載っている全キー。未知パラメータの判定に使う。
KNOWN_PARAMS = set(
    RANK_KEYS + TRIBE_KEYS + TRIBE_SS_KEYS + ATTRIBUTE_KEYS + NAME_JA_KEYS
    + NAME_ROMAJI_KEYS + FOOD_KEYS + BADFOOD_KEYS + MEDALLIUM_KEYS + TYPE_KEYS
    + ["image", "name", "defence", "defense", "stat defence", "stat defense",
       "japaneseva", "seiyu", "voice", "jva", "apaneseva"]
)

# ---------------------------------------------------------------------------
# SPEC.md §5.4 / §5.14 カテゴリ由来の分類軸
# ---------------------------------------------------------------------------

RANK_ENUM = ["E", "D", "C", "B", "A", "S", "SS"]

GEN1_TRIBES = {
    "Charming", "Brave", "Shady", "Tough", "Slippery", "Mysterious",
    "Heartful", "Eerie",
}
SS_TRIBES = {
    "Mononoke", "Oni", "Uwanosora", "Omamori", "Enma", "Onnen", "Goriki",
    "Wicked", "Tsukumono", "Izana", "Mikado", "Wandroid", "Shinma",
}
ATTRIBUTE_ENUM = {
    "fire", "water", "lightning", "ice", "earth", "wind", "drain",
    "restoration",
}
ATTRIBUTE_FIX = {"darin": "drain"}  # wiki 側の誤記
ROLE_ENUM = {"Fighter", "Tank", "Ranger", "Healer", "Shooter"}
YOKAI_TYPE_CATEGORIES = {
    "Boss Yo-kai": "Boss",
    "Classic Yo-kai": "Classic",
    "'Merican Yo-kai": "'Merican",
    "Merican Yo-kai": "'Merican",
}

RE_RANK_CAT = re.compile(r"^Rank ([A-Za-z+]+) Yo-kai$")
RE_ATTR_CAT = re.compile(r"^([A-Za-z]+)-attribute Yo-kai$", re.I)
RE_TRIBE_CAT = re.compile(r"^(.+?) [Tt]ribe$")
RE_ROLE_CAT = re.compile(r"^([A-Za-z]+) Role Yo-kai$")
RE_VARIANTS_CAT = re.compile(r"^(.+)'s Variants$")

# ---------------------------------------------------------------------------
# SPEC.md §5.8 presence 注記（実測65種類）
# ---------------------------------------------------------------------------

DEBUT_TOKENS = {"debut", "anime debut", "full debut", "first debut"}
# 実体を伴わない表現は cameo に寄せる
CAMEO_TOKENS = {
    "cameo", "medal only", "silhouette only", "voice only", "voice-only",
    "pictured", "shadow cameo", "face cameo", "on tv", "on television",
    "costume", "non-speaking cameo", "medal", "silhouette", "tv",
    "medal and voice only", "recap time", "daydream", "multiple",
}
FLASHBACK_TOKENS = {"flashback", "flashback cameo", "silhouette cameo"}
MENTIONED_TOKENS = {"mentioned", "first mentioned", "discussed"}
# 弱いものが勝つ（SPEC.md §5.8 規則2）
PRESENCE_ORDER = ["mentioned", "flashback", "cameo", "main"]


# 完全一致しなかったトークンに対する部分一致の受け皿。
# "flashback only" "cameo medal" "whisper's costume" のような自由記述を拾う。
# 上から順に評価する（強い意味を先に置く）。
KEYWORD_FALLBACK: list[tuple[str, str]] = [
    ("mentioned", "mentioned"),
    ("flashback", "flashback"),
    ("cameo", "cameo"),
    ("medal", "cameo"),
    ("silhouette", "cameo"),
    ("costume", "cameo"),
    ("voice", "cameo"),
    ("picture", "cameo"),
    ("recap", "cameo"),
    ("statue", "cameo"),
    ("sculpture", "cameo"),
    ("speaking role", "main"),
]


def fold_presence(note: str, reporter: "Reports", page: str, link: str) -> tuple[str, bool]:
    """注記文字列を (presence, is_debut) に畳む（SPEC.md §5.8）。"""
    if not note:
        return "main", False
    # 区切りは ; と , に加えて / も扱う。
    # "anime debut/non-speaking cameo" のような実例があるため（D-20260815-07）。
    tokens = [normalize_spaces(t).lower() for t in re.split(r"[;,/]", note)]
    tokens = [t for t in tokens if t]
    is_debut = False
    found: list[str] = []
    for tok in tokens:
        if tok in DEBUT_TOKENS:
            is_debut = True
            continue
        if "debut" in tok:
            is_debut = True  # "anime debut" 等。他の語を含む場合は下でも評価する
        if tok in MENTIONED_TOKENS:
            found.append("mentioned")
        elif tok in FLASHBACK_TOKENS:
            found.append("flashback")
        elif tok in CAMEO_TOKENS:
            found.append("cameo")
        elif tok in ("main", "full appearance"):
            found.append("main")
        else:
            matched = next(
                (level for kw, level in KEYWORD_FALLBACK if kw in tok), None)
            if matched:
                found.append(matched)
            elif "debut" not in tok:
                # 未知のトークンは必ず記録する（CLAUDE.md「静かに失敗しない」）
                reporter.unknown_presence.append(
                    {"episode": page, "link": link, "note": note, "token": tok}
                )
    if not found:
        # 規則4: 何も該当しなければ main に倒す。
        # main に倒せば「登場している」事実は保たれ、UI 上は多めに出るだけで済む。
        return "main", is_debut
    for level in PRESENCE_ORDER:
        if level in found:
            return level, is_debut
    return "main", is_debut


# ---------------------------------------------------------------------------
# レポート（SPEC.md §5.13）
# ---------------------------------------------------------------------------


class Reports:
    def __init__(self) -> None:
        self.unknown_params: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []
        self.unresolved: list[dict[str, Any]] = []
        self.unknown_presence: list[dict[str, Any]] = []
        self.segment_title_mismatch: list[dict[str, Any]] = []

    def write(self, out_dir: Path) -> dict[str, int]:
        out_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        # 未知パラメータは「名前」の一覧が欲しいので集約する（SPEC.md §5.13 の4）。
        agg: dict[str, dict[str, Any]] = {}
        for row in self.unknown_params:
            entry = agg.setdefault(
                row["param"],
                {"param": row["param"], "count": 0, "sample_page": row["page"],
                 "sample_value": row["sample"]},
            )
            entry["count"] += 1
        unknown_params_rows = sorted(agg.values(), key=lambda r: -r["count"])

        for name, rows in [
            ("unknown_params.csv", unknown_params_rows),
            ("conflicts.csv", self.conflicts),
            ("unresolved_yokai.csv", self.unresolved),
            ("unknown_presence.csv", self.unknown_presence),
            ("segment_title_mismatch.csv", self.segment_title_mismatch),
        ]:
            path = out_dir / name
            counts[name] = len(rows)
            if not rows:
                path.write_text("", encoding="utf-8-sig")
                continue
            fields = list(rows[0].keys())
            # Excel で開けるよう UTF-8 BOM 付き（CLAUDE.md「環境」）
            with path.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        return counts


# ---------------------------------------------------------------------------
# 名前解決（SPEC.md §5.9 / §5.10）
# ---------------------------------------------------------------------------

RE_REDIRECT = re.compile(r"#\s*REDIRECT\s*\[\[([^\]|#]+)", re.I)


def build_redirects(pages: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for title, text in pages.items():
        m = RE_REDIRECT.match(text.lstrip())
        if m:
            out[title] = normalize_spaces(strip_ruby(m.group(1)))
    return out


def resolve_redirect(name: str, redirects: dict[str, str]) -> str:
    """最大5段まで辿り、循環を検出したら打ち切る（SPEC.md §5.9）。"""
    seen = {name}
    for _ in range(5):
        target = redirects.get(name)
        if not target or target in seen:
            break
        name = target
        seen.add(name)
    return name


def load_overrides(path: Path) -> dict[str, str]:
    """overrides/unresolved_yokai.csv を読む。to が空の行は解決不能として無視。"""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            src = normalize_spaces(row.get("from", ""))
            dst = normalize_spaces(row.get("to", ""))
            if src and dst:
                out[src] = dst
    return out


# ---------------------------------------------------------------------------
# Characters 節のリンク（SPEC.md §5.8）
# ---------------------------------------------------------------------------

RE_LINK = re.compile(r"\[\[([^\]]+)\]\]")
RE_TRAILING_NOTE = re.compile(r"\(([^)]*)\)")


def parse_link_target(inner: str) -> str | None:
    """[[...]] の中身から解決対象のページ名を取り出す。破棄すべきものは None。"""
    inner = normalize_spaces(strip_ruby(inner))
    if not inner:
        return None
    if inner.startswith(":"):
        return None  # [[:Category:...]] などは破棄
    if re.match(r"^[a-z-]{1,10}:(c:)?", inner) and not inner.startswith("File:"):
        # w:c:inazuma-eleven:Foo のようなインターウィキ
        if ":" in inner and not inner.split(":", 1)[0].istitle():
            return None
    target = inner.split("|", 1)[0]     # パイプ左を採用
    target = target.split("#", 1)[0]    # #以降を落とす
    target = normalize_spaces(target)
    return target or None


def parse_characters_section(text: str) -> dict[str, list[tuple[str, str]]]:
    """Characters 節から {"humans": [(link, note)], "yokai": [...]} を返す。"""
    m = re.search(r"\n==+\s*Characters\s*==+(.*?)(?=\n==[^=]|\Z)", text, re.S | re.I)
    if not m:
        return {"humans": [], "yokai": []}
    body = m.group(1)
    out: dict[str, list[tuple[str, str]]] = {"humans": [], "yokai": []}
    current: str | None = None
    for line in body.splitlines():
        head = re.match(r"\s*=+\s*(Humans?|Yo-?kai)\s*=+\s*$", line, re.I)
        if head:
            current = "humans" if head.group(1).lower().startswith("human") else "yokai"
            continue
        if current is None or not line.strip().startswith("*"):
            continue
        links = RE_LINK.findall(line)
        if not links:
            continue  # リンクなし行は破棄（"* Classic Yo-kai Trio"）
        tail = line[line.rfind("]]") + 2 :]
        note_m = RE_TRAILING_NOTE.search(tail)
        note = note_m.group(1) if note_m else ""
        for inner in links:
            out[current].append((inner, note))
    return out


# ---------------------------------------------------------------------------
# エピソード（SPEC.md §5.11 / §5.12）
# ---------------------------------------------------------------------------

RE_EP_TITLE = re.compile(r"^EP(\d{3})$")
RE_MN_TITLE = re.compile(r"^MN(\d{3})$")

MONTHS = {
    m: i
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}
RE_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")


def parse_air_date(value: str) -> str | None:
    """"January 8, 2014" -> "2014-01-08"。複数ある場合は最初を採る。"""
    m = RE_DATE.search(clean_value(value))
    if not m:
        return None
    month = MONTHS.get(m.group(1).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2))).isoformat()
    except ValueError:
        return None


def lead_section(text: str) -> str:
    """最初の "==" 見出しより前（SPEC.md §5.12）。"""
    m = re.search(r"\n==", text)
    return text[: m.start()] if m else text


def extract_translations(text: str) -> list[tuple[str, str]]:
    """lead 段落の {{translation|en|ja|romaji}} を出現順に返す。第3引数は使わない。"""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"\{\{\s*translation\s*\|", text, re.I):
        blk = extract_braced(text, m.start())
        if not blk:
            continue
        parts = split_params(blk[2:-2])[1:]
        if len(parts) < 2:
            continue
        en = clean_value(parts[0])
        ja = clean_value(parts[1])
        if ja:
            out.append((en, ja))
    return out


def detect_series(title: str, prefix_param: str) -> tuple[str | None, str | None]:
    """ページ名を主、prefix を照合に使う（SPEC.md §5.11 / D-20260815-06）。

    戻り値は (series, conflict_reason)。

    §5.11 は「ページ名 MN\\d{3} かつ prefix = MN」を求めているが、
    `{{episode}}` 本体に prefix を持たない MN 話が実在する（例: MN090）。
    prefix を必須にすると♪が32話落ちるため、**prefix は在るときだけ照合する**。
    EX011 / EX012 を弾くという §5.11 の目的はページ名の判定だけで達成できる。
    """
    prefix = normalize_spaces(prefix_param).upper()
    if RE_EP_TITLE.match(title):
        if prefix and prefix != "EP":
            return None, f"page=EP prefix={prefix}"
        return "gen1", None
    if RE_MN_TITLE.match(title):
        if prefix and prefix != "MN":
            return None, f"page=MN prefix={prefix}"
        return "uta", None
    return None, None


# ---------------------------------------------------------------------------
# 妖怪 / キャラクター
# ---------------------------------------------------------------------------


def first_param(params: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = params.get(key)
        if value and clean_value(value):
            return clean_value(value)
    return ""


def clean_ja_name(value: str) -> str:
    """"天野景太 ''Amano Keita''" -> "天野景太"。ローマ字部分を落とす。"""
    value = strip_ruby(value)
    value = re.sub(r"''.*?''", "", value)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    return normalize_spaces(clean_value(value))


def pick_rank(cats: list[str], params: dict[str, str], page: str,
              reporter: Reports) -> str:
    """カテゴリ優先、infobox で補完（SPEC.md §5.4）。"""
    cat_ranks: list[str] = []
    for cat in cats:
        m = RE_RANK_CAT.match(cat)
        if m:
            value = m.group(1).upper()
            if value in RANK_ENUM and value not in cat_ranks:
                cat_ranks.append(value)
    info = first_param(params, RANK_KEYS).upper()
    info = info if info in RANK_ENUM else ""

    if len(cat_ranks) == 1:
        chosen = cat_ranks[0]
        if info and info != chosen:
            reporter.conflicts.append(
                {"page": page, "field": "rank", "category": chosen,
                 "infobox": info, "adopted": chosen})
        return chosen
    if len(cat_ranks) > 1:
        chosen = info if info in cat_ranks else min(cat_ranks, key=RANK_ENUM.index)
        reporter.conflicts.append(
            {"page": page, "field": "rank", "category": "|".join(cat_ranks),
             "infobox": info or "", "adopted": chosen})
        return chosen
    return info or "unknown"


def pick_attribute(cats: list[str], params: dict[str, str], page: str,
                   reporter: Reports) -> str:
    cat_values: list[str] = []
    for cat in cats:
        m = RE_ATTR_CAT.match(cat)
        if m:
            value = ATTRIBUTE_FIX.get(m.group(1).lower(), m.group(1).lower())
            if value in ATTRIBUTE_ENUM and value not in cat_values:
                cat_values.append(value)
    info = first_param(params, ATTRIBUTE_KEYS).lower()
    info = ATTRIBUTE_FIX.get(info, info)
    info = info if info in ATTRIBUTE_ENUM else ""
    if cat_values:
        chosen = cat_values[0]
        if info and info != chosen:
            reporter.conflicts.append(
                {"page": page, "field": "attribute", "category": "|".join(cat_values),
                 "infobox": info, "adopted": chosen})
        return chosen
    return info or "unknown"


def pick_tribes(cats: list[str], params: dict[str, str], page: str,
                reporter: Reports) -> tuple[str, str | None]:
    gen1: list[str] = []
    ss: list[str] = []
    for cat in cats:
        m = RE_TRIBE_CAT.match(cat)
        if not m:
            continue
        name = normalize_spaces(m.group(1)).capitalize() if m.group(1).islower() \
            else normalize_spaces(m.group(1))
        if name in GEN1_TRIBES and name not in gen1:
            gen1.append(name)
        elif name in SS_TRIBES and name not in ss:
            ss.append(name)
    info = first_param(params, TRIBE_KEYS)
    info_norm = info.replace(" Tribe", "").strip()
    if not gen1 and info_norm in GEN1_TRIBES:
        gen1.append(info_norm)
    info_ss = first_param(params, TRIBE_SS_KEYS).replace(" Tribe", "").strip()
    if not ss and info_ss in SS_TRIBES:
        ss.append(info_ss)
    if gen1 and info_norm in GEN1_TRIBES and info_norm != gen1[0]:
        reporter.conflicts.append(
            {"page": page, "field": "tribe", "category": "|".join(gen1),
             "infobox": info_norm, "adopted": gen1[0]})
    return (gen1[0] if gen1 else "unknown", ss[0] if ss else None)


def parse_yokai(title: str, text: str, cats: list[str], params: dict[str, str],
                reporter: Reports) -> dict[str, Any]:
    rank = pick_rank(cats, params, title, reporter)
    attribute = pick_attribute(cats, params, title, reporter)
    tribe, tribe_ss = pick_tribes(cats, params, title, reporter)

    role = "unknown"
    for cat in cats:
        m = RE_ROLE_CAT.match(cat)
        if m and m.group(1) in ROLE_ENUM:
            role = m.group(1)
            break

    yokai_type = first_param(params, TYPE_KEYS) or "unknown"
    if yokai_type == "unknown":
        for cat in cats:
            if cat in YOKAI_TYPE_CATEGORIES:
                yokai_type = YOKAI_TYPE_CATEGORIES[cat]
                break

    family = None
    for cat in cats:
        m = RE_VARIANTS_CAT.match(cat)
        if m:
            family = normalize_spaces(m.group(1))
            break

    # 日本語名は {{language}} の ja-name を最優先（SPEC.md §5.7）
    name_ja = ""
    lang_block = find_template(text, r"language")
    if lang_block:
        lang_params = parse_template_params(lang_block)
        name_ja = clean_ja_name(lang_params.get("ja-name", ""))
    if not name_ja:
        name_ja = clean_ja_name(first_param(params, NAME_JA_KEYS))
    if not name_ja:
        tr = extract_translations(text)
        if tr:
            name_ja = clean_ja_name(tr[0][1])

    foods: list[str] = []
    for key in FOOD_KEYS:
        if key in params:
            for value in split_multi(clean_value(params[key])):
                if value and value not in foods:
                    foods.append(value)
    bad: list[str] = []
    for key in BADFOOD_KEYS:
        if key in params:
            for value in split_multi(clean_value(params[key])):
                if value and value not in bad:
                    bad.append(value)

    medallium = {}
    for key in MEDALLIUM_KEYS:
        if key in params:
            value = clean_value(params[key])
            if value:
                medallium[key.replace(" ", "")] = split_multi(value)[0]

    return {
        "yokai_id": title,
        "name_en": first_param(params, ["name"]) or title,
        "name_ja": name_ja or "unknown",
        "name_romaji": first_param(params, NAME_ROMAJI_KEYS),
        "tribe": tribe,
        "tribe_ss": tribe_ss,
        "rank": rank,
        "attribute": attribute,
        "yokai_type": yokai_type,
        "role": role,
        "foods_loved": foods,
        "foods_disliked": bad,
        "family": family,
        "is_family_head": bool(family and family == title),
        "medallium_no": medallium,
        "introduced_in": None,          # 第一弾では実装しない（SPEC.md §5.14）
        "categories": cats,
        "appears_in": [],               # あとで逆引きを埋める
        "intro_ja": None,               # 第一弾では null（SPEC.md §14）
        "etymology_ja": None,
        "data_status": "full",
    }


def parse_character(title: str, text: str, params: dict[str, str]) -> dict[str, Any]:
    name_ja = ""
    lang_block = find_template(text, r"language")
    if lang_block:
        name_ja = clean_ja_name(parse_template_params(lang_block).get("ja-name", ""))
    if not name_ja:
        name_ja = clean_ja_name(first_param(params, NAME_JA_KEYS))
    return {
        "character_id": title,
        "name_en": first_param(params, ["name"]) or title,
        "name_ja": name_ja or "unknown",
        "appears_in": [],
        "data_status": "full" if name_ja else "partial",
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-title-mismatch", action="store_true",
                    help="titles.txt との集合差があっても続行する（既定は停止）")
    args = ap.parse_args()

    if not RAW.exists():
        print(f"ERROR: {RAW} がない。raw/fandom/ は人間が配置する（SPEC.md §5.1）",
              file=sys.stderr)
        return 2

    reporter = Reports()

    # --- 読み込みと自己検証（SPEC.md §5.13）--------------------------------
    result = load_pages(RAW)
    titles = load_titles(RAW / "titles.txt")
    in_xml = set(result.pages)
    in_titles = set(titles)
    only_titles = sorted(in_titles - in_xml)
    only_xml = sorted(in_xml - in_titles)

    print("=" * 66)
    print("Fandom XML パース（SPEC.md §5）")
    print("=" * 66)
    print(f"  <page> の総数            {result.raw_count:,}")
    print(f"  重複タイトル             {len(result.duplicates)} 件 "
          f"{result.duplicates[:4]}")
    print(f"  重複排除後               {len(result.pages):,}")
    print(f"  titles.txt               {len(titles):,}")
    print(f"  本文が空のページ         {len(result.empty_text)} 件")
    print(f"  集合差 titles.txt のみ   {len(only_titles)} 件")
    print(f"  集合差 XML のみ          {len(only_xml)} 件")

    if only_titles or only_xml:
        print("\nERROR: titles.txt と XML の集合が一致しない（SPEC.md §5.13）",
              file=sys.stderr)
        for t in only_titles[:10]:
            print(f"  titles.txt のみ: {t}", file=sys.stderr)
        for t in only_xml[:10]:
            print(f"  XML のみ:        {t}", file=sys.stderr)
        if not args.allow_title_mismatch:
            print("取りこぼしの可能性がある。--allow-title-mismatch で続行可能。",
                  file=sys.stderr)
            return 1

    pages = result.pages

    # --- 分類（SPEC.md §5.13 の2）------------------------------------------
    redirects = build_redirects(pages)
    kinds: dict[str, str] = {}
    namespace_skipped = 0
    for title, text in pages.items():
        if ":" in title and title.split(":", 1)[0] in {
            "File", "Category", "Template", "Help", "User", "Module",
            "MediaWiki", "Talk", "Board", "Forum", "Blog",
        }:
            namespace_skipped += 1
            continue
        if title in redirects:
            kinds[title] = "redirect"
        elif re.search(r"\{\{\s*yo-?kai\s*[|}]", text, re.I):
            # 妖怪優先（D-20260815-01）。{{character}} と併存する6件はここで妖怪になる。
            kinds[title] = "yokai"
        elif re.search(r"\{\{\s*character\s*[|}]", text, re.I):
            kinds[title] = "character"
        elif re.search(r"\{\{\s*episode\s*[|}]", text, re.I):
            kinds[title] = "episode"
        else:
            kinds[title] = "unclassified"

    counts = Counter(kinds.values())
    print(f"\n  妖怪                     {counts['yokai']:,}")
    print(f"  人間キャラ               {counts['character']:,}")
    print(f"  エピソード               {counts['episode']:,}")
    print(f"  リダイレクト             {counts['redirect']:,}")
    print(f"  unclassified             {counts['unclassified']:,}")
    print(f"  namespace_skipped        {namespace_skipped:,}")
    print(f"  合計                     {sum(counts.values()) + namespace_skipped:,}")

    # --- 妖怪 / キャラクター ------------------------------------------------
    yokai: dict[str, dict[str, Any]] = {}
    characters: dict[str, dict[str, Any]] = {}
    for title, kind in kinds.items():
        if kind not in ("yokai", "character"):
            continue
        text = pages[title]
        cats = extract_categories(text)
        pattern = r"yo-?kai" if kind == "yokai" else r"character"
        block = find_template(text, pattern)
        params = parse_template_params(block) if block else {}
        params.pop("image", None)  # 画像は値を破棄する（SPEC.md §2.1）
        for key, value in params.items():
            if key not in KNOWN_PARAMS:
                reporter.unknown_params.append(
                    {"page": title, "param": key,
                     "sample": clean_value(value)[:60]})
        if kind == "yokai":
            yokai[title] = parse_yokai(title, text, cats, params, reporter)
        else:
            characters[title] = parse_character(title, text, params)

    # --- 名前解決の準備（SPEC.md §5.9 / §5.10）-----------------------------
    overrides = load_overrides(OVERRIDES / "unresolved_yokai.csv")
    known = set(pages)

    def resolve(link: str, page: str, section: str) -> str | None:
        target = parse_link_target(link)
        if not target:
            return None
        candidates = [target]
        stripped = re.sub(r"\s*\(anime\)$", "", target)
        if stripped != target:
            candidates.append(stripped)   # (anime) は剥がす
        else:
            candidates.append(f"{target} (anime)")  # 逆方向も試す
        for cand in candidates:
            if cand in known:
                return resolve_redirect(cand, redirects)
        for cand in candidates:
            if cand in overrides:
                return resolve_redirect(overrides[cand], redirects)
        reporter.unresolved.append(
            {"episode": page, "section": section, "link": target})
        return None

    # --- エピソードとセグメント（SPEC.md §5.11 / §5.12）--------------------
    episodes: dict[str, dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    prefix_counter: Counter[str] = Counter()
    out_of_scope = 0

    for title, kind in kinds.items():
        if kind != "episode":
            continue
        text = pages[title]
        block = find_template(text, r"episode")
        params = parse_template_params(block) if block else {}
        params.pop("image", None)
        prefix_counter[normalize_spaces(params.get("prefix", "")) or "(none)"] += 1

        series, conflict = detect_series(title, params.get("prefix", ""))
        if conflict:
            reporter.conflicts.append(
                {"page": title, "field": "series", "category": title[:2],
                 "infobox": conflict, "adopted": "除外"})
        if series is None:
            out_of_scope += 1
            continue

        no = int((RE_EP_TITLE.match(title) or RE_MN_TITLE.match(title)).group(1))
        chars = parse_characters_section(text)
        yk_list: list[dict[str, Any]] = []
        hu_list: list[dict[str, Any]] = []
        for link, note in chars["yokai"]:
            resolved = resolve(link, title, "Yo-kai")
            if not resolved or resolved not in yokai:
                if resolved and resolved not in yokai:
                    reporter.unresolved.append(
                        {"episode": title, "section": "Yo-kai",
                         "link": f"{resolved} (妖怪として未登録)"})
                continue
            presence, is_debut = fold_presence(note, reporter, title, link)
            yk_list.append({"yokai_id": resolved, "presence": presence,
                            "is_debut": is_debut})
        for link, note in chars["humans"]:
            resolved = resolve(link, title, "Humans")
            if not resolved:
                continue
            presence, is_debut = fold_presence(note, reporter, title, link)
            if resolved in characters:
                hu_list.append({"character_id": resolved, "presence": presence,
                                "is_debut": is_debut})
            elif resolved in yokai:
                # Humans 節に妖怪リンクが置かれている場合がある。妖怪側へ寄せる。
                yk_list.append({"yokai_id": resolved, "presence": presence,
                                "is_debut": is_debut})

        # セグメント（lead 段落限定）
        translations = extract_translations(lead_section(text))
        title_en_param = clean_value(params.get("episode title", ""))
        en_titles = split_multi(title_en_param) if title_en_param else []
        if en_titles and len(en_titles) != len(translations):
            reporter.segment_title_mismatch.append(
                {"episode": title, "translations": len(translations),
                 "episode_title_parts": len(en_titles)})
            en_titles = []
        elif not en_titles and translations:
            reporter.segment_title_mismatch.append(
                {"episode": title, "translations": len(translations),
                 "episode_title_parts": 0})

        for seq, (en, ja) in enumerate(translations, start=1):
            segments.append({
                "segment_id": f"{title}-{seq}",
                "episode_id": title,
                "seq": seq,
                "title_ja": ja,
                "title_ja_norm": normalize_title_key(ja),
                "title_en": en_titles[seq - 1] if len(en_titles) == len(translations) else (en or None),
                "yotube_no": None,
                "yotube_video_id": None,
                "is_recurring": False,   # PR4 で判定する（SPEC.md §5.14）
                "synopsis_ja": None,
                "keywords": None,
                "data_status": "partial",
            })

        staff = {k: clean_value(params[k]) for k in
                 ("screenplay", "storyboard", "director", "amindirector", "animation")
                 if params.get(k)}
        episodes[title] = {
            "episode_id": title,
            "kind": "tv",
            "series": series,
            "prefix": "EP" if series == "gen1" else "MN",
            "episode_no": no,
            "title_ja_full": None,      # 第一弾では常に null（D-20260815-04）
            "air_date": parse_air_date(params.get("japan", "")),
            "staff": staff,
            "opening": clean_value(params.get("j-opening", "")) or None,
            "ending": clean_value(params.get("j-ending", "")) or None,
            "yokai": yk_list,
            "humans": hu_list,
            "data_status": "full" if yk_list else "partial",
        }

    # --- 逆引き -------------------------------------------------------------
    for ep_id, ep in episodes.items():
        for entry in ep["yokai"]:
            rec = yokai.get(entry["yokai_id"])
            if rec is not None and ep_id not in rec["appears_in"]:
                rec["appears_in"].append(ep_id)
        for entry in ep["humans"]:
            rec = characters.get(entry["character_id"])
            if rec is not None and ep_id not in rec["appears_in"]:
                rec["appears_in"].append(ep_id)

    # --- 欠番チェック（SPEC.md §5.13 の3）----------------------------------
    print("\n  prefix 別の内訳")
    for key, value in sorted(prefix_counter.items()):
        print(f"    {key:<8} {value:>4}")
    print(f"  スコープ外として除外     {out_of_scope}")

    by_series: dict[str, list[int]] = defaultdict(list)
    for ep in episodes.values():
        by_series[ep["series"]].append(ep["episode_no"])
    for series, numbers in sorted(by_series.items()):
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        print(f"    {series:<6} {len(numbers):>4} 件  1-{max(numbers)}  "
              f"欠番 {len(missing)} {missing[:8]}")

    seg_by_series: Counter[str] = Counter()
    for seg in segments:
        seg_by_series[episodes[seg["episode_id"]]["series"]] += 1
    print(f"\n  セグメント               {len(segments):,} "
          f"({dict(seg_by_series)})")

    # --- 出力 ---------------------------------------------------------------
    report_counts = reporter.write(REPORTS)
    print("\n  レポート（reports/）")
    for name, count in report_counts.items():
        print(f"    {name:<30} {count:>6}")

    BUILD.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_from": "raw/fandom/*.xml",
        "counts": {
            "pages": len(pages),
            "yokai": len(yokai),
            "characters": len(characters),
            "episodes": len(episodes),
            "segments": len(segments),
            "redirects": len(redirects),
            "namespace_skipped": namespace_skipped,
            "unclassified": counts["unclassified"],
        },
        "reports": report_counts,
        "yokai": list(yokai.values()),
        "characters": list(characters.values()),
        "episodes": list(episodes.values()),
        "segments": segments,
    }
    out_path = BUILD / "fandom.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  書き出し                 {out_path.relative_to(ROOT)} "
          f"({out_path.stat().st_size / 1_048_576:.1f} MB)")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
