# 出典

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
| `yokai.json` | 3,414 |
| `characters.json` | 154 |
| `episodes.json` | 310 |
| `segments.json` | 1,186 |

## 扱っていないもの

- **画像**（Fandom の画像は CC BY-SA の対象外のため、一切使用していません）
- 取得元の原文（あらすじ・解説などの散文）
- 妖Tube のタイトル・説明欄（保存しているのは `video_id` のみ）

## 加工について

事実データ（名前・話数・放送日・種族・ランク・属性など）のみを抽出し、
散文は含めていません。正規化と突合の規則は `SPEC.md` §5 と §8 に記載しています。

データの誤りにお気づきの場合は
[Issues](https://github.com/no-ri/yokai-watch-index/issues) までお知らせください。
