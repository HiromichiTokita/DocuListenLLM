# UIオーバーホール設計書

**日付:** 2026-06-24

---

## 概要

4つの独立した改善を1リリースにまとめる：
1. バージョン文字列の一元化
2. 再生コントロールUIのブラッシュアップ（シンボルボタン・チャンクスキップ・Pillowトグル）
3. 読み上げ履歴バー
4. 音量キーボードショートカット

変更ファイルは `main.py` と `build.py` のみ。

---

## Feature 1: バージョン文字列一元化

### 現状
- `main.py` L3 (docstring)
- `main.py` L400 (`self.title(...)`)
- `build.py` L32 (`VERSION = "v1.2.3"`)

### 設計
- `main.py` の定数ブロックに `APP_VERSION = "v1.2.3"` を追加
- `self.title(...)` を `f"... {APP_VERSION}"` に変更
- docstring はバージョンを削除（定数が正本）
- `build.py` は `main.py` を正規表現でパースして取得：
  ```python
  import re, pathlib
  src = pathlib.Path("main.py").read_text(encoding="utf-8")
  VERSION = re.search(r'^APP_VERSION\s*=\s*["\'](.+)["\']', src, re.M).group(1)
  ```

---

## Feature 2: 再生コントロールUIブラッシュアップ

### ボタン変更
| 現在 | 変更後 | width |
|------|--------|-------|
| `▶  再生` | `▶` | 40 |
| `⏸  一時停止` / `▶  再開` | `⏸` / `▶` | 40 |
| `⏹  停止` | `⏹` | 40 |

### チャンクスキップボタン追加（停止ボタンの右に配置）
```
⏮⏮  ⏮  ⏭  ⏭⏭
-100 -10 +10 +100
```
- 4ボタン、各 width=44
- 再生中のみ有効（idle時はdisabled）
- 実装：`_seek_to_chunk(delta: int)` を新設
  - `self._current_chunk_idx + delta` にクランプしてシーク
  - 既存の `_on_seek` / `time_slider` のシークロジックを再利用

### Pillowトグルスイッチ（「ブースト」）
- `CTkCheckBox` を `CTkButton` + Pillow描画画像に置換
- 画像サイズ: 44×22px
- OFF: 背景グレー(#555)、円ボタン左寄り(白)
- ON: 背景青(#1F6AA5)、円ボタン右寄り(白)
- `CTkImage` でLight/Dark両対応
- クリックで `volume_boost_var` をトグル → 既存 `_on_volume_boost_toggle` を呼ぶ

### 制御
- スキップボタンは `_set_controls_enabled` で再生中/停止時を管理
  - 再生中(enabled=False時): `"normal"`（操作可）
  - idle(enabled=True時): `"disabled"`（非再生時は無意味なので無効）

---

## Feature 3: 読み上げ履歴バー

### レイアウト
タイムスライダー行（row=4相当）の直下・再生コントロール行の直上に新行を挿入：

```
[ 📄 小説A.epub ][ 📄 長編B.txt ][ 📄 C.pdf ]  (最大5件、左詰め)
```

- フレーム高さ最小化（pady=2）
- ボタン: `fg_color="#2B2B2B"`, `hover_color="#3B3B3B"`, `text_color="#AAAAAA"`
- ファイル名: 拡張子付き最大20文字（超過は `…` で切り捨て）
- クリック: `_on_import_history(path)` → 既存 `_on_import` のパス指定版を呼ぶ

### データ
- 保存先: `settings.json` キー `recent_files: list[str]`（絶対パス）
- 最大保持: 10件（保存時に古いものを削除）
- 最大表示: 5件（新しい順）
- 更新タイミング: `_on_import` / `_on_drop` 成功時

### メソッド
- `_add_to_history(path: str)`: リスト先頭に追加、重複削除、10件超を切り捨て、`_save_settings` 呼び出し
- `_rebuild_history_bar()`: 履歴フレームの子ウィジェットを全破棄→再構築（最大5件）
- `_on_import_history(path: str)`: パス存在確認→`_extract_text_from_file`→テキスト設定

---

## Feature 4: 音量キーボードショートカット

- `Ctrl+↑`: 音量+10%（上限: ブーストON=200%、OFF=100%）
- `Ctrl+↓`: 音量-10%（下限0%）
- `self.bind("<Control-Up>", self._on_volume_up)`
- `self.bind("<Control-Down>", self._on_volume_down)`
- ステップ: スライダー範囲に合わせて 0.1 固定
- ラベルも即時更新、`_save_settings` 呼び出し

---

## グローバル制約

- 実行Python: `py main.py`（3.14）
- 新規依存: `Pillow`（`py -m pip install Pillow`、3.14環境で要確認）
- 変更ファイル: `main.py`, `build.py` のみ
- テスト: 手動確認
