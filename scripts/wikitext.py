"""Fandom XML と wikitext を読むための共通処理。

SPEC.md §5.2 / §5.3 / §5.6 / §5.13 の実装。
scripts/parse_fandom.py と tools/spec_audit.py の両方から使う。
"""

from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path
from typing import Iterator, NamedTuple

# --- 特殊空白の正規化（SPEC.md §5.6）----------------------------------------
# 実データにノーブレークスペース（U+00A0）が混入しており、見た目では気づけない。
_SPECIAL_SPACE = dict.fromkeys(
    [
        0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005,
        0x2006, 0x2007, 0x2008, 0x2009, 0x200A, 0x200B, 0x202F, 0x205F,
        0x3000, 0xFEFF, 0x0009,
    ],
    " ",
)

_RE_BR = re.compile(r"<\s*br\s*/?\s*>", re.I)
_RE_RUBY_RT = re.compile(r"<\s*rt\s*>.*?<\s*/\s*rt\s*>", re.I | re.S)
_RE_RP = re.compile(r"<\s*rp\s*>.*?<\s*/\s*rp\s*>", re.I | re.S)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RE_QUOTES = re.compile(r"'{2,}")


class Page(NamedTuple):
    title: str
    text: str

    @property
    def namespace(self) -> str:
        """"File:Foo" -> "File"。名前空間なしは ""。"""
        if ":" not in self.title:
            return ""
        head = self.title.split(":", 1)[0]
        # "Konbu-san (Shadowside)" のような通常タイトルを誤判定しないよう、
        # 既知の名前空間だけを名前空間として扱う。
        return head if head in KNOWN_NAMESPACES else ""

    @property
    def is_redirect(self) -> bool:
        return bool(re.match(r"\s*#\s*REDIRECT", self.text, re.I))


KNOWN_NAMESPACES = {
    "File", "Category", "Template", "Help", "User", "Talk", "Module",
    "MediaWiki", "Project", "Forum", "Board", "Blog", "Image",
    "User talk", "File talk", "Category talk", "Template talk",
    "Yo-kai Watch Wiki",
}


def normalize_spaces(value: str) -> str:
    """特殊空白を U+0020 に潰し、前後を strip する（SPEC.md §5.6）。"""
    return value.translate(_SPECIAL_SPACE).strip()


def strip_ruby(value: str) -> str:
    """ルビ HTML を除去する（SPEC.md §5.6 / §8.1）。

    <ruby>鬼<rt>き</rt></ruby> -> 鬼
    読み仮名（rt）を落としてから残りのタグを落とす。順序が逆だと読みが本文に混ざる。
    """
    value = _RE_RUBY_RT.sub("", value)
    value = _RE_RP.sub("", value)
    return _RE_TAG.sub("", value)


# --- テンプレートの切り出し（SPEC.md §5.3）----------------------------------
# 非貪欲マッチを使うと本文の散文まで取り込み、パラメータが 140 -> 1,835 に膨れる。
# {{ }} の対応を数えて切り出す。


def extract_braced(text: str, start: int) -> str | None:
    """text[start] の "{{" から対応する "}}" までを返す。"""
    if not text.startswith("{{", start):
        return None
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return None  # 閉じていない


def split_params(body: str) -> list[str]:
    """テンプレート本体を "|" で分割する。

    ネストした {{ }} と [[ ]] の内側の "|" は区切りにしない（SPEC.md §5.3）。
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(body)
    while i < n:
        two = body[i : i + 2]
        if two in ("{{", "[["):
            depth += 1
            buf.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            buf.append(two)
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth <= 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def find_template(text: str, name_pattern: str) -> str | None:
    """最初に見つかった {{name|...}} 全体を返す。name_pattern は正規表現。"""
    for m in re.finditer(r"\{\{\s*(" + name_pattern + r")\s*[|}]", text, re.I):
        blk = extract_braced(text, m.start())
        if blk:
            return blk
    return None


def parse_template_params(block: str) -> dict[str, str]:
    """{{name|a=1|b=2}} -> {"a": "1", "b": "2"}。名前は小文字化する。"""
    inner = block[2:-2]
    params: dict[str, str] = {}
    for part in split_params(inner)[1:]:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = normalize_spaces(key).lower()
        if key and key not in params:  # 重複時は先勝ち
            params[key] = value.strip()
    return params


# --- 値の正規化（SPEC.md §5.6）----------------------------------------------

_RE_SMALL_TMPL = re.compile(r"\{\{\s*(?:small|tt|nowrap)\s*\|([^{}]*)\}\}", re.I)


def clean_value(value: str) -> str:
    """infobox の値を表示可能な文字列にする。

    ルビ HTML / <br> / 注記テンプレート / 特殊空白 / コメントを処理する。
    """
    value = _RE_COMMENT.sub("", value)
    # {{small|(YW)}} -> (YW)。第1引数だけを残す。
    for _ in range(3):  # ネストは浅いので数回で収束する
        new = _RE_SMALL_TMPL.sub(lambda m: m.group(1), value)
        if new == value:
            break
        value = new
    value = _RE_BR.sub("\n", value)
    value = strip_ruby(value)
    value = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", value)  # [[A|B]] -> B
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)             # [[A]]   -> A
    value = _RE_QUOTES.sub("", value)                             # '''強調''' を落とす
    value = normalize_spaces(value)
    return value


def split_multi(value: str) -> list[str]:
    """<br> 区切りの値を分割する。空要素は落とす。"""
    return [normalize_spaces(v) for v in value.split("\n") if normalize_spaces(v)]


# --- XML の読み込み（SPEC.md §5.13）-----------------------------------------
# <text ... /> の自己閉じタグを空本文として扱わないと、本文が空のページが
# 丸ごと消える。実測で34件。

_RE_PAGE = re.compile(r"<page>\s*<title>(.*?)</title>(.*?)</page>", re.S)
_RE_TEXT_SELFCLOSED = re.compile(r"<text[^>]*/\s*>")
_RE_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.S)


def iter_pages(xml_path: Path) -> Iterator[Page]:
    raw = xml_path.read_text(encoding="utf-8")
    for m in _RE_PAGE.finditer(raw):
        title = html.unescape(m.group(1))
        body = m.group(2)
        if _RE_TEXT_SELFCLOSED.search(body):
            text = ""
        else:
            tm = _RE_TEXT.search(body)
            text = html.unescape(tm.group(1)) if tm else ""
        yield Page(normalize_spaces(title), text)


class LoadResult(NamedTuple):
    pages: dict[str, str]      # title -> wikitext（重複排除後）
    raw_count: int             # <page> の総数（重複を含む）
    duplicates: list[str]      # 重複していたタイトル
    empty_text: list[str]      # 本文が空のページ


def load_pages(fandom_dir: Path) -> LoadResult:
    """raw/fandom/*.xml を読み、タイトルで重複排除する（SPEC.md §5.13）。"""
    pages: dict[str, str] = {}
    raw_count = 0
    duplicates: list[str] = []
    for path in sorted(fandom_dir.glob("*.xml")):
        for page in iter_pages(path):
            raw_count += 1
            if page.title in pages:
                duplicates.append(page.title)
                continue
            pages[page.title] = page.text
    empty = [t for t, x in pages.items() if not x.strip()]
    return LoadResult(pages, raw_count, sorted(set(duplicates)), sorted(empty))


def load_titles(titles_path: Path) -> list[str]:
    """titles.txt を読む。

    titles.txt は一覧ページの wikitext から抽出されたもので、`&amp;` のような
    HTML 実体参照がそのまま残っている（実測15件）。XML 側は unescape して
    読むため、ここでも unescape しないと集合が一致しない。
    """
    lines = titles_path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        title = normalize_spaces(html.unescape(line))
        if title:
            out.append(title)
    return out


# --- カテゴリ ----------------------------------------------------------------

_RE_CATEGORY = re.compile(r"\[\[Category:\s*([^\]|#]+)", re.I)


def extract_categories(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _RE_CATEGORY.finditer(text):
        name = normalize_spaces(m.group(1))
        if name:
            seen.setdefault(name, None)
    return list(seen)


# --- 突合キーの正規化（SPEC.md §8.1）----------------------------------------

_RE_BRACKETS = re.compile(r"[「」『』（）()\[\]【】〈〉《》]")


def normalize_title_key(value: str) -> str:
    """title_ja_norm を作る。Fandom と妖Tube を繋ぐ唯一のキー。"""
    value = strip_ruby(value)
    value = normalize_spaces(value)
    # 全角英数記号を半角へ。波ダッシュ・全角チルダも吸収する。
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("〜", "~").replace("～", "~")
    value = _RE_BRACKETS.sub("", value)
    value = re.sub(r"\s+", "", value)
    return value
