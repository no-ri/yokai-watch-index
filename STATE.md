# 進捗

最終更新: 2026-08-15

**中断した場合、新しいセッションはこのファイルから再開すること。**
再開手順は末尾の「再開のしかた」を参照。

---

## 完了

- [x] 着手前レビュー（`files/SPEC_ISSUES.md`）→ SPEC.md 版2.1 に反映済み
- [x] PR1 リポジトリの足場 — `654526e`（main へ直接。リポジトリ作成時のブートストラップ）
- [x] PR2 Fandom パーサと自己検証 — [#1](https://github.com/no-ri/yokai-watch-index/pull/1) merged

## 作業中

- [ ] PR4 妖Tube 取得 ＋ A1 ゲートの測定 — `feat/fetch-youtube`

## 残り

- [x] PR3 欠番（ja.Wikipedia は第一弾では使わない — SPEC §6 / D-20260815-03）
- [ ] PR5 突合
- [ ] PR6 データ生成（`facets.json` 含む）
- [ ] PR7 フロントエンド ＋ GitHub Pages 公開

### 実行方法

```bash
python3 scripts/parse_fandom.py          # raw/fandom/*.xml -> build/fandom.json
python3 tools/spec_audit.py              # §15 の実測値を再現
python3 -m unittest discover -s tests    # 27件
```

---

## 計測結果

着手前レビューで得た値（`tools/spec_audit.py` で再現可能。PR2 で作成）。

| 項目 | 実測 | SPEC との差異 |
|---|---|---|
| XML の `<page>` | 4,369（重複排除後 4,364） | §5.13 に反映済み |
| `titles.txt` との集合差 | 両方向 0 件 | — |
| 自己閉じ `<text />` | 34 件 | §5.13 の想定どおり |
| 妖怪 | 3,414 | 一致 |
| 人間キャラ | **154** | **§15.1 が 160 になっているが 154 が正しい（D-20260815-01）** |
| エピソード | 459（EP 214 / MN 96 / SS 49 / YSH 64 / EX 36） | §15.1 に反映済み |
| リダイレクト | 251 | 一致 |
| unclassified | 86 | §15.1 に反映済み |
| infobox パラメータ | 140 種類 | 一致 |
| セグメント（lead） | 1,186（EP 621 / MN 565） | §15.6 に反映済み |
| presence 注記 | 65 種類 | §15.6 に反映済み |
| 妖Tube 総動画数 | 1,811（API 実測） | 一致 |

### レポート件数（`reports/` は gitignore のためここに記録）

PR2 実行時点（2026-08-15）。

| ファイル | 件数 | 内容 |
|---|---|---|
| `unknown_params.csv` | 106 | 名前で集約。大半はゲームのステータス（§1.3 でスコープ外） |
| `conflicts.csv` | 268 | rank 243 / attribute 25。複数ゲームでランクが違うため |
| `unresolved_yokai.csv` | 93 | 46 種類のリンク。赤リンクとアニメオンリー妖怪 |
| `unknown_presence.csv` | **3** | `original` / `human` / `program` のみ。畳めないもの |
| `segment_title_mismatch.csv` | 2 | EP146（3対4）/ EP168（3対2） |
| `unmatched.csv` | 未計測 | PR5 で出力 |

**`segment_title_mismatch` は EP031 / EP063 を含まない。**
着手前レビューで「この2件は `episode title` パラメータ自体が無い」と報告したのは、
雑な正規表現による計測の誤りだった。実際は両方とも持っている。

### A1 ゲート（SPEC §11.2）

分母は `yotube_video_id` が非 null のセグメント。**PR4 で測定する。**

| | 値 |
|---|---|
| 判定 | 未測定 |
| 分母 | — |
| `【...】` ブロックあり | — |

---

## 引っかかっている点

### SPEC.md への差し戻し依頼（実装は先行して進める）

いずれも `tools/spec_audit.py` で再現できる。

1. **§15.1 の「人間キャラ 160」は 154 が正しい。**
   160 は着手前レビューでの計測誤り。排他分類（妖怪優先）では154で、
   内訳の合計も 4,364（`titles.txt` の行数）と一致する。D-20260815-01。
   `{{yo-kai}}` と `{{character}}` を両方持つページが6件あるのが差の理由。
   §15.1 の「人間キャラの日本語名 145 / 154 = 94.2%」の行は154前提のままなので、
   戻せば整合する。「パーサが認識した4,330件ベース」も古い表現。

2. **§5.11 / §15.1 の prefix 内訳は `{{episode/nav}}` の値を拾った数値。**
   `{{episode}}` 本体のみで数えると
   `(none) 318 / MN 64 / YG 9 / EX 19 / SS 49`。
   **Y学園の infobox 側の値は `YSH` ではなく `YG`。**
   本体に `prefix` を持たない MN 話が実在するため（MN090 等）、
   §5.11 をそのまま実装すると♪が32話落ちる。D-20260815-06（**要確認**）。

3. **§5.12 の「EP031 / EP063 は `episode title` パラメータ自体が無い」は誤り。**
   両方とも持っている。実際の個数不一致は EP146（3対4）と EP168（3対2）。

### 人間の作業待ち（なくても進行可能）

- `overrides/movies.csv` — 劇場版8件の手入力（SPEC §5.15）。
  未配置の間は劇場版セクションを空で構築する。後から置けば再ビルドで反映される。
- `tools/make_overrides.py` / `tools/yotube_inventory.py` — Phase 0 の調査用。
  Phase 2 以降の実装には影響しない。

---

## 環境

| | |
|---|---|
| GitHub | `no-ri/yokai-watch-index`（public） |
| Pages | `main` ブランチの `/docs`。PR7 で有効化 |
| `gh` | 2.97.0（`~/.local/bin/gh`）。認証済み |
| Python | 3.9.6（システム標準）。依存は標準ライブラリのみ |
| `.env` | リポジトリ直下。`YT_API_KEY` を格納。gitignore 済み |

---

## 再開のしかた

```bash
cd ~/Desktop/yokai-watch-index
git branch -a          # 作業中のブランチを確認
git log --oneline -10  # どこまで進んだか
```

1. `CLAUDE.md` → `SPEC.md`（版2.1）の該当節を読む
2. `DECISIONS.md` で既に決めたことを確認する（同じ判断を繰り返さない）
3. 上の「作業中」の PR から再開する
4. 各 PR のマージ後、**必ずこのファイルを更新してコミットする**

`raw/` と `reports/` は gitignore のため clone しても存在しない。
`raw/fandom/` は人間が `Special:Export` で配置する（SPEC §5.1、`raw/fandom/MANIFEST.txt`）。
