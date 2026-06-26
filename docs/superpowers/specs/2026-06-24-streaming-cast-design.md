# ストリーミング配役設計書

**日付:** 2026-06-24

---

## 概要

AIディレクターモードの Stage 2（セリフ配役）をバックグラウンド実行に変更する。
現在は全チャンク配役完了後に再生開始するため待ち時間が長い。
変更後はルールベースの仮speakerでプリフィルして即座に再生開始し、配役結果を後追いで反映する。

変更ファイルは `main.py` のみ。

---

## 現在のフロー

```
_llm_and_play_thread:
  Stage1: キャラクター抽出（dirty時のみ、1回Ollama）
  Stage2: for each chunk → ollama.chat → _script.append  ← 全完了まで待機
  → _start_playback()
```

```
_producer:
  script_chunks = [(text, style_id) for entry in self._script]  ← スナップショット
  for chunk in script_chunks: ... TTS ...
```

---

## 変更後のフロー

```
_llm_and_play_thread:
  Stage1: キャラクター抽出（dirty時のみ、変更なし）
  プリフィル: _script = [{"text": c, "style_id": fallback_id} for c in _chunks]
  → after(0, _start_playback)   ← 即時再生開始
  Stage2(バックグラウンド継続):
    for each dialogue chunk:
      if _stop_event: break
      ollama.chat → _script[i]["style_id"] = new_id  ← 上書き
  → status "AI配役完了"
```

```
_producer（変更後）:
  total = len(self._script)
  for chunk_idx in range(start_index, total):
    entry = self._script[chunk_idx]   ← スナップショットなし、動的読み取り
    speaker_id = int(entry.get("style_id", narrator_id))
    ... TTS ...
```

---

## 詳細仕様

### `_llm_and_play_thread` の変更

1. **Stage 1**: 変更なし（`_char_dict_dirty` 時のみ Ollama 1回呼び出し）
2. **プリフィル処理**（Stage 2 の前に追加）:
   - `narrator_id` / `dialogue_id` を取得
   - `_script` を `[{"text": c, "style_id": rule_based_id}]` で全チャンク分初期化
   - `_update_chunks()` を after で呼ぶ
   - `_start_playback(start_index)` を `self.after(0, ...)` で呼び出す
3. **Stage 2 バックグラウンド継続**:
   - プリフィル後、同スレッドでセリフチャンクを順次 Ollama 配役
   - `_stop_event.is_set()` を毎チャンクチェック（stop時は中断）
   - `_script[i]["style_id"] = new_style_id` で上書き（GIL で十分安全）
   - ステータス: `"AI: 配役中... ({n}/{total})"` を `self.after(0, ...)` で更新
   - 完了後: `"AI配役完了 ({n}チャンク)"` を表示
4. **`_is_llm_processing`**: Stage 2 完了まで `True` のまま維持
   - `_on_play` の冒頭チェック: `_is_llm_processing` の場合でも再生中なら無視（すでに再生中のため）
   - 停止後に再度▶を押すと `_on_play` が呼ばれるが、`_is_llm_processing=True` のとき stop_event を立てて LLM を中断し再スタートする

### `_producer` の変更

- 現在: `self._script` からスナップショットリスト `script_chunks` を生成してからループ
- 変更後: スナップショットを作らず `self._script[chunk_idx]` をループ内で動的読み取り

```python
# 変更前
if self._script:
    script_chunks = [(entry["text"], int(entry.get("style_id", narrator_id)))
                     for entry in self._script]
else:
    script_chunks = [...]

for index, (chunk, speaker_id) in enumerate(script_chunks, start=1):
    chunk_idx = index - 1
    ...

# 変更後
if self._script:
    total = len(self._script)
    for chunk_idx in range(total):
        index = chunk_idx + 1
        if chunk_idx < start_index:
            continue
        entry = self._script[chunk_idx]
        chunk = entry.get("text", "")
        speaker_id = int(entry.get("style_id", narrator_id))
        ...
else:
    # ルールベースモードは変更なし
    ...
```

### `_on_play` の変更

現在:
```python
if self._is_llm_processing:
    self._set_status("AIの終了処理を待っています。数秒お待ちください", "working")
    return
```

変更後:
```python
if self._is_llm_processing and not self._is_playing:
    # バックグラウンド配役中に再生していない状態 → LLMを中断して再スタート
    self._stop_event.set()
    # _is_llm_processing は LLM スレッドの finally でクリアされる
    # ここではすぐ return して LLM が終わるのを待つ（既存動作）
    self._set_status("AI配役を中断して再開します...", "working")
    return
# _is_playing=True かつ _is_llm_processing=True → バックグラウンド配役中に再生中
# → 何もしない（既に再生中）
```

---

## グローバル制約

- 変更ファイルは `E:\project\DocuListenLLM\main.py` のみ
- 実行は `py main.py`（Python 3.14）
- テストは手動確認
- `_script` の要素は `{"text": str, "style_id": int}` の dict（変更なし）
- GIL により `_script[i]["style_id"] = x` の単一代入はスレッドセーフ
