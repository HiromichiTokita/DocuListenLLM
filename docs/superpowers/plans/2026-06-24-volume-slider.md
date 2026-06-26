# 音量スライダー実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** アプリ内に音量スライダー（0〜100%、ブーストチェックONで0〜200%）を追加し、OS主音量と独立してアプリ内音量を制御できるようにする。

**Architecture:** 再生直前の numpy float32 配列に係数（0.0〜2.0）を乗算し、`np.clip(-1.0, 1.0)` でクリッピング。UIは既存の「話速:」「余白:」スライダーと同行に追加。「ブースト」チェックボックスOFF時は上限1.0、ON時は2.0に動的変更。設定は他スライダーと同様 `settings.json` に保存・復元。

**Tech Stack:** Python 3.14, customtkinter, numpy, sounddevice（既存）

## Global Constraints

- 実行は `py main.py`（Python 3.14）。`python` は 3.12 で別物。
- 変更ファイルは `E:\project\DocuListenLLM\main.py` のみ。
- テストは手動確認（自動テスト環境なし）。

---

### Task 1: 定数追加 + save/load

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:50-52`（定数ブロック末尾）
- Modify: `E:\project\DocuListenLLM\main.py:465-493`（`_save_settings`）

**Interfaces:**
- Produces: 定数 `VOLUME_DEFAULT = 1.0`、設定キー `"playback_volume"`、設定キー `"volume_boost"`

- [ ] **Step 1: 定数を追加**

`main.py` L52 (`SPEED_DEFAULT = 1.0`) の直後に追記：

```python
VOLUME_DEFAULT = 1.0
```

- [ ] **Step 2: `_save_settings` に音量とブーストを追加**

`_save_settings` 内の `data = { ... }` ブロック（L474〜493）の `"silence_padding"` 行直後に追記：

```python
"playback_speed":   round(self.speed_slider.get(), 1),
"silence_padding":  round(self.padding_slider.get(), 1),
"playback_volume":  round(self.volume_slider.get(), 2),  # ← 追加
"volume_boost":     self.volume_boost_var.get(),          # ← 追加
```

- [ ] **Step 3: 動作確認（この時点ではまだ `volume_slider` / `volume_boost_var` が存在しないためアプリ起動不可。Task 2 完了後に確認）**

---

### Task 2: UI（スライダー＋ラベル＋ブーストチェックボックス）追加

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:1185-1194`（`padding_slider` 直後）

**Interfaces:**
- Consumes: 定数 `VOLUME_DEFAULT`、設定キー `"playback_volume"`・`"volume_boost"` (Task 1)
- Produces:
  - `self.volume_boost_var`（BooleanVar）
  - `self.volume_slider`（CTkSlider）
  - `self.volume_label`（CTkLabel）
  - `self._on_volume_change(value: float)` メソッド
  - `self._on_volume_boost_toggle()` メソッド

- [ ] **Step 1: スライダー・ラベル・チェックボックスを追加**

`main.py` の `padding_label.pack(...)` 行（L1193〜1194）の直後、「終了」ボタンより前に追記：

```python
        ctk.CTkLabel(frame, text="音量:").pack(side="left", padx=(10, 4))
        saved_volume = self._settings.get("playback_volume", VOLUME_DEFAULT)
        saved_boost  = self._settings.get("volume_boost", False)
        self.volume_boost_var = ctk.BooleanVar(value=saved_boost)
        slider_max = 2.0 if saved_boost else 1.0
        self.volume_slider = ctk.CTkSlider(
            frame, from_=0.0, to=slider_max, number_of_steps=20,
            width=100, command=self._on_volume_change)
        self.volume_slider.set(min(saved_volume, slider_max))
        self.volume_slider.pack(side="left", padx=(0, 4))
        self.volume_label = ctk.CTkLabel(
            frame, text=f"{round(saved_volume * 100):.0f}%", width=44, anchor="w")
        self.volume_label.pack(side="left", padx=(0, 4))
        self.volume_boost_cb = ctk.CTkCheckBox(
            frame, text="ブースト", variable=self.volume_boost_var,
            width=80, command=self._on_volume_boost_toggle)
        self.volume_boost_cb.pack(side="left", padx=(0, 10))
```

- [ ] **Step 2: コールバックを追加**

`_on_padding_change` メソッド（L1396〜1398）の直後に追記：

```python
    def _on_volume_change(self, value: float) -> None:
        self.volume_label.configure(text=f"{round(value * 100):.0f}%")
        self._save_settings()

    def _on_volume_boost_toggle(self) -> None:
        boosted = self.volume_boost_var.get()
        new_max = 2.0 if boosted else 1.0
        current = self.volume_slider.get()
        if not boosted and current > 1.0:
            self.volume_slider.set(1.0)
            self.volume_label.configure(text="100%")
        self.volume_slider.configure(to=new_max, number_of_steps=20)
        self._save_settings()
```

- [ ] **Step 3: 手動確認**

```
py main.py
```

期待:
- 「音量: [スライダー] 100% [ブースト]」が表示される
- チェックOFF: スライダーを動かしても100%が上限
- チェックON: スライダーが200%まで動く
- チェックをOFF→ONして200%→OFFに戻すと100%にクランプされる

---

### Task 3: 再生ループへのゲイン適用

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:1981-1984`（`sd.play` 直前）

**Interfaces:**
- Consumes: `self.volume_slider`（Task 2）

- [ ] **Step 1: `sd.play` 直前にゲイン乗算を挿入**

現在の L1981〜1984：

```python
                padded = np.concatenate([pre_silence, audio_processed, silence])
                del pre_silence, audio_processed, silence

                sd.play(padded, samplerate=sample_rate)
```

これを下記に変更：

```python
                padded = np.concatenate([pre_silence, audio_processed, silence])
                del pre_silence, audio_processed, silence

                volume = self.volume_slider.get()
                if abs(volume - 1.0) > 0.01:
                    padded = np.clip(padded * volume, -1.0, 1.0)

                sd.play(padded, samplerate=sample_rate)
```

- [ ] **Step 2: 手動確認**

```
py main.py
```

1. テキストを貼り付けて再生開始
2. 音量スライダーを 50%（0.5）に下げる → 次チャンクから音が小さくなることを確認
3. ブーストONにして200%（2.0）に上げる → 音が大きくなることを確認
4. 0%（0.0）にする → 無音になることを確認

---

### Task 4: enabled/disabled 制御への追加

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:2021-2040`（`_set_controls_enabled`）

**Interfaces:**
- Consumes: `self.volume_slider`（Task 2）

- [ ] **Step 1: `_set_controls_enabled` に volume_slider を追加**

現在（L2031〜2032）：

```python
        self.speed_slider.configure(state="normal")
        self.time_slider.configure(state="normal")
```

これを下記に変更：

```python
        self.speed_slider.configure(state="normal")
        self.volume_slider.configure(state="normal")
        self.time_slider.configure(state="normal")
```

- [ ] **Step 2: 手動確認**

```
py main.py
```

1. 再生中に音量スライダーとブーストチェックボックスが操作できることを確認
2. 停止中も操作できることを確認
3. アプリを終了して再起動し、音量・ブーストON/OFFの状態が復元されることを確認
