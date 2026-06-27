# Irodori 参照音声(ref_latent化)＋カテゴリ毎エンジン振り分け（C）Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。lean方針。
> 2リポジトリ: サーバ=`E:\project\IrodoriVDServer`（`.venv` 3.12）、アプリ=`E:\project\DocuListenLLM`（`py` 3.14）。

**Goal:** (Part1) 参照音声を torchcodec 不要の `ref_latent` 方式に直し Irodori の声をカテゴリ毎に一貫させる。
(Part2) カテゴリ毎に VOICEVOX / Irodori を選べるようにする（global: voicevox/irodori/mixed）。

## Global Constraints
- 後方互換: `category_engines` 既定空・global既定 voicevox → 2a/2b 非破壊。
- 参照音声は torchcodec/ffmpeg 不要（`codec.encode_waveform`→latent→`torch.save`、`SamplingRequest(ref_latent=path, no_ref=False)`）。
- `encode_waveform(waveform:(C,T)|(B,C,T), sample_rate, normalize_db=None, ensure_max=True) -> (B,T,D)`。保存は `(T,D)`。
- エンジン決定は純粋関数 `engine_for(category, global_engine, category_engines)` に集約しpytest。
- サーバ: `.venv/Scripts/python.exe`、アプリ: `py`。各リポジトリで各タスク末尾コミット。

---

### Task 1: サーバ ref_latent 化（torchcodec回避）【GPU-free write / GPU verify】

**Repo:** IrodoriVDServer / **Files:** `vd_server/backend.py`

- [ ] **Step 1: `_generate_ref` を latent 化**
`_generate_ref` を次に置換（波形→encode_waveform→latent→torch.save(.pt)）:
```python
    def _generate_ref(self, caption: str, seed) -> str:
        """REF_PHRASE を caption-only で1回合成し、基準 latent を .pt 保存してパスを返す（torchcodec不要）。"""
        import os, torch
        res = self._synthesize(self._runtime, REF_PHRASE, caption, seed)  # no_ref=True 既存経路
        wav = res.audio.detach().to("cpu").float()
        wav = torch.squeeze(wav)
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)                  # (C=1, T) like _load_audio
        latent = self._runtime.codec.encode_waveform(
            wav, sample_rate=int(res.sample_rate), normalize_db=None, ensure_max=True).cpu()  # (1,T,D)
        path = os.path.join(self._ref_dir, f"ref_{abs(hash((caption, seed)))}.pt")
        torch.save(latent.squeeze(0), path)         # (T,D); loader が _coerce+unsqueeze で戻す
        return path
```
- [ ] **Step 2: `_synthesize_ref` を ref_latent に**
```python
    def _synthesize_ref(self, text: str, caption: str, seed, ref_path: str):
        from irodori_tts.inference_runtime import SamplingRequest
        return self._runtime.synthesize(SamplingRequest(
            text=text, caption=caption, ref_latent=ref_path, no_ref=False,
            num_steps=self._num_steps, cfg_scale_text=self._cfg_text,
            cfg_scale_caption=self._cfg_caption,
            seed=None if seed is None else int(seed)), log_fn=None)
```
（`infer` の `ref_wav = self._ref_cache.get(...)` → `ref_path = ...`、`self._synthesize_ref(text, caption, seed, ref_path)` に変数名追従。挙動同じ。）
- [ ] **Step 3: import確認＋テスト**
`cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -c "import vd_server.backend; print('ok')" && .venv/Scripts/python.exe -m pytest -q`（20 passed・FakeBackend経路不変）
- [ ] **Step 4: バンドル更新**: `cp -f vd_server/*.py irodori-vd-runtime/Lib/site-packages/vd_server/`
- [ ] **Step 5: commit**: `feat(vd-server): use ref_latent (encode_waveform) to avoid torchcodec`

---

### Task 2: アプリ engine_for 純粋関数【pytest・GPU-free】

**Repo:** DocuListenLLM / **Files:** `irodori_engine.py`, `tests/test_irodori_engine.py`

**Produces:** `engine_for(category, global_engine, category_engines) -> "voicevox"|"irodori"`
- global が "voicevox"/"irodori" → そのまま。"mixed" → `category_engines.get(正規化category, "voicevox")`。
- 地の文系カテゴリは `"__narrator__"` キーで引く（caption/seed と整合）。

- [ ] **Step 1: 失敗テスト（追記）**
```python
def test_engine_for_global_overrides():
    from irodori_engine import engine_for
    assert engine_for("主人公 男", "voicevox", {"主人公 男": "irodori"}) == "voicevox"
    assert engine_for("主人公 男", "irodori", {}) == "irodori"


def test_engine_for_mixed_uses_category_map():
    from irodori_engine import engine_for
    ce = {"主人公 男": "irodori", "__narrator__": "voicevox"}
    assert engine_for("主人公 男", "mixed", ce) == "irodori"
    assert engine_for("ナレーション", "mixed", ce) == "voicevox"   # 地の文→narratorキー
    assert engine_for("中年 女", "mixed", ce) == "voicevox"        # 未設定→既定voicevox
```
- [ ] **Step 2: 失敗確認** `py -m pytest tests/test_irodori_engine.py -q`
- [ ] **Step 3: 実装（末尾に追記）**
```python
def engine_for(category: str, global_engine: str, category_engines: dict) -> str:
    if global_engine in ("voicevox", "irodori"):
        return global_engine
    # mixed
    cat = (category or "").strip()
    key = _NARRATION_SEED_KEY if (cat in _NARRATION_CATEGORIES or cat not in DEFAULT_CAPTIONS) else cat
    val = (category_engines or {}).get(key, "voicevox")
    return "irodori" if val == "irodori" else "voicevox"
```
- [ ] **Step 4: PASS** `py -m pytest tests/test_irodori_engine.py -q`（19+3=22）
- [ ] **Step 5: commit**: `feat(irodori): engine_for (per-category engine routing)`

---

### Task 3: アプリ main.py 設定＋producer 振り分け【py_compile・GPU-free】

**Repo:** DocuListenLLM / **Files:** `main.py`

- [ ] **Step 1: 設定既定＋ロード**（Irodori既定ブロックに）
```python
        _s.setdefault("category_engines", {})
        self._category_engines: dict[str, str] = dict(_s.get("category_engines", {}))
```
- [ ] **Step 2: `_save_settings` 追記**
```python
            "category_engines": {c: v for c, v in self._category_engines.items()} if hasattr(self, "_category_engines") else self._settings.get("category_engines", {}),
```
- [ ] **Step 3: producer スナップショットに追加**（`_use_ref`/`_seeds` の隣）
```python
            _global_engine = _engine  # "voicevox"/"irodori"/"mixed"
            _cat_engines = dict(self._category_engines)
```
- [ ] **Step 4: producer 冒頭の遅延起動条件を mixed 対応に**
`if _engine == "irodori":` を、Irodoriを使う可能性で判定するよう変更:
```python
            _needs_irodori = (_global_engine == "irodori"
                              or (_global_engine == "mixed"
                                  and any(v == "irodori" for v in _cat_engines.values())))
            if _needs_irodori:
                try:
                    ok = self._irodori.ensure_running(...)   # 既存の中身そのまま
                ...
```
- [ ] **Step 5: producer 合成分岐をチャンク毎エンジンに**
`if _engine == "irodori":` の分岐を、チャンクの category から決定するよう変更:
```python
                    # チャンク毎のカテゴリ→エンジン
                    if self._script and chunk_idx < len(self._script):
                        _cat = self._script[chunk_idx].get("category", "ナレーション")
                    else:
                        _cat = "ナレーション"
                    _chunk_engine = irodori_engine.engine_for(_cat, _global_engine, _cat_engines)
                    if _chunk_engine == "irodori":
                        caption = irodori_engine.resolve_caption(_cat, _caption_map, _narr_caption)
                        seed = irodori_engine.voice_seed_for(_cat, _seeds)
                        ...（既存 Irodori 合成: synthesize_irodori(..., seed=seed, use_ref=_use_ref)）...
                    else:
                        ...（既存 VOICEVOX 合成: audio_query→synthesis）...
```
（従来の `cat`/`caption` 取得行は `_cat`/上記に統合。`speaker_id` はVOX分岐で従来通り使用。）
- [ ] **Step 6: py_compile** `py -m py_compile main.py`
- [ ] **Step 7: commit**: `feat(irodori): per-chunk engine routing in producer + lazy launch for mixed`

---

### Task 4: アプリ main.py UI（global 3択＋行毎エンジン）【手動】

**Repo:** DocuListenLLM / **Files:** `main.py`

- [ ] **Step 1: トップバーのエンジン選択を3択に**
`ctk.CTkOptionMenu(... values=["voicevox", "irodori"] ...)` を `values=["voicevox", "irodori", "mixed"]` に。
- [ ] **Step 2: 各役＋ナレーター行にエンジン選択ドロップダウン（column=5）**
各役の if ブロック内（🎲 の隣）:
```python
                _eng_init = self._category_engines.get(archetype, "voicevox")
                _eng_var = ctk.StringVar(value=_eng_init)
                def _on_eng(v, c=archetype):
                    self._category_engines[c] = v
                    self._save_settings()
                ctk.CTkOptionMenu(scroll, values=["voicevox", "irodori"], variable=_eng_var,
                                  width=92, command=_on_eng).grid(
                    row=row_idx, column=5, padx=(4, 0), pady=2)
```
ナレーター行（`_nar_row`）にも同様（`c="__narrator__"`、column=5）。
- [ ] **Step 3: 手動確認** `py main.py`（global=mixed で各行エンジン選択が出る／保存される）
- [ ] **Step 4: commit**: `feat(irodori): global mixed mode + per-category engine dropdowns`

---

### Task 5: E2E（GPU・手動）
- [ ] バンドル更新確認＋ `py main.py`：
  1. global=irodori＋声固定ON → **声がカテゴリ毎に一貫**（ref_latent修正の確認）。
  2. global=mixed → ナレーター=voicevox / 主役=irodori 等に設定 → **チャンク毎に正しいエンジンで読み上げ**。
  3. global=voicevox → 従来通り（後方互換）。
- [ ] handoff 更新。

## Self-Review
- ref_latent で torchcodec 回避（Task1）／engine_for 純粋関数＋pytest（Task2）／producer 振り分け＋mixed遅延起動（Task3）／UI（Task4）／E2E（Task5）。
- 後方互換: category_engines 既定空・global voicevox → 非破壊。FakeBackend/既存テスト不変。
- 型整合: `engine_for(category,global,category_engines)->str`、`_synthesize_ref(text,caption,seed,ref_path)`、`encode_waveform(...)->(B,T,D)`。
