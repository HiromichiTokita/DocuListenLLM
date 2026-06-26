# UIオーバーホール 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** バージョン一元化・再生UIシンボル化＋チャンクスキップ・Pillowトグルスイッチ・読み上げ履歴バー・音量ショートカットを main.py と build.py に追加する。

**Architecture:** 全変更は `main.py`（メインアプリ）と `build.py`（ビルドスクリプト）のみ。履歴バーはグリッドrow 3に挿入し、既存 row 3〜5 を row 4〜6 にシフト。Pillowは既インストール済み（v12.1.1）。

**Tech Stack:** Python 3.14, customtkinter, Pillow 12.1.1, numpy（既存）

## Global Constraints

- 実行は `py main.py`（Python 3.14）。`python` は 3.12 で別物。
- 変更ファイルは `E:\project\DocuListenLLM\main.py` と `E:\project\DocuListenLLM\build.py` のみ。
- テストは手動確認（自動テスト環境なし）。
- `APP_VERSION` の値は `"v1.2.3"` のまま維持（バンプは別途）。

---

### Task 1: バージョン文字列一元化

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py` — docstring・定数・title
- Modify: `E:\project\DocuListenLLM\build.py` — VERSION 行をパース取得に変更

**Interfaces:**
- Produces: 定数 `APP_VERSION = "v1.2.3"` (main.py)

- [ ] **Step 1: main.py の docstring からバージョンを削除し、定数を追加**

現在の L1-4：
```python
"""
VOICEVOX テキスト読み上げ (AI Audio Director 対応版)
v1.2.3
"""
```

変更後：
```python
"""VOICEVOX テキスト読み上げ (AI Audio Director 対応版)"""
```

また L53 の `VOLUME_DEFAULT = 1.0` の直前に追加：
```python
APP_VERSION   = "v1.2.3"
```

- [ ] **Step 2: タイトルを定数参照に変更**

現在の L400（クラス `__init__` 内）：
```python
        self.title("VOICEVOX テキスト読み上げ (AI Audio Director) v1.2.3")
```

変更後：
```python
        self.title(f"VOICEVOX テキスト読み上げ (AI Audio Director) {APP_VERSION}")
```

- [ ] **Step 3: build.py の VERSION 行をパース取得に変更**

現在の L32：
```python
VERSION     = "v1.2.3"
```

変更後（L32 を以下に置換。`import re, pathlib` は build.py 冒頭のインポートに追加）：
```python
import re as _re, pathlib as _pathlib
_main_src = _pathlib.Path(os.path.join(script_dir, "main.py")).read_text(encoding="utf-8")
VERSION   = _re.search(r'^APP_VERSION\s*=\s*["\'](.+)["\']', _main_src, _re.M).group(1)
```

- [ ] **Step 4: 手動確認**

```
py main.py
```

期待: タイトルバーに「VOICEVOX テキスト読み上げ (AI Audio Director) v1.2.3」が表示される。

---

### Task 2: 再生ボタンシンボル化 ＋ チャンクスキップボタン追加

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py` — `_build_control_frame`・`_on_pause_resume`・`_set_controls_enabled`・新メソッド `_skip_chunks`

**Interfaces:**
- Produces:
  - `self.skip_btn_m100`、`self.skip_btn_m10`、`self.skip_btn_p10`、`self.skip_btn_p100`（CTkButton）
  - `_skip_chunks(delta: int)` メソッド

- [ ] **Step 1: 再生・一時停止・停止ボタンをシンボルのみに変更**

`_build_control_frame` 内（現在 L1161〜1175）：

```python
        self.play_btn = ctk.CTkButton(
            frame, text="▶", width=44, command=self._on_play)
        self.play_btn.pack(side="left", padx=(10, 4), pady=8)

        self.pause_btn = ctk.CTkButton(
            frame, text="⏸", width=44,
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=self._on_pause_resume)
        self.pause_btn.pack(side="left", padx=(0, 4))

        self.stop_btn = ctk.CTkButton(
            frame, text="⏹", width=44,
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=self._on_stop)
        self.stop_btn.pack(side="left", padx=(0, 6))
```

- [ ] **Step 2: チャンクスキップボタンを停止ボタンの右に追加**

`self.stop_btn.pack(...)` の直後に追記：

```python
        self.skip_btn_m100 = ctk.CTkButton(
            frame, text="⏮⏮", width=50, font=ctk.CTkFont(size=11),
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=lambda: self._skip_chunks(-100))
        self.skip_btn_m100.pack(side="left", padx=(6, 2))

        self.skip_btn_m10 = ctk.CTkButton(
            frame, text="⏮", width=44, font=ctk.CTkFont(size=13),
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=lambda: self._skip_chunks(-10))
        self.skip_btn_m10.pack(side="left", padx=(0, 2))

        self.skip_btn_p10 = ctk.CTkButton(
            frame, text="⏭", width=44, font=ctk.CTkFont(size=13),
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=lambda: self._skip_chunks(10))
        self.skip_btn_p10.pack(side="left", padx=(0, 2))

        self.skip_btn_p100 = ctk.CTkButton(
            frame, text="⏭⏭", width=50, font=ctk.CTkFont(size=11),
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=lambda: self._skip_chunks(100))
        self.skip_btn_p100.pack(side="left", padx=(0, 16))
```

- [ ] **Step 3: `_skip_chunks` メソッドを追加**

`_on_padding_change` の近く（`_on_volume_boost_toggle` の直後）に追加：

```python
    def _skip_chunks(self, delta: int) -> None:
        if not self._chunks:
            return
        current = max(self._highlighted_chunk_idx, 0)
        new_idx = max(0, min(len(self._chunks) - 1, current + delta))
        self._programmatic_slider_update = True
        self.time_slider.set(new_idx)
        self._programmatic_slider_update = False
        self._update_time_label(new_idx)
        self._highlight_chunk(new_idx)
        if self._is_playing:
            self._seek_to(new_idx)
```

- [ ] **Step 4: `_on_pause_resume` のボタンテキストをシンボルに更新**

現在 L1760：
```python
            self.pause_btn.configure(text="▶  再開")
```
変更後：
```python
            self.pause_btn.configure(text="▶")
```

現在 L1765（停止解除後）：
```python
            self.pause_btn.configure(text="⏸  一時停止")
```
変更後：
```python
            self.pause_btn.configure(text="⏸")
```

また `_consumer_thread` 終了後のリセット（L2044付近）：
```python
                self.after(0, lambda: self.pause_btn.configure(text="⏸  一時停止"))
```
変更後：
```python
                self.after(0, lambda: self.pause_btn.configure(text="⏸"))
```

- [ ] **Step 5: `_set_controls_enabled` にスキップボタンを追加**

現在の `_set_controls_enabled` 内（enabled=False の else ブロック、pause_btn・stop_btn を有効化している箇所）の直後に追記：

```python
        for btn in (self.skip_btn_m100, self.skip_btn_m10,
                    self.skip_btn_p10,  self.skip_btn_p100):
            if enabled:
                btn.configure(state="disabled", fg_color=COLOR_DISABLED, hover=False)
            else:
                btn.configure(state="normal", fg_color=COLOR_PAUSE_ACTIVE, hover=True)
```

- [ ] **Step 6: 手動確認**

```
py main.py
```

期待:
- ▶ ⏸ ⏹ がシンボルのみのコンパクトなボタンになっている
- ⏮⏮ ⏮ ⏭ ⏭⏭ が停止ボタンの右に表示される（グレーアウト）
- 再生中にスキップボタンが青くなり、クリックで前後にジャンプする

---

### Task 3: Pillowトグルスイッチ（「ブースト」チェックボックス置換）

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py` — `_build_control_frame` 内のブーストCB・新メソッド `_make_toggle_image`・`_on_boost_btn_click`

**Interfaces:**
- Consumes: `self.volume_boost_var`（BooleanVar, Task 2 時点で既存）、`_on_volume_boost_toggle()`（既存）
- Produces: `self.volume_boost_btn`（CTkButton）、`_make_toggle_image(on: bool) -> CTkImage`

- [ ] **Step 1: `_make_toggle_image` メソッドを追加**

`_on_volume_boost_toggle` の直後に追加：

```python
    def _make_toggle_image(self, on: bool) -> ctk.CTkImage:
        from PIL import Image, ImageDraw
        w, h = 44, 22
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w - 1, h - 1],
                               radius=h // 2,
                               fill="#1F6AA5" if on else "#555555")
        d = h - 4
        cx = w - 2 - d if on else 2
        draw.ellipse([cx, 2, cx + d, h - 2], fill="white")
        return ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
```

- [ ] **Step 2: `_build_control_frame` 内のブーストチェックボックスを置換**

現在（L1212〜1215）：
```python
        self.volume_boost_cb = ctk.CTkCheckBox(
            frame, text="ブースト", variable=self.volume_boost_var,
            width=80, command=self._on_volume_boost_toggle)
        self.volume_boost_cb.pack(side="left", padx=(0, 10))
```

変更後：
```python
        self.volume_boost_btn = ctk.CTkButton(
            frame, text="", image=self._make_toggle_image(saved_boost),
            width=44, height=22, fg_color="transparent", hover=False,
            command=self._on_boost_btn_click)
        self.volume_boost_btn.pack(side="left", padx=(0, 10))
```

- [ ] **Step 3: `_on_boost_btn_click` メソッドを追加**

`_make_toggle_image` の直後に追加：

```python
    def _on_boost_btn_click(self) -> None:
        self.volume_boost_var.set(not self.volume_boost_var.get())
        self.volume_boost_btn.configure(
            image=self._make_toggle_image(self.volume_boost_var.get()))
        self._on_volume_boost_toggle()
```

- [ ] **Step 4: 手動確認**

```
py main.py
```

期待:
- 音量スライダーの右にトグルスイッチ画像が表示される（グレー/青の角丸）
- クリックするとON/OFF切り替わり、スライダー上限が変わる

---

### Task 4: 読み上げ履歴バー

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py` — `_save_settings`・`_build_ui`・`_on_import`・`_on_drop`・新メソッド群

**Interfaces:**
- Produces:
  - `self.history_frame`（CTkFrame）
  - `_add_to_history(path: str)`
  - `_rebuild_history_bar()`
  - `_on_import_history(path: str)`
  - `_build_history_bar()`

- [ ] **Step 1: `_save_settings` に `recent_files` を追加**

`_save_settings` の `data = { ... }` ブロックに追記（`"ruby_to_kana"` 行の後）：

```python
            "recent_files":    getattr(self, "_recent_files", []),
```

また `__init__` 内の `self._settings: dict = self._load_settings()` の直後（L438付近）に追記：

```python
        self._recent_files: list[str] = self._settings.get("recent_files", [])
```

- [ ] **Step 2: `_build_history_bar` メソッドを追加**

`_build_control_frame` の直前に追加：

```python
    def _build_history_bar(self) -> None:
        self.history_frame = ctk.CTkFrame(self, corner_radius=6, height=32)
        self.history_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 0))
        self._rebuild_history_bar()
```

- [ ] **Step 3: `_rebuild_history_bar` メソッドを追加**

`_build_history_bar` の直後に追加：

```python
    def _rebuild_history_bar(self) -> None:
        for w in self.history_frame.winfo_children():
            w.destroy()
        recent = self._recent_files[:5]
        if not recent:
            ctk.CTkLabel(
                self.history_frame, text="履歴なし",
                text_color="#666666", font=ctk.CTkFont(size=11)
            ).pack(side="left", padx=(10, 0), pady=4)
            return
        for path in recent:
            name = os.path.basename(path)
            label = name if len(name) <= 20 else name[:19] + "…"
            ctk.CTkButton(
                self.history_frame,
                text=f"📄 {label}",
                width=0,
                height=24,
                font=ctk.CTkFont(size=11),
                fg_color="#2B2B2B",
                hover_color="#3B3B3B",
                text_color="#AAAAAA",
                command=lambda p=path: self._on_import_history(p),
            ).pack(side="left", padx=(6, 0), pady=4)
```

- [ ] **Step 4: `_add_to_history` と `_on_import_history` メソッドを追加**

`_rebuild_history_bar` の直後に追加：

```python
    def _add_to_history(self, path: str) -> None:
        self._recent_files = [p for p in self._recent_files if p != path]
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:10]
        self._save_settings()
        self._rebuild_history_bar()

    def _on_import_history(self, path: str) -> None:
        if not os.path.exists(path):
            self._set_status(f"ファイルが見つかりません: {os.path.basename(path)}", "error")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._save_settings()
            self._rebuild_history_bar()
            return
        try:
            text = _extract_text_from_file(
                path, ruby_to_kana=self.ruby_to_kana_var.get())
        except Exception as exc:
            self._set_status(f"読み込みエラー: {exc}", "error")
            return
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self._script = []
        self._char_dict_dirty = True
        self._clear_all_highlights()
        self._update_chunks()
        self.time_slider.set(0)
        self._update_time_label(0)
        self._highlight_chunk(0)
        self._set_status(f"読み込み完了: {os.path.basename(path)}", "ok")
        self._add_to_history(path)
```

- [ ] **Step 5: `_on_import` 成功時に `_add_to_history` を呼び出す**

`_on_import` 内（L1402）の `self._set_status(f"読み込み完了: ...")` の直後に追加：

```python
        self._add_to_history(filepath)
```

- [ ] **Step 6: `_on_drop` 成功時に `_add_to_history` を呼び出す**

`_on_drop` 内（L808）の `self._set_status(f"読み込み完了: ...")` の直後に追加：

```python
                    self._add_to_history(filepath)
```

- [ ] **Step 7: グリッド行をシフトして history_bar を row 3 に挿入**

`_build_casting_frame`（L838）: `row=3` → `row=4`
`_build_system_setting_frame`（L1111）: `row=4` → `row=5`
`_build_control_frame`（L1159）: `row=5` → `row=6`

`_build_ui` メソッド（L734〜742）を以下に変更：

```python
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_top_bar()               # row 0
        self._build_text_frame()            # row 1
        self._build_navigation_frame()      # row 2
        self._build_history_bar()           # row 3  ← NEW
        self._build_casting_frame()         # row 4
        self._build_system_setting_frame()  # row 5
        self._build_control_frame()         # row 6
```

- [ ] **Step 8: 手動確認**

```
py main.py
```

期待:
- タイムスライダーの直下に「履歴なし」の細いバーが表示される
- ファイルをインポートするとバーにファイル名ボタンが現れる
- ボタンクリックでファイルを再読み込みできる
- 再起動後も履歴が復元される

---

### Task 5: 音量キーボードショートカット

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py` — `__init__` のバインド・新メソッド2つ

**Interfaces:**
- Consumes: `self.volume_slider`、`self.volume_label`（既存）、`self.volume_boost_var`（既存）

- [ ] **Step 1: `__init__` にキーバインドを追加**

`self.protocol("WM_DELETE_WINDOW", self._on_close)` の直後（L454）に追記：

```python
        self.bind("<Control-Up>",   self._on_volume_up)
        self.bind("<Control-Down>", self._on_volume_down)
```

- [ ] **Step 2: `_on_volume_up` と `_on_volume_down` メソッドを追加**

`_on_boost_btn_click` の直後に追加：

```python
    def _on_volume_up(self, _event=None) -> None:
        limit = 2.0 if self.volume_boost_var.get() else 1.0
        new_val = min(self.volume_slider.get() + 0.1, limit)
        self.volume_slider.set(new_val)
        self.volume_label.configure(text=f"{round(new_val * 100):.0f}%")
        self._save_settings()

    def _on_volume_down(self, _event=None) -> None:
        new_val = max(self.volume_slider.get() - 0.1, 0.0)
        self.volume_slider.set(new_val)
        self.volume_label.configure(text=f"{round(new_val * 100):.0f}%")
        self._save_settings()
```

- [ ] **Step 3: 手動確認**

```
py main.py
```

期待:
- Ctrl+↑ で音量が10%上昇（上限100%、ブーストON時200%）
- Ctrl+↓ で音量が10%下降（下限0%）
- 音量ラベルが即時更新される
