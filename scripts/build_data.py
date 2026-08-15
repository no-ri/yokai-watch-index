#!/usr/bin/env python3
"""公開データ docs/data/*.json を生成する（SPEC.md §2.2 / §9 / §14.3）。

    python3 scripts/build_data.py

入力   build/fandom.json, build/segments_matched.json, overrides/movies.csv
出力   docs/data/{yokai,characters,episodes,segments,facets}.json
       docs/data/LICENSE, docs/data/ATTRIBUTION.md

**禁止キー検査**（SPEC.md §2.2）:
出力 JSON に plot / description / etymology_raw / personality_raw /
medallium_raw のいずれかが含まれていたら、書き出す前にビルドを失敗させる。
人間の注意力に頼らず、機械で強制する。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
OVERRIDES = ROOT / "overrides"
DATA = ROOT / "docs" / "data"

# SPEC.md §2.2。取得元の原文をサイトに出さないための機械的な歯止め。
FORBIDDEN_KEYS = {
    "plot", "description", "etymology_raw", "personality_raw", "medallium_raw",
}


class ForbiddenKeyError(RuntimeError):
    pass


def assert_no_forbidden_keys(payload: Any, path: str = "$") -> None:
    """再帰的に禁止キーを探す。1つでもあれば例外を投げる（SPEC.md §2.2）。"""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ForbiddenKeyError(
                    f"禁止キー '{key}' が {path} にある（SPEC.md §2.2）。"
                    "取得元の原文を公開データに含めてはならない。")
            assert_no_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            assert_no_forbidden_keys(item, f"{path}[{i}]")


# --- 絞り込み軸（SPEC.md §9.1）----------------------------------------------
# 軸の値は yokai.categories から UI 側で導出する。ここは対応表だけを持つ。

FACETS: dict[str, dict[str, str]] = {
    "tribe": {
        "Charming": "プリチー族", "Brave": "イサマシ族", "Shady": "ウスラカゲ族",
        "Tough": "ゴーケツ族", "Slippery": "ニョロロン族",
        "Mysterious": "フシギ族", "Heartful": "ポカポカ族", "Eerie": "ブキミー族",
    },
    "rank": {"E": "E", "D": "D", "C": "C", "B": "B", "A": "A", "S": "S", "SS": "SS"},
    "attribute": {
        "fire": "火", "water": "水", "lightning": "雷", "ice": "氷",
        "earth": "土", "wind": "風", "drain": "吸", "restoration": "回",
    },
    "color": {
        "White Yo-kai": "白", "Blue Yo-kai": "青", "Red Yo-kai": "赤",
        "Black Yo-kai": "黒", "Yellow Yo-kai": "黄", "Purple Yo-kai": "紫",
        "Green Yo-kai": "緑", "Pink Yo-kai": "ピンク", "Grey Yo-kai": "灰",
        "Brown Yo-kai": "茶", "Orange Yo-kai": "オレンジ",
    },
    "animal": {
        "Humanoid Yo-kai": "人型", "Animal Yo-kai": "動物", "Cat Yo-kai": "ネコ",
        "Dog Yo-kai": "イヌ", "Dragon Yo-kai": "ドラゴン", "Oni Yo-kai": "鬼",
        "Bird Yo-kai": "鳥", "Robot Yo-kai": "ロボット", "Fish Yo-kai": "魚",
    },
    "special": {
        "Boss Yo-kai": "ボス", "Rare Yo-kai": "レア",
        "Present Yo-kai": "プレゼント", "Legendary Yo-kai": "レジェンド",
    },
}

FOOD_LABELS = {
    "Sweets": "スイーツ", "Meat": "肉", "Chocobars": "チョコボー",
    "Seafood": "海鮮", "Ice Cream": "アイス", "Vegetables": "野菜",
    "Candy": "アメ", "Milk": "ミルク", "Rice Balls": "おにぎり",
    "Curry": "カレー", "Sushi": "寿司", "Juice": "ジュース", "Soba": "そば",
    "Hamburgers": "ハンバーガー", "Bread": "パン", "Ramen": "ラーメン",
    "Tempura": "天ぷら", "Chinese Food": "中華", "Sukiyaki": "すき焼き",
    "Oden": "おでん", "Snacks": "スナック", "Pizza": "ピザ", "Donuts": "ドーナツ",
    "Hamburger": "ハンバーガー",
}


def build_facets(yokai: list[dict[str, Any]]) -> dict[str, Any]:
    """実際に使われているカテゴリだけを対応表に載せる。"""
    used: Counter[str] = Counter()
    for rec in yokai:
        for cat in rec["categories"]:
            used[cat] += 1

    facets: dict[str, Any] = {}
    for axis in ("color", "animal", "special"):
        facets[axis] = {cat: label for cat, label in FACETS[axis].items()
                        if used.get(cat)}
    for axis in ("tribe", "rank", "attribute"):
        facets[axis] = dict(FACETS[axis])

    for axis, prefix in (("food", "Yo-kai That Love "),
                         ("badfood", "Yo-kai That Despise ")):
        entries: dict[str, str] = {}
        for cat, count in used.items():
            if cat.startswith(prefix) and count >= 10:
                name = cat[len(prefix):]
                entries[cat] = FOOD_LABELS.get(name, name)
        facets[axis] = dict(sorted(entries.items(), key=lambda kv: -used[kv[0]]))

    families = sorted({r["family"] for r in yokai if r["family"]})
    facets["family"] = {name: name for name in families}
    return facets


def load_movies() -> list[dict[str, Any]]:
    """劇場版は overrides/movies.csv から構成する（SPEC.md §5.15）。"""
    path = OVERRIDES / "movies.csv"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            episode_id = (row.get("episode_id") or "").strip()
            if not episode_id:
                continue
            year = (row.get("year") or "").strip()
            out.append({
                "episode_id": episode_id,
                "kind": "movie",
                "series": "movie",
                "prefix": "M",
                "episode_no": int("".join(filter(str.isdigit, episode_id)) or 0),
                "title_ja_full": (row.get("title_ja") or "").strip() or None,
                "air_date": f"{year}-01-01" if year.isdigit() else None,
                "staff": {},
                "opening": None,
                "ending": None,
                "yokai": [],
                "humans": [],
                "data_status": "none",
            })
    return out


def write_json(path: Path, payload: Any) -> int:
    # 書き出す前に必ず検査する（SPEC.md §2.2）
    assert_no_forbidden_keys(payload, f"${path.name}")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


LICENSE_TEXT = """Creative Commons Attribution-ShareAlike (CC BY-SA)

このディレクトリ（docs/data/）の JSON は CC BY-SA で提供します。

由来:
  Yo-kai Watch Wiki (Fandom) — https://yokaiwatch.fandom.com/
  CC BY-SA（テキストのみ。画像は対象外）

派生物であるため ShareAlike が及びます。再利用する場合は、
同じライセンスで提供し、出典を表示してください。

詳細は ATTRIBUTION.md を参照してください。
なお本リポジトリの**コード**は MIT です（ルートの LICENSE）。

全文: https://creativecommons.org/licenses/by-sa/4.0/
"""


def attribution_text(counts: dict[str, int]) -> str:
    return f"""# 出典

本サイトは非公式のファンサイトです。
妖怪ウォッチは株式会社レベルファイブの商標です。 (C) LEVEL-5 Inc.

## データ

| ソース | ライセンス | 取得方法 | 取得日 |
|---|---|---|---|
| [Yo-kai Watch Wiki (Fandom)](https://yokaiwatch.fandom.com/) | CC BY-SA（テキストのみ） | 人間による `Special:Export` | 2026-08-15 |
| 妖怪ウォッチ公式YouTubeチャンネル「妖Tube」 | YouTube 利用規約に準拠 | YouTube Data API v3 | 2026-08-15 |

## 生成物の内訳

| ファイル | 件数 |
|---|---|
| `yokai.json` | {counts['yokai']:,} |
| `characters.json` | {counts['characters']:,} |
| `episodes.json` | {counts['episodes']:,} |
| `segments.json` | {counts['segments']:,} |

## 扱っていないもの

- **画像**（Fandom の画像は CC BY-SA の対象外のため、一切使用していません）
- 取得元の原文（あらすじ・解説などの散文）
- 妖Tube のタイトル・説明欄（保存しているのは `video_id` のみ）

## 加工について

事実データ（名前・話数・放送日・種族・ランク・属性など）のみを抽出し、
散文は含めていません。正規化と突合の規則は `SPEC.md` §5 と §8 に記載しています。

データの誤りにお気づきの場合は
[Issues](https://github.com/no-ri/yokai-watch-index/issues) までお知らせください。
"""


def main() -> int:
    fandom = json.loads((BUILD / "fandom.json").read_text(encoding="utf-8"))
    matched_path = BUILD / "segments_matched.json"
    if matched_path.exists():
        segments = json.loads(matched_path.read_text(encoding="utf-8"))["segments"]
    else:
        print("WARNING: build/segments_matched.json がない。突合前の状態で出力する",
              file=sys.stderr)
        segments = fandom["segments"]

    yokai = fandom["yokai"]
    characters = fandom["characters"]
    episodes = fandom["episodes"] + load_movies()

    # 出演のない妖怪も図鑑には出す。data_status で欠損を明示する（SPEC.md §12.5）
    for rec in yokai:
        if not rec["appears_in"]:
            rec["data_status"] = "partial"
    for ep in episodes:
        if ep["kind"] == "tv" and not ep["yokai"]:
            ep["data_status"] = "partial"

    DATA.mkdir(parents=True, exist_ok=True)
    print("=" * 66)
    print("公開データの生成（SPEC.md §2.2 / §9 / §14.3）")
    print("=" * 66)

    counts = {"yokai": len(yokai), "characters": len(characters),
              "episodes": len(episodes), "segments": len(segments)}

    try:
        sizes = {
            "yokai.json": write_json(DATA / "yokai.json", yokai),
            "characters.json": write_json(DATA / "characters.json", characters),
            "episodes.json": write_json(DATA / "episodes.json", episodes),
            "segments.json": write_json(DATA / "segments.json", segments),
            "facets.json": write_json(DATA / "facets.json", build_facets(yokai)),
        }
    except ForbiddenKeyError as exc:
        print(f"\nERROR: ビルドを中止した。\n  {exc}", file=sys.stderr)
        return 1

    print("  禁止キー検査             通過 "
          f"({'/'.join(sorted(FORBIDDEN_KEYS))})")
    total = 0
    for name, size in sizes.items():
        total += size
        print(f"  {name:<22} {size / 1024:>8.0f} KB")
    print(f"  {'合計':<21} {total / 1_048_576:>8.1f} MB")

    (DATA / "LICENSE").write_text(LICENSE_TEXT, encoding="utf-8")
    (DATA / "ATTRIBUTION.md").write_text(attribution_text(counts), encoding="utf-8")

    movies = [e for e in episodes if e["kind"] == "movie"]
    with_video = sum(1 for s in segments if s.get("yotube_video_id"))
    print(f"\n  妖怪 {counts['yokai']:,} / 人物 {counts['characters']:,} / "
          f"放送回 {counts['episodes']:,}（劇場版 {len(movies)}） / "
          f"セグメント {counts['segments']:,}")
    print(f"  動画があるセグメント     {with_video:,} / {counts['segments']:,}")
    if not movies:
        print("  ※ overrides/movies.csv が未配置のため劇場版は空（SPEC.md §5.15）")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
