# サブタブ設計書（配役リスト / キャラクター辞書）

**日付:** 2026-06-25

---

## 概要

「AIディレクター (15役)」タブ内に `CTkTabview` をネストし、
「配役リスト」と「キャラクター辞書」をサブタブで切り替えられるようにする。

変更ファイルは `main.py` のみ。

---

## 現在の構造

```
[ルールベース] [AIディレクター (15役)]  ← 外側 self.tabview (row=4)
                └─ 配役リスト (15アーキタイプ) ← CTkScrollableFrame
                └─ キャラクター辞書ヘッダー    ← CTkFrame
                └─ キャラクター辞書リスト      ← CTkScrollableFrame
```

## 変更後の構造

```
[ルールベース] [AIディレクター (15役)]  ← 外側 self.tabview (変更なし)
                └─ [配役リスト] [キャラクター辞書]  ← 内側 CTkTabview (新規)
                        配役リスト タブ:
                          └─ 15アーキタイプ scroll (既存ウィジェットを移動)
                        キャラクター辞書 タブ:
                          └─ ヘッダー (AIで自動抽出 / ＋追加 ボタン)
                          └─ 列ヘッダー
                          └─ self.char_list_frame (既存)
```

---

## 実装詳細

### `_build_llm_archetypes_tab(self, parent)` の変更

1. `parent` の直下に `inner_tabs = ctk.CTkTabview(parent)` を作成し `pack(fill="both", expand=True)` で配置
2. `inner_tabs.add("配役リスト")` と `inner_tabs.add("キャラクター辞書")` を追加
3. 既存の「15アーキタイプ scroll」を `inner_tabs.tab("配役リスト")` に移す
4. 既存の「キャラクター辞書ヘッダー + char_list_frame」を `inner_tabs.tab("キャラクター辞書")` に移す
5. `inner_tabs` は `self` には保存しない（外部から参照不要）

### 高さ調整

- 外側 `self.tabview` の `height` は現在 `160` → `220` に拡大（サブタブのタブバー分）
- 内側 `CTkTabview` の高さ指定なし（`expand=True` で親に追従）
- 既存 `CTkScrollableFrame` の `height=180` はそのまま維持

### 変更しないもの

- `self.char_list_frame` の属性名・参照箇所（`_add_char_row` 等）
- `self.archetype_vars` の構造
- `self.extract_btn` の属性名
- 外側 `self.tabview` の構造・行配置

---

## グローバル制約

- 変更ファイルは `E:\project\DocuListenLLM\main.py` のみ
- 実行は `py main.py`（Python 3.14）
- テストは手動確認
