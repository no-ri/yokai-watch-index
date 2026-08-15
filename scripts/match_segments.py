#!/usr/bin/env python3
"""Fandom のセグメントと妖Tube の動画を突合する（SPEC.md §8）。

    python3 scripts/match_segments.py

入力   build/fandom.json, build/youtube.json,
       overrides/segment_youtube_map.csv（任意）
出力   build/segments_matched.json
       reports/unmatched.csv

3段構え（SPEC.md §8.2）:
    段1  正規化後の完全一致
    段2  difflib.SequenceMatcher、cutoff = 0.85
    段3  番号の単調性による位置補間

突合失敗は必ず reports/unmatched.csv に出す。手動補正の入口として必須。
"""

from __future__ import annotations

import csv
import difflib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
REPORTS = ROOT / "reports"
OVERRIDES = ROOT / "overrides"

CUTOFF = 0.85           # SPEC.md §8.2
RECURRING_MIN_EPISODES = 5   # SPEC.md §5.14。閾値の妥当性は §17 U-8


def load(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"ERROR: {path} がない。先に前段のスクリプトを実行する")
    return json.loads(path.read_text(encoding="utf-8"))


def mark_recurring(segments: list[dict[str, Any]]) -> int:
    """定期ミニコーナーを識別する（SPEC.md §5.14）。

    コーナーはタイトルが毎回同じ、本編は毎回違う。
    同一 title_ja_norm が5話以上に登場するものをコーナーとみなす。
    """
    episodes_by_title: dict[str, set[str]] = defaultdict(set)
    for seg in segments:
        if seg["title_ja_norm"]:
            episodes_by_title[seg["title_ja_norm"]].add(seg["episode_id"])
    recurring = {t for t, eps in episodes_by_title.items()
                 if len(eps) >= RECURRING_MIN_EPISODES}
    for seg in segments:
        seg["is_recurring"] = seg["title_ja_norm"] in recurring
    return len(recurring)


def _longest_increasing(pairs: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """番号が単調増加になる最長の部分列を返す（O(n^2) で十分な規模）。"""
    if not pairs:
        return set()
    best = [1] * len(pairs)
    prev = [-1] * len(pairs)
    for i in range(len(pairs)):
        for j in range(i):
            if pairs[j][1] < pairs[i][1] and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j
    end = max(range(len(pairs)), key=lambda i: best[i])
    keep: set[tuple[int, int]] = set()
    while end != -1:
        keep.add(pairs[end])
        end = prev[end]
    return keep


def match_series(segments: list[dict[str, Any]], videos: list[dict[str, Any]],
                 unmatched: list[dict[str, Any]]) -> Counter[str]:
    """1シリーズ分を突合する。segments は放送順、videos は yotube_no 順。"""
    stats: Counter[str] = Counter()
    by_no = {v["yotube_no"]: v for v in videos}

    # 妖Tube 側の突合キー。説明欄の 【...】 を第一候補、タイトルを第二候補とする
    # （同一動画内で表記が揺れる実例があるため。SPEC.md §8.2）
    keys: dict[str, list[int]] = defaultdict(list)
    for v in videos:
        for key in (v.get("desc_title_norm"), v.get("title_norm")):
            if key:
                keys[key].append(v["yotube_no"])

    assigned: dict[int, str] = {}   # yotube_no -> segment_id
    max_no = max(by_no) if by_no else 0

    # --- 段1: 完全一致 ------------------------------------------------------
    for seg in segments:
        key = seg["title_ja_norm"]
        if not key:
            continue
        candidates = [n for n in keys.get(key, []) if n not in assigned]
        if len(candidates) == 1:
            seg["yotube_no"] = candidates[0]
            assigned[candidates[0]] = seg["segment_id"]
            stats["exact"] += 1

    # --- 段1.5: 単調性の強制 -----------------------------------------------
    # 妖Tube の #N は放送順なので、放送順に並べたセグメントの番号は
    # 単調増加でなければならない。破っているアンカーは誤マッチなので外す。
    # 最長増加部分列を残し、それ以外を解除する。
    idx_no = [(i, seg["yotube_no"]) for i, seg in enumerate(segments)
              if seg["yotube_no"] is not None]
    keep = _longest_increasing(idx_no)
    for i, no in idx_no:
        if (i, no) not in keep:
            segments[i]["yotube_no"] = None
            del assigned[no]
            stats["exact"] -= 1
            stats["dropped_nonmonotonic"] += 1

    # --- 段2: difflib（アンカー間に限定）------------------------------------
    # 候補を前後のアンカーで挟まれた範囲に絞る。範囲を無視すると、
    # 似たタイトルの別セグメント（「コマさんの〜」等）に飛ぶ。
    def window(index: int) -> tuple[int, int]:
        low = 0
        high = max_no
        for i, seg in enumerate(segments):
            if seg["yotube_no"] is None:
                continue
            if i < index:
                low = seg["yotube_no"]
            elif i > index:
                high = seg["yotube_no"]
                break
        return low, high

    for index, seg in enumerate(segments):
        if seg["yotube_no"] is not None or not seg["title_ja_norm"]:
            continue
        low, high = window(index)
        pool = {k: n for k, nos in keys.items() for n in nos
                if n not in assigned and low < n < high}
        if not pool:
            continue
        best = difflib.get_close_matches(seg["title_ja_norm"], list(pool),
                                         n=1, cutoff=CUTOFF)
        if not best:
            continue
        no = pool[best[0]]
        seg["yotube_no"] = no
        assigned[no] = seg["segment_id"]
        stats["fuzzy"] += 1

    # --- 段3: 位置補間 ------------------------------------------------------
    # 確定したアンカーの間に挟まれるセグメントは位置から推定できる（SPEC.md §8.2）。
    anchors = [(i, seg["yotube_no"]) for i, seg in enumerate(segments)
               if seg["yotube_no"] is not None]
    if anchors:
        bounds = [(-1, 0)] + anchors + [(len(segments), max_no + 1)]
        for (li, ln), (ri, rn) in zip(bounds, bounds[1:]):
            gap_segments = list(range(li + 1, ri))
            gap_numbers = [n for n in range(ln + 1, rn) if n not in assigned]
            # 個数が一致するときだけ埋める。ずれていたら推測しない。
            if gap_segments and len(gap_segments) == len(gap_numbers):
                for idx, no in zip(gap_segments, gap_numbers):
                    segments[idx]["yotube_no"] = no
                    assigned[no] = segments[idx]["segment_id"]
                    stats["positional"] += 1

    # --- video_id の割り当てと失敗の記録 ------------------------------------
    for seg in segments:
        no = seg["yotube_no"]
        if no is None:
            stats["unmatched"] += 1
            unmatched.append({
                "segment_id": seg["segment_id"],
                "episode_id": seg["episode_id"],
                "title_ja": seg["title_ja"],
                "is_recurring": seg["is_recurring"],
                "reason": "no_video",
            })
            continue
        video = by_no.get(no)
        if not video:
            seg["yotube_no"] = None
            stats["unmatched"] += 1
            continue
        seg["yotube_video_id"] = video["video_id"]
        seg["has_synopsis_source"] = video["has_synopsis"]
    return stats


def apply_overrides(segments: dict[str, dict[str, Any]],
                    videos_by_id: dict[str, dict[str, Any]]) -> int:
    """手動補正を適用する（SPEC.md §8.2）。パイプライン再実行で失われない。"""
    path = OVERRIDES / "segment_youtube_map.csv"
    if not path.exists():
        return 0
    applied = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            seg_id = (row.get("segment_id") or "").strip()
            video_id = (row.get("video_id") or "").strip()
            seg = segments.get(seg_id)
            if not seg or not video_id:
                continue
            seg["yotube_video_id"] = video_id
            video = videos_by_id.get(video_id)
            if video:
                seg["yotube_no"] = video["yotube_no"]
                seg["has_synopsis_source"] = video["has_synopsis"]
            applied += 1
    return applied


def main() -> int:
    fandom = load(BUILD / "fandom.json")
    youtube = load(BUILD / "youtube.json")

    segments = fandom["segments"]
    episodes = {e["episode_id"]: e for e in fandom["episodes"]}
    for seg in segments:
        seg.setdefault("has_synopsis_source", False)

    print("=" * 66)
    print("セグメントの突合（SPEC.md §8）")
    print("=" * 66)

    n_recurring_titles = mark_recurring(segments)
    n_recurring = sum(1 for s in segments if s["is_recurring"])
    print(f"  定期ミニコーナー         {n_recurring:,} セグメント "
          f"({n_recurring_titles} 種類、閾値 {RECURRING_MIN_EPISODES} 話)")

    videos = [v for v in youtube["records"] if v["series"] in ("gen1", "uta")]
    unmatched: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()

    for series in ("gen1", "uta"):
        # 放送順に並べる（episode_no, seq）
        segs = sorted(
            (s for s in segments if episodes[s["episode_id"]]["series"] == series),
            key=lambda s: (episodes[s["episode_id"]]["episode_no"], s["seq"]))
        vids = sorted((v for v in videos if v["series"] == series),
                      key=lambda v: v["yotube_no"])
        stats = match_series(segs, vids, unmatched)
        totals.update(stats)
        matched = len(segs) - stats["unmatched"]
        print(f"\n  {series}")
        print(f"    セグメント             {len(segs):>5}")
        print(f"    動画                   {len(vids):>5}")
        print(f"    段1 完全一致           {stats['exact']:>5}")
        print(f"    段2 difflib(0.85)      {stats['fuzzy']:>5}")
        print(f"    段3 位置補間           {stats['positional']:>5}")
        print(f"    突合できた             {matched:>5} / {len(segs)} "
              f"= {matched / len(segs):.1%}")

    by_id = {s["segment_id"]: s for s in segments}
    n_over = apply_overrides(by_id, {v["video_id"]: v for v in youtube["records"]})
    if n_over:
        print(f"\n  手動補正の適用           {n_over}")

    # --- data_status（SPEC.md §12.5）---------------------------------------
    for seg in segments:
        if seg["yotube_video_id"]:
            seg["data_status"] = "full" if seg.get("has_synopsis_source") else "partial"
        else:
            seg["data_status"] = "none"
        seg.pop("has_synopsis_source", None)

    # --- A1 ゲートの確定値（SPEC.md §11.2）---------------------------------
    with_video = [s for s in segments if s["yotube_video_id"]]
    with_source = [s for s in segments if s["data_status"] == "full"]
    print("\n" + "-" * 66)
    print("A1 ゲート 確定値（SPEC.md §11.2）")
    print("-" * 66)
    print(f"  分母（動画が対応するセグメント） {len(with_video):>5}")
    print(f"  【...】ブロックあり              {len(with_source):>5}")
    if with_video:
        rate = len(with_source) / len(with_video)
        print(f"  充足率                           {rate:>5.1%}  (合格基準 80%)")
        print(f"  判定                             "
              f"{'通過' if rate >= 0.80 else '不合格'}")
    print("-" * 66)

    REPORTS.mkdir(parents=True, exist_ok=True)
    with (REPORTS / "unmatched.csv").open(
            "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["segment_id", "episode_id", "title_ja",
                            "is_recurring", "reason"])
        writer.writeheader()
        writer.writerows(unmatched)

    recurring_unmatched = sum(1 for r in unmatched if r["is_recurring"])
    print(f"\n  突合できなかった         {len(unmatched):,} "
          f"(うち定期コーナー {recurring_unmatched:,})")
    print(f"  出力                     reports/unmatched.csv")

    (BUILD / "segments_matched.json").write_text(
        json.dumps({"segments": segments}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"  書き出し                 build/segments_matched.json")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
