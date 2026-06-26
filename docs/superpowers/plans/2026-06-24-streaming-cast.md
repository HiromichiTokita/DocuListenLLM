# ストリーミング配役 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AIディレクターモードで全チャンク配役完了を待たずに即時再生を開始し、配役をバックグラウンドで逐次反映する。

**Architecture:** `_llm_and_play_thread` をプリフィル（ルールベース仮speaker全チャンク）→即時 `_start_playback` → バックグラウンドで Stage 2 継続（`_script[i]["style_id"]` を上書き）に変更。`_producer` はスナップショットを廃止しループ内で `_script[chunk_idx]` を動的読み取りするよう変更。

**Tech Stack:** Python 3.14, threading（既存）, ollama（既存）

## Global Constraints

- 変更ファイルは `E:\project\DocuListenLLM\main.py` のみ。
- 実行は `py main.py`（Python 3.14）。
- テストは手動確認（自動テスト環境なし）。
- `_script` の要素は `{"text": str, "style_id": int}` の dict（変更なし）。

---

### Task 1: `_producer` の動的読み取り化

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:1975-1993`（`_producer` 内スナップショット部分）

**Interfaces:**
- Consumes: `self._script: list[dict]`（既存）
- Produces: `_producer` がループ内で `self._script[chunk_idx]` を動的読み取り

このタスクは Task 2 より先に実施する。現状 `_script` は再生前に完全に埋まっているため、Task 1 単体では動作に変化なし（後方互換）。Task 2 でプリフィルに変更したあと、このコードが効果を発揮する。

- [ ] **Step 1: `_producer` のスナップショット部分を動的読み取りに書き換える**

現在の L1975-1993：

```python
            if self._script:
                script_chunks = []
                for entry in self._script:
                    try:
                        speaker_id = int(entry.get("style_id", narrator_id))
                    except (ValueError, TypeError):
                        speaker_id = narrator_id
                    tts_text = entry.get("text", "")
                    script_chunks.append((tts_text, speaker_id))
            else:
                raw = self._split_text(text)
                script_chunks = [
                    (c, _speaker_for_chunk(c, narrator_id, dialogue_id, self._valid_openers()))
                    for c in raw
                ]

            total = len(script_chunks)

            for index, (chunk, speaker_id) in enumerate(script_chunks, start=1):
                chunk_idx = index - 1
```

変更後（`script_chunks` リストを作らず、ループ内で動的読み取り）：

```python
            if self._script:
                total = len(self._script)
                _iter = (
                    (chunk_idx, self._script[chunk_idx].get("text", ""),
                     ___speaker(chunk_idx))
                    for chunk_idx in range(total)
                )
            else:
                raw = self._split_text(text)
                script_chunks = [
                    (c, _speaker_for_chunk(c, narrator_id, dialogue_id, self._valid_openers()))
                    for c in raw
                ]
                total = len(script_chunks)
                _iter = (
                    (chunk_idx, chunk, speaker_id)
                    for chunk_idx, (chunk, speaker_id) in enumerate(script_chunks)
                )

            def ___speaker(ci: int) -> int:
                try:
                    return int(self._script[ci].get("style_id", narrator_id))
                except (ValueError, TypeError):
                    return narrator_id

            for chunk_idx, chunk, speaker_id in _iter:
                index = chunk_idx + 1
```

**注意**: ジェネレータ式の中で `___speaker(chunk_idx)` を呼ぶと、ジェネレータが評価される**時点**（ループ内、各イテレーション時）の `_script[chunk_idx]` が読まれる。これが動的読み取りの肝。

ただし、ジェネレータ式だと `___speaker` の定義がジェネレータより後になる問題がある。代わりにインラインで読む方がシンプルで安全：

```python
            if self._script:
                total = len(self._script)

                def _iter_script():
                    for ci in range(total):
                        entry = self._script[ci]
                        tts_text = entry.get("text", "")
                        try:
                            spk = int(entry.get("style_id", narrator_id))
                        except (ValueError, TypeError):
                            spk = narrator_id
                        yield ci, tts_text, spk

                _chunks_iter = _iter_script()
            else:
                raw = self._split_text(text)
                def _iter_rule():
                    for ci, c in enumerate(raw):
                        spk = _speaker_for_chunk(
                            c, narrator_id, dialogue_id, self._valid_openers())
                        yield ci, c, spk
                _chunks_iter = _iter_rule()
                total = len(raw)

            for chunk_idx, chunk, speaker_id in _chunks_iter:
                index = chunk_idx + 1
```

**これを採用する。** `_script[ci]` は `_iter_script` がそのイテレーションで実行される時点で読まれるため、バックグラウンドスレッドが上書きした最新値を得られる。

- [ ] **Step 2: 手動確認（後方互換チェック）**

```
py main.py
```

ルールベースタブ・AIディレクタータブ（現状動作）で再生が正常動作することを確認。動作は現状と変わらないはず。

---

### Task 2: `_llm_and_play_thread` のプリフィル＋即時再生化

**Files:**
- Modify: `E:\project\DocuListenLLM\main.py:1573-1576`（`_on_play` の `_is_llm_processing` チェック）
- Modify: `E:\project\DocuListenLLM\main.py:1641-1846`（`_llm_and_play_thread` 全体）

**Interfaces:**
- Consumes: `self._chunks`、`self._get_speaker_id()`、`self._valid_openers()`、`self._start_playback()`、`self._set_status()`（すべて既存）

- [ ] **Step 1: `_on_play` の `_is_llm_processing` チェックを修正**

現在 L1573-1576：

```python
    def _on_play(self) -> None:
        if self._is_llm_processing:
            self._set_status("AIの終了処理を待っています。数秒お待ちください", "working")
            return
```

変更後（再生中なら無視、停止中なら stop_event を立てて LLM を中断させてから return）：

```python
    def _on_play(self) -> None:
        if self._is_llm_processing:
            if self._is_playing:
                return  # バックグラウンド配役中に再生中 → 既に動いているので何もしない
            # バックグラウンド配役中で停止中 → stop_eventを立てて中断し、再試行を促す
            self._stop_event.set()
            self._set_status("AI配役を中断中... もう一度▶を押してください", "working")
            return
```

- [ ] **Step 2: `_llm_and_play_thread` のコメントヘッダを更新**

L1641：
```python
    # ─── LLM前処理 (v1.2.0: Stage1自動抽出 + バッチ配役) ──
```
→
```python
    # ─── LLM前処理 (Stage1: 自動抽出, Stage2: バックグラウンド配役) ──
```

L1647：
```python
            print(f"\n[DEBUG] --- LLM Thread Start (v1.2.0 Batch Mode) ---")
```
→
```python
            print(f"\n[DEBUG] --- LLM Thread Start (Streaming Cast Mode) ---")
```

- [ ] **Step 3: Stage 2 の前にプリフィルと即時再生を追加**

L1721（Stage 1 直後、`# ── Stage 2:` の前）のブロック全体を以下に置き換える。

**現在の L1721-1836（Stage 2 全体）を削除して、以下に置換：**

```python
            # ── プリフィル: ルールベースの仮speakerで全チャンクを初期化 ──
            narrator_id_llm = self._get_speaker_id(
                self.narrator_char_var.get(), self.narrator_style_var.get(), fallback=2)
            dialogue_id_llm = self._get_speaker_id(
                self.dialogue_char_var.get(), self.dialogue_style_var.get(), fallback=2)
            valid_openers = tuple(
                q.get()[0] for q in [self.quote1_var, self.quote2_var, self.quote3_var]
                if q.get() != "なし" and len(q.get()) == 2
            )
            if not valid_openers:
                valid_openers = ("「",)

            self._script = [
                {
                    "text": c,
                    "style_id": _speaker_for_chunk(
                        c, narrator_id_llm, dialogue_id_llm, valid_openers),
                }
                for c in self._chunks
            ]
            print(f"[DEBUG] Prefilled {len(self._script)} chunks with rule-based speakers.")

            # ── 即時再生開始 ──
            start_idx = min(
                int(round(self.time_slider.get())), max(0, len(self._chunks) - 1))
            self.after(0, lambda si=start_idx: self._start_playback(si))

            # ── Stage 2: バックグラウンドで逐次配役 ──
            character_profile_json = (
                stage1_profile_json if stage1_profile_json is not None
                else self._get_character_profile_json()
            )
            print(f"[DEBUG] Stage 2 Background Cast. Profile: {character_profile_json[:80]}...")

            last_speaker_category = "主人公 女"
            total_chunks = len(self._chunks)
            cast_count = 0

            try:
                for i, chunk in enumerate(self._chunks):
                    if self._stop_event.is_set():
                        print("[DEBUG] Stop event — background cast aborted.")
                        return

                    if not chunk.startswith(valid_openers):
                        continue

                    self.after(0, lambda idx=i, t=total_chunks: self._set_status(
                        f"AI: 配役中... ({idx + 1}/{t})", "working"))

                    start_ctx = max(0, i - 10)
                    end_ctx   = min(total_chunks, i + 11)
                    context_lines = []
                    for idx in range(start_ctx, end_ctx):
                        line = self._chunks[idx]
                        if idx == i:
                            context_lines.append(
                                f"===> [TARGET DIALOGUE TO CLASSIFY]: {line}")
                        else:
                            context_lines.append(line)
                    broad_context_str = "\n".join(context_lines)

                    system_msg = ATTRIBUTION_PROMPT.replace(
                        "{character_profile}", character_profile_json)
                    user_msg = (
                        f"[Broad Context (10 Chunks Before & After)]\n"
                        f"{broad_context_str}\n\n[Target Dialogue]\n{chunk}"
                    )

                    try:
                        resp = ollama.chat(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_msg},
                                {"role": "user",   "content": user_msg},
                            ],
                            format={
                                "type": "object",
                                "properties": {"category": {"type": "string"}},
                                "required": ["category"],
                            },
                            options={"num_ctx": 8192},
                        )
                        if self._stop_event.is_set():
                            return
                        cat_content = (resp.message.content if hasattr(resp, "message")
                                       else resp["message"]["content"])
                        parsed_cat = json.loads(cat_content)
                        category   = str(parsed_cat.get(
                            "category", last_speaker_category)).strip()
                        if category == "ナレーション" or category not in self.archetype_vars:
                            category = last_speaker_category
                    except Exception as exc:
                        print(f"[DEBUG] Error classifying chunk {i}: {exc}")
                        category = last_speaker_category

                    last_speaker_category = category

                    if category in self.archetype_vars:
                        c_name   = self.archetype_vars[category]["char"].get()
                        s_name   = self.archetype_vars[category]["style"].get()
                        style_id = self._get_speaker_id(c_name, s_name, fallback=2)
                    else:
                        c_name   = self.narrator_char_var.get()
                        s_name   = self.narrator_style_var.get()
                        style_id = self._get_speaker_id(c_name, s_name, fallback=2)

                    self._script[i]["style_id"] = style_id
                    cast_count += 1
                    print(f"[DEBUG] Chunk {i}: Cat='{category}', ID={style_id}")

            except Exception:
                print("\n[DEBUG] !!! STAGE 2 CRITICAL ERROR !!!")
                traceback.print_exc()
                # 再生はすでに始まっているので止めない。ステータスだけ更新。
                self.after(0, lambda: self._set_status("AI配役でエラーが発生しました", "error"))
                return

            self.after(0, lambda n=cast_count: self._set_status(
                f"AI配役完了 ({n}チャンク)", "ok"))
            print(f"[DEBUG] Background cast complete: {cast_count} dialogues classified.")
```

- [ ] **Step 4: `except Exception` ブロックを修正**

現在の L1838-1844（`_llm_and_play_thread` の外側 except）：

```python
        except Exception:
            import traceback
            print("\n[DEBUG] !!! LLM THREAD CRITICAL ERROR !!!")
            traceback.print_exc()
            self._script = []
            self.after(0, lambda: self._set_status("LLM解析に失敗しました", "stopped"))
            self.after(0, lambda: self._set_controls_enabled(True))
```

変更後（プリフィル前のエラー = 再生未開始なので controls を戻す。プリフィル後のエラーは Step 3 内で処理済み）：

```python
        except Exception:
            import traceback
            print("\n[DEBUG] !!! LLM THREAD CRITICAL ERROR !!!")
            traceback.print_exc()
            self._script = []
            self.after(0, lambda: self._set_status("LLM解析に失敗しました", "error"))
            if not self._is_playing:
                self.after(0, lambda: self._set_controls_enabled(True))
```

- [ ] **Step 5: 手動確認**

```
py main.py
```

1. テキストをインポートし、「AIディレクター (15役)」タブを選択
2. ▶ を押す
3. **Stage 1**（キャラクター抽出）は数秒待ち → その後**すぐ再生が始まること**を確認
4. ステータスバーに「AI: 配役中... (N/M)」が表示されながら音声が再生されていることを確認
5. 再生が最後まで終わると「AI配役完了」が表示されることを確認
6. ⏹停止 → 再度▶ → 前回の配役結果が引き継がれて（ルールベース仮speakerのまま or 部分的に配役済み）すぐ再生されることを確認
