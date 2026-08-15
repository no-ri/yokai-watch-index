#!/usr/bin/env python3
"""
Fandom Special:Export の取りこぼし検証スクリプト

data/_raw/fandom/ 以下の XML を全部読んで、
「何が取れていて、何が参照されているのに取れていないか」を報告する。

使い方:
    python3 check_fandom_export.py data/_raw/fandom/

出力:
    標準出力にレポート
    missing_pages.txt に「参照されているが未取得のページ名」

依存: 標準ライブラリのみ
"""

import glob
import html
import os
import re
import sys
from collections import Counter, defaultdict

NS_SKIP = ("File:", "Template:", "Category:", "Talk:", "User:", "Help:", "Module:")

# エピソードページのID形式
EPISODE_ID = re.compile(r"^(EP|MN|M|YG|SS)\d+$")


def load_pages(paths):
    """XML群から {title: wikitext} を作る。重複はマージ。"""
    pages = {}
    dupes = Counter()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        for m in re.finditer(r"<page>.*?</page>", raw, re.S):
            block = m.group(0)
            tm = re.search(r"<title>(.*?)</title>", block)
            xm = re.search(r"<text[^>]*>(.*?)</text>", block, re.S)
            if not tm or not xm:
                continue
            title = html.unescape(tm.group(1))
            if title in pages:
                dupes[title] += 1
                continue
            pages[title] = html.unescape(xm.group(1))
    return pages, dupes


REDIRECT = re.compile(r"^\s*#\s*(REDIRECT|転送)\s*\[\[([^\]|#]+)", re.I)


def redirect_target(text):
    """#REDIRECT [[Target]] なら Target を返す。違えば None。"""
    m = REDIRECT.match(text)
    return m.group(2).strip() if m else None


def classify(title, text):
    """ページ種別を判定する。"""
    if title.startswith(NS_SKIP):
        return "other_ns"
    if redirect_target(text):
        return "redirect"
    if EPISODE_ID.match(title):
        return "episode"
    if re.search(r"\{\{\s*yo-?kai\s*\|", text, re.I):
        return "yokai"
    if re.search(r"\{\{\s*episode\s*\|", text, re.I):
        return "episode"
    if re.search(r"\{\{\s*character\s*\|", text, re.I):
        return "character"
    return "unclassified"


def norm_yokai_link(target):
    """[[Jibanyan (anime)|Jibanyan]] のリンク先を正規化する。

    除外対象（None を返す）:
      - カテゴリリンク  [[:Category:Foo]]
      - インターウィキ  [[w:c:other-wiki:Foo]]
      - 名前空間付き    [[File:Foo]]
    """
    t = target.split("|")[0]
    t = t.split("#")[0].strip()          # セクションアンカーを落とす
    if not t:
        return None
    if t.startswith(":"):                 # [[:Category:...]] / [[:File:...]]
        return None
    if re.match(r"^w:", t, re.I):          # インターウィキ
        return None
    if t.startswith(NS_SKIP):
        return None
    # (anime) は同一キャラの表記揺れなので剥がす。
    # (Shadowside) は別作品の別キャラなので剥がさない。
    t = re.sub(r"\s*\((anime|game|manga)\)\s*$", "", t, flags=re.I)
    return t or None


def extract_template(text, name):
    """{{name|...}} の中身を、波括弧の対応を数えて正確に切り出す。

    ネストしたテンプレートや、本文中の }} に引きずられない。
    見つからなければ None。
    """
    m = re.search(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|\}])", text, re.I)
    if not m:
        return None
    i = m.start()
    depth = 0
    j = i
    while j < len(text) - 1:
        pair = text[j : j + 2]
        if pair == "{{":
            depth += 1
            j += 2
            continue
        if pair == "}}":
            depth -= 1
            j += 2
            if depth == 0:
                return text[i + 2 : j - 2]
            continue
        j += 1
    return None


def split_params(body):
    """テンプレート本体をトップレベルの | で割り、パラメータ名を返す。

    ネストした {{ }} と [[ ]] の内側の | は区切りとして扱わない。
    """
    keys = []
    depth_t = depth_l = 0
    buf = []
    i = 0
    while i < len(body):
        pair = body[i : i + 2]
        if pair == "{{":
            depth_t += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "}}":
            depth_t -= 1
            buf.append(pair)
            i += 2
            continue
        if pair == "[[":
            depth_l += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "]]":
            depth_l -= 1
            buf.append(pair)
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth_t == 0 and depth_l == 0:
            keys.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    keys.append("".join(buf))

    out = []
    for seg in keys:
        if "=" not in seg:
            continue
        k = seg.split("=", 1)[0].strip().lower()
        # 改行を含むキーは切り出し失敗なので捨てる
        if not k or "\n" in k or len(k) > 40:
            continue
        out.append(k)
    return out


def extract_characters(text):
    """Characters 節から妖怪リンクを抜く。"""
    m = re.search(
        r"==+\s*Characters\s*==+(.*?)(?=\n==[^=]|\Z)", text, re.S | re.I
    )
    if not m:
        return []
    body = m.group(1)
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("*"):
            continue
        links = re.findall(r"\[\[([^\]]+)\]\]", line)
        for lk in links:
            n = norm_yokai_link(lk)
            if n:
                out.append(n)
    return out


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    paths = sorted(glob.glob(os.path.join(target, "*.xml")))
    if not paths:
        print(f"XMLが見つかりません: {target}", file=sys.stderr)
        sys.exit(1)

    print(f"読み込み対象: {len(paths)} ファイル")
    for p in paths:
        size = os.path.getsize(p) / 1024
        print(f"  {os.path.basename(p):<44} {size:>8.0f} KB")

    pages, dupes = load_pages(paths)
    print(f"\n総ページ数（重複除去後）: {len(pages)}")
    if dupes:
        print(f"重複していたページ: {sum(dupes.values())} 件"
              f"（{len(dupes)} 種類）")

    # 種別集計
    kinds = defaultdict(list)
    for title, text in pages.items():
        kinds[classify(title, text)].append(title)

    print("\n" + "-" * 62)
    print("ページ種別")
    print("-" * 62)
    for k in ("yokai", "character", "episode", "redirect",
              "unclassified", "other_ns"):
        print(f"  {k:<16} {len(kinds[k]):>6}")

    # エピソードのプレフィックス別
    ep_prefix = Counter()
    ep_nums = defaultdict(list)
    for t in kinds["episode"]:
        m = EPISODE_ID.match(t)
        if m:
            pfx = m.group(1)
            ep_prefix[pfx] += 1
            ep_nums[pfx].append(int(t[len(pfx):]))
    if ep_prefix:
        print("\n" + "-" * 62)
        print("エピソードのプレフィックス別")
        print("-" * 62)
        for pfx, cnt in sorted(ep_prefix.items()):
            ns = sorted(ep_nums[pfx])
            gaps = [n for n in range(ns[0], ns[-1] + 1) if n not in set(ns)]
            print(f"  {pfx:<4} {cnt:>5} 件   範囲 {ns[0]}-{ns[-1]}   "
                  f"欠番 {len(gaps)}")
            if gaps:
                print(f"        欠番例: {gaps[:20]}")

    # 妖怪ページの日本語名充足率
    if kinds["yokai"]:
        has_ja = 0
        no_ja = []
        for t in kinds["yokai"]:
            tx = pages[t]
            if (re.search(r"\|\s*japanese name\s*=\s*\S", tx)
                    or re.search(r"ja-name\s*=\s*\S", tx)):
                has_ja += 1
            else:
                no_ja.append(t)
        pct = has_ja / len(kinds["yokai"]) * 100
        print("\n" + "-" * 62)
        print("妖怪ページの日本語名")
        print("-" * 62)
        print(f"  日本語名あり: {has_ja}/{len(kinds['yokai'])} ({pct:.1f}%)")
        if no_ja:
            print(f"  欠落例: {no_ja[:15]}")

        # Etymology / medallium の充足率（Phase 2.5 の材料）
        for sec, pat in (("Etymology節", r"==+\s*Etymology\s*==+"),
                         ("{{medallium}}", r"\{\{\s*medallium")):
            n = sum(1 for t in kinds["yokai"]
                    if re.search(pat, pages[t], re.I))
            print(f"  {sec:<16} {n}/{len(kinds['yokai'])} "
                  f"({n / len(kinds['yokai']) * 100:.1f}%)")

    # 人間キャラの日本語名
    if kinds["character"]:
        n = sum(1 for t in kinds["character"]
                if re.search(r"\|\s*japanese name\s*=\s*\S", pages[t])
                or re.search(r"ja-name\s*=\s*\S", pages[t]))
        print("\n" + "-" * 62)
        print("人間キャラクターの日本語名")
        print("-" * 62)
        print(f"  日本語名あり: {n}/{len(kinds['character'])} "
              f"({n / len(kinds['character']) * 100:.1f}%)")

    # リダイレクト表
    redirects = {}
    for t in kinds["redirect"]:
        tgt = redirect_target(pages[t])
        if tgt:
            redirects[t] = tgt
    if redirects:
        print("\n" + "-" * 62)
        print(f"リダイレクト: {len(redirects)} 件")
        print("-" * 62)
        for src, dst in list(redirects.items())[:15]:
            print(f"  {src}  ->  {dst}")
        with open("redirects.csv", "w", encoding="utf-8") as f:
            f.write("from,to\n")
            for src, dst in sorted(redirects.items()):
                f.write(f'"{src}","{dst}"\n')
        print(f"  -> redirects.csv に {len(redirects)} 件を出力しました。")

    # 参照されているが未取得のページ
    referenced = Counter()
    for t in kinds["episode"]:
        for y in extract_characters(pages[t]):
            referenced[y] += 1

    have = set(pages)
    have_norm = {n for n in (norm_yokai_link(t) for t in pages) if n}

    def resolves(name):
        """名前が実在ページに解決できるか（リダイレクト経由を含む）。"""
        seen_r = set()
        cur = name
        for _ in range(5):
            if cur in have or cur in have_norm:
                return True
            if cur in redirects and cur not in seen_r:
                seen_r.add(cur)
                cur = redirects[cur]
                continue
            return False
        return False

    missing = {y: c for y, c in referenced.items() if not resolves(y)}

    print("\n" + "-" * 62)
    print("エピソードから参照されている妖怪")
    print("-" * 62)
    print(f"  参照されたページ名: {len(referenced)} 種類")
    print(f"  うち未取得:         {len(missing)} 種類")
    if missing:
        top = sorted(missing.items(), key=lambda x: -x[1])[:25]
        print("  参照が多い順:")
        for name, cnt in top:
            print(f"    {cnt:>4} 回  {name}")
        with open("missing_pages.txt", "w", encoding="utf-8") as f:
            for name, cnt in sorted(missing.items(), key=lambda x: -x[1]):
                f.write(f"{name}\n")
        print(f"\n  -> missing_pages.txt に {len(missing)} 件を出力しました。")
        print("     Special:Export のテキストエリアに貼り付けて追加取得できます。")
        print("     （人間キャラクターも混ざるので、全部が妖怪とは限りません）")

    # infobox パラメータ
    if kinds["yokai"]:
        params = Counter()
        nofound = 0
        for t in kinds["yokai"]:
            body = extract_template(pages[t], "yo-kai")
            if body is None:
                body = extract_template(pages[t], "yokai")
            if body is None:
                nofound += 1
                continue
            for key in split_params(body):
                params[key] += 1
        print("\n" + "-" * 62)
        print(f"infobox パラメータ（{len(params)} 種類）")
        print("-" * 62)
        if nofound:
            print(f"  ※ {{{{yo-kai}}}} を抽出できなかったページ: {nofound}")
        for p, c in params.most_common():
            print(f"  {c:>6}  {p}")

    # unclassified の中身（テンプレート名の分布）
    if kinds["unclassified"]:
        tmpl = Counter()
        for t in kinds["unclassified"]:
            m = re.match(r"\s*\{\{\s*([A-Za-z0-9 _'\-]+?)\s*[|\}]",
                         pages[t].lstrip())
            tmpl[m.group(1).lower() if m else "(先頭がテンプレートでない)"] += 1
        print("\n" + "-" * 62)
        print(f"unclassified の先頭テンプレート（{len(kinds['unclassified'])} 件）")
        print("-" * 62)
        for name, c in tmpl.most_common(20):
            print(f"  {c:>6}  {name}")
        print(f"  例: {kinds['unclassified'][:10]}")

    print("\n完了。")


if __name__ == "__main__":
    main()
