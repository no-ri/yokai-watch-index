#!/usr/bin/env python3
"""
Fandom の一覧ページから、リンクされている全ページ名を抽出する。

Special:Export で「List of Yo-kai by Medallium Number」等の一覧ページを
数枚だけ取得しておき、このスクリプトに食わせると、
Special:Export のテキストエリアに貼り付けられる形式で出力する。

使い方:
    python3 extract_page_list.py lists.xml
    python3 extract_page_list.py lists.xml --exclude data/_raw/fandom/

    --exclude を付けると、指定ディレクトリで既に取得済みのページを除外する。

出力:
    export_batch_01.txt, export_batch_02.txt, ...  （500行ずつ）

依存: 標準ライブラリのみ
"""

import argparse
import glob
import html
import os
import re
import sys

# 除外する名前空間
NS_SKIP = (
    "File:", "Image:", "Template:", "Category:", "Talk:", "User:",
    "Help:", "Module:", "Special:", "Project:", "MediaWiki:", "Board:",
)

# 明らかにページ名でないもの
JUNK = re.compile(r"^(https?:|#|\s*$)")

BATCH_SIZE = 500


def load_texts(paths):
    out = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        for m in re.finditer(r"<page>.*?</page>", raw, re.S):
            block = m.group(0)
            tm = re.search(r"<title>(.*?)</title>", block)
            xm = re.search(r"<text[^>]*>(.*?)</text>", block, re.S)
            if tm and xm:
                out[html.unescape(tm.group(1))] = html.unescape(xm.group(1))
    return out


def extract_links(text):
    """wikitext から [[リンク先]] を抽出して正規化する。"""
    found = []
    for raw in re.findall(r"\[\[([^\[\]]+)\]\]", text):
        target = raw.split("|")[0].split("#")[0].strip()
        if not target or JUNK.match(target):
            continue
        if target.startswith(NS_SKIP):
            continue
        if target.startswith(":"):
            continue
        # 先頭を大文字化（MediaWiki の仕様）
        target = target[0].upper() + target[1:]
        found.append(target)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml", nargs="+", help="一覧ページを含む XML")
    ap.add_argument("--exclude", help="取得済み XML のディレクトリ")
    ap.add_argument("--out-prefix", default="export_batch")
    args = ap.parse_args()

    pages = load_texts(args.xml)
    if not pages:
        print("ページが読み込めませんでした。", file=sys.stderr)
        sys.exit(1)

    print(f"一覧ページ: {len(pages)} 枚")
    for t in pages:
        print(f"  - {t}")

    # 全リンクを収集
    all_links = []
    per_page = {}
    for title, text in pages.items():
        links = extract_links(text)
        per_page[title] = len(links)
        all_links.extend(links)

    print("\nページごとのリンク数:")
    for t, n in sorted(per_page.items(), key=lambda x: -x[1]):
        print(f"  {n:>6}  {t}")

    # 重複除去（順序保持）
    seen = set()
    unique = []
    for lk in all_links:
        if lk not in seen:
            seen.add(lk)
            unique.append(lk)

    print(f"\n抽出したページ名: {len(all_links)} 件 "
          f"-> 重複除去後 {len(unique)} 件")

    # 一覧ページ自身を除外
    unique = [u for u in unique if u not in pages]

    # 取得済みを除外
    if args.exclude:
        got = load_texts(sorted(glob.glob(os.path.join(args.exclude, "*.xml"))))
        before = len(unique)
        unique = [u for u in unique if u not in got]
        print(f"取得済みを除外: {before} -> {len(unique)} 件"
              f"（既存 {len(got)} ページと照合）")

    if not unique:
        print("\n新たに取得すべきページはありません。")
        return

    # バッチ出力
    nbatch = -(-len(unique) // BATCH_SIZE)
    for i in range(nbatch):
        chunk = unique[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        fn = f"{args.out_prefix}_{i + 1:02d}.txt"
        with open(fn, "w", encoding="utf-8") as f:
            f.write("\n".join(chunk) + "\n")
        print(f"  {fn}  ({len(chunk)} 行)")

    print(f"\n{nbatch} 個のファイルを出力しました。")
    print("各ファイルの中身を Special:Export のテキストエリアに貼り付けて、")
    print("1ファイルずつエクスポートしてください。")


if __name__ == "__main__":
    main()
