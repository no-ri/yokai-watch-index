#!/usr/bin/env python3
"""妖Tube から動画の棚卸しをする（SPEC.md §3.3 / §7）。

    python3 scripts/fetch_youtube.py            # API から取得
    python3 scripts/fetch_youtube.py --cached   # raw/youtube/ の保存分で再計算

入力   .env の YT_API_KEY
出力   raw/youtube/uploads.json  一時保存（gitignore）
       build/youtube.json        video_id と自作ラベルのみ
       reports/youtube_noise.csv 除外した動画の内訳

**永続化してよいのは video_id と自作ラベルだけ**（SPEC.md §2.4）。
title / description / publishedAt / duration は build/ にも docs/ にも入れない。
raw/youtube/ は一時保存で gitignore の対象。

**search.list を使ってはならない**（1回100ユニット）。
playlistItems.list（1ユニット/50件）のみ使う（SPEC.md §3.3）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikitext import normalize_title_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_YT = ROOT / "raw" / "youtube"
BUILD = ROOT / "build"
REPORTS = ROOT / "reports"

CHANNEL_ID = "UCvudj1z5SLEkOw-Jiu63IYg"
# アップロードプレイリストは UC -> UU で導出できる（SPEC.md §3.3）
UPLOADS_PLAYLIST_ID = "UU" + CHANNEL_ID[2:]
API = "https://www.googleapis.com/youtube/v3/playlistItems"

# --- ノイズの除外（SPEC.md §7.2）-------------------------------------------
RE_SHORTS = re.compile(r"#shorts", re.I)
RE_MATOME = re.compile(r"まとめ")
PREFIX_OFFICIAL = "【公式】"

# --- 話数番号（SPEC.md §7.4）------------------------------------------------
# # は半角と全角（＃）の両方が使われる
RE_UTA = re.compile(r"妖怪ウォッチ♪\s*[#＃]\s*(\d+)")
RE_GEN1 = re.compile(r"妖怪ウォッチ\s*[#＃]\s*(\d+)")

# --- あらすじブロック（SPEC.md §7.3）----------------------------------------
# 説明欄の先頭は定型文（約330文字）なので、文字数では判定できない。
RE_SYNOPSIS = re.compile(r"【([^】]{2,40})】\s*\n+(.{60,})", re.S)


def load_api_key() -> str:
    env = ROOT / ".env"
    if not env.exists():
        raise SystemExit("ERROR: .env がない。.env.example を参照（SPEC.md §7.1）")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("YT_API_KEY"):
            return line.partition("=")[2].strip().strip("\"'")
    raise SystemExit("ERROR: .env に YT_API_KEY がない")


def fetch_uploads(api_key: str) -> list[dict[str, Any]]:
    """アップロードプレイリストを全件走査する。1ページ50件＝1ユニット。"""
    items: list[dict[str, Any]] = []
    token: str | None = None
    units = 0
    while True:
        query = {
            "part": "snippet",
            "playlistId": UPLOADS_PLAYLIST_ID,
            "maxResults": "50",
            "key": api_key,
        }
        if token:
            query["pageToken"] = token
        url = f"{API}?{urllib.parse.urlencode(query)}"
        try:
            with urllib.request.urlopen(url, timeout=30) as res:
                payload = json.load(res)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"ERROR: YouTube API {exc.code}\n{body}") from exc
        units += 1
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            items.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
            })
        token = payload.get("nextPageToken")
        print(f"\r  取得中 {len(items):,} 件 / {units} ユニット", end="", flush=True)
        if not token:
            break
        time.sleep(0.1)
    print()
    return items


def classify(item: dict[str, Any]) -> tuple[str | None, str]:
    """(除外理由 or None, "") を返す。除外理由が None なら本編候補。"""
    title = item["title"]
    desc = item["description"]
    if RE_SHORTS.search(title) or RE_SHORTS.search(desc):
        return "shorts", ""
    if RE_MATOME.search(title):
        return "matome", ""
    if not title.startswith(PREFIX_OFFICIAL):
        return "not_official", ""
    return None, ""


def parse_series_no(title: str) -> tuple[str | None, int | None]:
    """タイトルからシリーズと話数番号を取る（SPEC.md §7.4）。

    ♪ の判定を先に行う。"妖怪ウォッチ♪ #1" は "妖怪ウォッチ #..." にも
    部分一致してしまうため、順序を逆にすると全部が初代に落ちる。
    """
    m = RE_UTA.search(title)
    if m:
        return "uta", int(m.group(1))
    m = RE_GEN1.search(title)
    if m:
        return "gen1", int(m.group(1))
    return None, None


def extract_synopsis_key(item: dict[str, Any]) -> tuple[str | None, bool]:
    """説明欄の 【サブタイトル】 を取る。戻り値は (サブタイトル, あらすじ有無)。

    サブタイトル自体は事実データ（話のタイトル）なので突合キーに使う。
    **本文（あらすじ）は返さない。**有無だけを bool で返す（SPEC.md §2.2 / §2.4）。
    """
    m = RE_SYNOPSIS.search(item["description"])
    if not m:
        # 【...】 はあるが本文が短い場合も拾っておく
        m2 = re.search(r"【([^】]{2,40})】", item["description"])
        return (m2.group(1).strip() if m2 else None), False
    return m.group(1).strip(), True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cached", action="store_true",
                    help="API を叩かず raw/youtube/uploads.json を使う")
    args = ap.parse_args()

    cache = RAW_YT / "uploads.json"
    if args.cached:
        if not cache.exists():
            raise SystemExit(f"ERROR: {cache} がない。--cached なしで実行する")
        items = json.loads(cache.read_text(encoding="utf-8"))
        print(f"  キャッシュから {len(items):,} 件")
    else:
        print("=" * 66)
        print("妖Tube 棚卸し（SPEC.md §7）")
        print("=" * 66)
        items = fetch_uploads(load_api_key())
        RAW_YT.mkdir(parents=True, exist_ok=True)
        # 一時保存。gitignore の対象で、build/ にも docs/ にも持ち出さない（§2.4）
        cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    print(f"\n  総動画数                 {len(items):,}")

    noise: list[dict[str, str]] = []
    reasons: Counter[str] = Counter()
    main_candidates: list[dict[str, Any]] = []
    for item in items:
        reason, _ = classify(item)
        if reason:
            reasons[reason] += 1
            noise.append({"video_id": item["video_id"], "reason": reason})
            continue
        main_candidates.append(item)

    print(f"  #shorts                  {reasons['shorts']:,}")
    print(f"  「まとめ」               {reasons['matome']:,}")
    print(f"  【公式】でない           {reasons['not_official']:,}")
    print(f"  本編候補                 {len(main_candidates):,}")

    records: list[dict[str, Any]] = []
    seen_no: dict[tuple[str, int], str] = {}
    duplicates: list[dict[str, str]] = []
    unnumbered = 0
    for item in main_candidates:
        series, no = parse_series_no(item["title"])
        subtitle, has_synopsis = extract_synopsis_key(item)
        if series is None:
            unnumbered += 1
        else:
            key = (series, no)
            if key in seen_no:
                # 同じ番号の動画が2本ある（実測: ♪ #186）。先勝ちにして記録する。
                duplicates.append({"video_id": item["video_id"],
                                   "reason": f"duplicate_no:{series}#{no}"})
                continue
            seen_no[key] = item["video_id"]
        records.append({
            "video_id": item["video_id"],
            "series": series,
            "yotube_no": no,
            # 突合キー。正規化済みで、原文そのものではない（SPEC.md §8.1）
            "title_norm": normalize_title_key(
                re.sub(r"^【公式】[^#＃]*[#＃]\s*\d+\s*", "", item["title"])),
            "desc_title_norm": normalize_title_key(subtitle) if subtitle else None,
            "has_synopsis": has_synopsis,
        })

    print(f"\n  シリーズ別（本編候補）")
    for series in ("gen1", "uta"):
        nums = [r["yotube_no"] for r in records if r["series"] == series]
        if not nums:
            continue
        missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        print(f"    {series:<6} {len(nums):>4} 本  #{min(nums)}〜#{max(nums)}  "
              f"欠番 {len(missing)}")
    print(f"    その他/番号なし {unnumbered:>4} 本")
    if duplicates:
        print(f"    番号の重複      {len(duplicates):>4} 本（先勝ちで採用）")

    # --- A1 ゲートの材料（SPEC.md §11.2）-----------------------------------
    in_scope = [r for r in records if r["series"] in ("gen1", "uta")]
    with_syn = [r for r in in_scope if r["has_synopsis"]]
    print("\n" + "-" * 66)
    print("A1 ゲート（SPEC.md §11.2）")
    print("-" * 66)
    print("  分母は「動画が対応するセグメント」。ここでは初代＋♪の本編動画で近似する。")
    print(f"  初代＋♪の本編動画       {len(in_scope):,}")
    print(f"  【...】ブロックあり     {len(with_syn):,}")
    if in_scope:
        rate = len(with_syn) / len(in_scope)
        print(f"  充足率                   {rate:.1%}  (合格基準 80%)")
        print(f"  判定                     {'通過' if rate >= 0.80 else '不合格'}")
    for series in ("gen1", "uta"):
        sub = [r for r in in_scope if r["series"] == series]
        if sub:
            ok = sum(1 for r in sub if r["has_synopsis"])
            print(f"    {series:<6} {ok:>4} / {len(sub):<4} = {ok / len(sub):.1%}")
    print("  ※ 突合後の確定値は PR5 で再計算する。")
    print("-" * 66)

    REPORTS.mkdir(parents=True, exist_ok=True)
    with (REPORTS / "youtube_noise.csv").open(
            "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["video_id", "reason"])
        writer.writeheader()
        writer.writerows(noise + duplicates)

    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "youtube.json").write_text(
        json.dumps({"total": len(items), "records": records},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n  書き出し                 build/youtube.json ({len(records):,} 件)")
    print(f"  除外の記録               reports/youtube_noise.csv ({len(noise):,} 件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
