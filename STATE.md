# 進捗

最終更新: 2026-08-15

**中断した場合、新しいセッションはこのファイルから再開すること。**
再開手順は末尾の「再開のしかた」を参照。

---

## 完了

- [x] 着手前レビュー（`files/SPEC_ISSUES.md`）→ SPEC.md 版2.1 に反映済み
- [x] PR1 リポジトリの足場 — `654526e`（main へ直接。リポジトリ作成時のブートストラップ）
- [x] PR2 Fandom パーサと自己検証 — [#1](https://github.com/no-ri/yokai-watch-index/pull/1) merged
- [x] PR3 欠番（ja.Wikipedia は第一弾では使わない — SPEC §6 / D-20260815-03）
- [x] PR4 妖Tube 取得と A1 ゲート — [#2](https://github.com/no-ri/yokai-watch-index/pull/2) merged
- [x] PR5 セグメントの突合 — [#3](https://github.com/no-ri/yokai-watch-index/pull/3) merged
- [x] PR6 公開データ生成と禁止キー検査 — [#4](https://github.com/no-ri/yokai-watch-index/pull/4) merged
- [x] PR7 フロントエンド — [#5](https://github.com/no-ri/yokai-watch-index/pull/5) merged
- [x] GitHub Pages 公開 — https://no-ri.github.io/yokai-watch-index/
- [x] 修正 [#6](https://github.com/no-ri/yokai-watch-index/pull/6) 全画面オーバーレイがタップを飲み込んでいた
- [x] 修正 [#7](https://github.com/no-ri/yokai-watch-index/pull/7) CSS/JS のキャッシュ破棄

## 作業中

なし。**第一弾は完成。**

## 残り（人間の作業待ち。なくても動く）

- [ ] `overrides/movies.csv` の配置（劇場版8件。SPEC §5.15）
- [ ] SPEC.md への差し戻し3件（下記「引っかかっている点」）
- [ ] `reports/unmatched.csv` を見て `overrides/segment_youtube_map.csv` で手動補正

### 実行方法

```bash
python3 scripts/parse_fandom.py          # raw/fandom/*.xml -> build/fandom.json
python3 scripts/fetch_youtube.py         # YouTube API -> build/youtube.json（37ユニット）
python3 scripts/fetch_youtube.py --cached  # API を叩かず再計算
python3 tools/spec_audit.py              # §15 の実測値を再現
python3 scripts/match_segments.py        # 突合
python3 scripts/build_data.py            # docs/data/*.json を生成
python3 -m unittest discover -s tests    # 38件
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
| 妖Tube 総動画数 | **1,812** | §15.2 は 1,811 |
| 妖Tube 初代 | **621本 #1〜#621 欠番0** | **§15.2 は 506本・欠番114。すでに埋まっていた** |
| 妖Tube ♪ | 190本 #1〜#190 欠番0 | 一致（#186 のみ動画2本） |

### レポート件数（`reports/` は gitignore のためここに記録）

PR2 実行時点（2026-08-15）。

| ファイル | 件数 | 内容 |
|---|---|---|
| `unknown_params.csv` | 106 | 名前で集約。大半はゲームのステータス（§1.3 でスコープ外） |
| `conflicts.csv` | 268 | rank 243 / attribute 25。複数ゲームでランクが違うため |
| `unresolved_yokai.csv` | 93 | 46 種類のリンク。赤リンクとアニメオンリー妖怪 |
| `unknown_presence.csv` | **3** | `original` / `human` / `program` のみ。畳めないもの |
| `segment_title_mismatch.csv` | 2 | EP146（3対4）/ EP168（3対2） |
| `youtube_noise.csv` | 953 | shorts 406 / まとめ 154 / 【公式】でない 393 |
| `unmatched.csv` | 418 | うち定期ミニコーナー190。初代41 / ♪377 |

**`segment_title_mismatch` は EP031 / EP063 を含まない。**
着手前レビューで「この2件は `episode title` パラメータ自体が無い」と報告したのは、
雑な正規表現による計測の誤りだった。実際は両方とも持っている。

### 突合の結果（PR5）

| シリーズ | 突合 | 内訳 |
|---|---|---|
| 初代 | 580 / 621 = **93.4%** | 完全一致297 / difflib210 / 位置補間73 |
| ♪ | 188 / 565 = **33.3%** | 動画が190本しかないため上限33.6% |

定期ミニコーナー（`is_recurring`）は3種類190セグメント。
「発表！妖怪似顔絵記者会見」94 /「妖怪ニャハ体験」87 /「妖怪スイッチ！」9。

### A1 ゲート（SPEC §11.2）

分母は `yotube_video_id` が非 null のセグメント。

| | PR4 近似値 | **PR5 確定値** |
|---|---|---|
| 分母 | 811 | **768** |
| `【...】` ブロックあり | 607 | **579** |
| 充足率 | 74.8% | **75.4%** |
| 判定 | 不合格 | **不合格**（基準80%） |

内訳は初代 67.6% / ♪ 98.4%。初代の前半は説明欄が定型文だけの動画が多い。

§11.2 のとおり不合格でも機能は残し、該当セグメントは「あらすじなし」表示。
第一弾は Phase 3 を実施しないため `synopsis_ja` は元から null で実害はない。

§11.2 のとおり不合格でも機能は残し、該当セグメントは「あらすじなし」表示。
第一弾は Phase 3 を実施しないため `synopsis_ja` は元から null で実害はない。
突合後の確定値は PR5 で再計算する。

---

## 踏んだバグ（再発防止のため残す）

### 1. `hidden` 属性が効かず、全画面オーバーレイがタップを飲み込んでいた（#6）

`.detail { display: flex }` がブラウザ標準の `[hidden] { display: none }` を
詳細度で上回り、`hidden` を付けても要素が残っていた。
`.detail` は `position: fixed / inset: 0 / z-index: 50` なので、
**ページ全体がタップを受け付けない状態で公開された。**

対処: `[hidden] { display: none !important; }` を追加。

**見落とした理由**: 動作確認を JavaScript の `.click()` だけで行っていた。
プログラムからのクリックは要素を直接叩くため、上に何が乗っていても成功する。

**今後の検証方法**: 操作要素の中心座標で `document.elementFromPoint` を引き、
その要素自身が返るかを見る。上に何か乗っていれば別の要素が返るので検出できる。

### 2. GitHub Pages のキャッシュで修正が届かない（#7）

`Cache-Control: max-age=600` が返るため、ファイル名が同じだと修正が
最大10分間ブラウザに届かない。#6 をデプロイした後も古い CSS が使われていた。

対処: `style.css?v=` / `app.js?v=` を付けた。
**フロントを直すときはこの値を必ず上げること。**
なお `index.html` 自体もキャッシュされるため、`?v=` を上げた直後の
1回だけは利用者側の再読み込みが必要になる。

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

4. **§15.2 の妖Tube の数値が古い。**
   初代は「506本・#2〜621・欠番114」とあるが、実測では
   **621本・#1〜#621・欠番0**。すでに全話が配信済みで、
   Fandom 側の初代セグメント621と完全に一致する。
   総動画数も 1,811 → 1,812。♪ は190本で一致（#186 のみ動画が2本）。

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
| Pages | **公開中** https://no-ri.github.io/yokai-watch-index/ （`main` の `/docs`） |
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
