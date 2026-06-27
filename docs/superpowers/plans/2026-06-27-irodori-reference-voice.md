# Irodori 参照音声による声の固定（サブPJ-2b）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

> 方針: lean（動く一本通し優先）。核心ロジックは pytest、GUI/GPU は手動。後方互換厳守。
> **2リポジトリにまたがる**: サーバ=`E:\project\IrodoriVDServer`（venv `.venv` Python3.12）、アプリ=`E:\project\DocuListenLLM`（`py`=Python3.14）。

**Goal:** カテゴリ毎に基準音声を自動生成・キャッシュし、その声でクローン合成することで、同カテゴリ（特にナレーション）の声を一貫させる。🎲で声を選び直せる。

**Architecture:** サーバ `/synthesize` に `use_ref` を追加し、`(caption,seed)` 毎に基準音声を1回生成→インメモリキャッシュ→ref_wavでクローン。キャッシュ判断は model 非依存の `RefCache` に分離してテスト可能化。アプリはカテゴリ毎seed＋声固定フラグを送るだけ。

**Tech Stack:** サーバ: FastAPI/pydantic, soundfile, irodori_tts（`SamplingRequest(ref_wav, no_ref=False)`）, pytest。アプリ: customtkinter, requests, pytest。

## Global Constraints
- 後方互換: `use_ref` 無し/False＝2aの caption-only と**完全同一**。`FakeBackend` は `use_ref` を受けるが音は不変。
- サーバ HTTP: `POST /synthesize {text, caption, speed?, seed?, use_ref?: bool=False}` → `audio/wav`。pydantic 余剰フィールド無視（前方互換）。
- サーバの基準フレーズ定数 `REF_PHRASE = "こんにちは。今日はいい天気ですね。少しお話しします。"`。
- 基準音声キャッシュは `(caption, seed)` キー・インメモリ・`threading.Lock` 下。
- アプリ設定: `caption_seeds: dict[str,int]`（14カテゴリ名＋`"__narrator__"`）、`irodori_use_ref: bool`（既定 True）。
- ref生成/クローン失敗時は caption-only にフォールバック（無音化させない）。
- サーバのテスト/実行は IrodoriVDServer の `.venv/Scripts/python.exe`。アプリは `py`（3.14）。
- 各リポジトリ内で各タスク末尾にコミット。

---

### Task 1: サーバ RefCache（model非依存・キャッシュ責務）

**Repo:** `E:\project\IrodoriVDServer`
**Files:** Create `vd_server/ref_cache.py`, Test `tests/test_ref_cache.py`

**Interfaces:**
- Produces: `vd_server.ref_cache.RefCache(generate)` — `generate(caption: str, seed) -> str`（基準WAVパスを返す callable）。
  - `.get(caption: str, seed) -> str`: `(caption, seed)` 毎に `generate` を**1回だけ**呼びパスをキャッシュ・再利用。
  - スレッド安全（内部 `threading.Lock`）。

- [ ] **Step 1: 失敗するテスト**
```python
# tests/test_ref_cache.py
from vd_server.ref_cache import RefCache


def test_generates_once_per_key():
    calls = []
    rc = RefCache(lambda cap, seed: calls.append((cap, seed)) or f"/tmp/{cap}_{seed}.wav")
    p1 = rc.get("calm", 1)
    p2 = rc.get("calm", 1)
    assert p1 == p2 == "/tmp/calm_1.wav"
    assert len(calls) == 1                 # 同キーは1回だけ生成


def test_distinct_keys_generate_separately():
    calls = []
    rc = RefCache(lambda cap, seed: calls.append((cap, seed)) or f"{cap}-{seed}")
    rc.get("calm", 1)
    rc.get("calm", 2)
    rc.get("angry", 1)
    assert len(calls) == 3                 # caption/seed が違えば別生成
```

- [ ] **Step 2: 失敗確認**
Run: `cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -m pytest tests/test_ref_cache.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 実装**
```python
# vd_server/ref_cache.py
import threading


class RefCache:
    """(caption, seed) 毎に基準音声を1回だけ生成してキャッシュする（model非依存）。"""

    def __init__(self, generate):
        self._generate = generate
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, caption: str, seed) -> str:
        key = (caption, seed)
        with self._lock:
            path = self._cache.get(key)
            if path is None:
                path = self._generate(caption, seed)
                self._cache[key] = path
            return path
```

- [ ] **Step 4: 成功確認**
Run: `cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -m pytest tests/test_ref_cache.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: コミット**
```bash
cd /e/project/IrodoriVDServer && git add vd_server/ref_cache.py tests/test_ref_cache.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(vd-server): RefCache (generate-once per caption+seed)"
```

---

### Task 2: サーバ `/synthesize` に use_ref（契約拡張・FakeBackend）

**Repo:** `E:\project\IrodoriVDServer`
**Files:** Modify `vd_server/app.py`, `vd_server/backend.py`(FakeBackend/Protocol), Test `tests/test_synthesize.py`

**Interfaces:**
- `SynthBackend.infer(text, caption, speed, seed, use_ref: bool = False) -> (np.ndarray, int)`
- `SynthRequest` に `use_ref: bool = False`
- `FakeBackend.infer` は `use_ref` を受け、`self.last_use_ref` に記録（音は従来通り）

- [ ] **Step 1: 失敗するテスト（tests/test_synthesize.py に追記）**
```python
def test_synthesize_passes_use_ref_to_backend():
    from vd_server.backend import FakeBackend
    from vd_server.app import create_app
    from fastapi.testclient import TestClient
    b = FakeBackend()
    client = TestClient(create_app(b))
    r = client.post("/synthesize",
                    json={"text": "あ", "caption": "x", "use_ref": True})
    assert r.status_code == 200
    assert b.last_use_ref is True


def test_synthesize_use_ref_defaults_false():
    from vd_server.backend import FakeBackend
    from vd_server.app import create_app
    from fastapi.testclient import TestClient
    b = FakeBackend()
    client = TestClient(create_app(b))
    client.post("/synthesize", json={"text": "あ", "caption": "x"})
    assert b.last_use_ref is False
```

- [ ] **Step 2: 失敗確認**
Run: `cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -m pytest tests/test_synthesize.py -q`
Expected: FAIL（`last_use_ref` 無し / TypeError）

- [ ] **Step 3: 実装**
`vd_server/backend.py` の Protocol と FakeBackend を更新:
```python
class SynthBackend(Protocol):
    ready: bool
    sample_rate: Optional[int]
    model_name: str
    load_error: Optional[str]

    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int], use_ref: bool = False) -> Tuple[np.ndarray, int]:
        ...
```
```python
class FakeBackend:
    def __init__(self, ready: bool = True, sample_rate: int = 24000, load_error: Optional[str] = None):
        self.ready = ready
        self.sample_rate = sample_rate
        self.model_name = "fake-voicedesign"
        self.load_error = load_error
        self.last_use_ref = None

    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int], use_ref: bool = False) -> Tuple[np.ndarray, int]:
        self.last_use_ref = use_ref
        n = int(self.sample_rate * 0.1)
        t = np.linspace(0, 0.1, n, endpoint=False)
        audio = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
        return audio, self.sample_rate
```
`vd_server/app.py` の `SynthRequest` と呼び出しを更新:
```python
class SynthRequest(BaseModel):
    text: str
    caption: str
    speed: float = 1.0
    seed: Optional[int] = None
    use_ref: bool = False
```
`synthesize` ハンドラの infer 呼び出しを:
```python
            with infer_lock:
                audio, sr = backend.infer(req.text, req.caption, speed, req.seed, req.use_ref)
```

- [ ] **Step 4: 成功確認**
Run: `cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS（既存16 + 新2 = 18 passed。既存テストは `infer` 既定引数で不変）

- [ ] **Step 5: コミット**
```bash
cd /e/project/IrodoriVDServer && git add vd_server/app.py vd_server/backend.py tests/test_synthesize.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(vd-server): /synthesize use_ref flag + FakeBackend records it"
```

---

### Task 3: サーバ VoiceDesignBackend に ref 生成＋クローン（GPU・手動検証）

**Repo:** `E:\project\IrodoriVDServer`
**Files:** Modify `vd_server/backend.py`（VoiceDesignBackend）

**Interfaces:**
- Consumes: `vd_server.ref_cache.RefCache`, `vd_server.wav.encode_wav_pcm16`, irodori `SamplingRequest`
- Produces: `VoiceDesignBackend.infer(text, caption, speed, seed, use_ref=False)` が `use_ref=True` で
  `(caption,seed)` の基準音声を `RefCache` 経由で1回生成→`ref_wav` クローン合成。

> GPU/モデル必須のため pytest は課さず Task 7 の手動E2Eで検証。

- [ ] **Step 1: REF_PHRASE と RefCache を __init__ に追加**
```python
# backend.py 冒頭付近（モジュール定数）
REF_PHRASE = "こんにちは。今日はいい天気ですね。少しお話しします。"
```
`VoiceDesignBackend.__init__` の最後（`_threading.Thread(...).start()` の直前）に:
```python
        import tempfile, os
        self._ref_dir = tempfile.mkdtemp(prefix="vd_ref_")
        from vd_server.ref_cache import RefCache
        self._ref_cache = RefCache(self._generate_ref)
```

- [ ] **Step 2: 基準音声生成＋ref合成メソッドを実装**
```python
    def _generate_ref(self, caption: str, seed) -> str:
        """REF_PHRASE を caption-only で1回合成し、基準WAVをファイル化してパスを返す。"""
        from vd_server.wav import encode_wav_pcm16
        res = self._synthesize(self._runtime, REF_PHRASE, caption, seed)  # no_ref=True 既存経路
        audio = res.audio.detach().to("cpu").float().numpy()
        import numpy as np
        audio = np.squeeze(audio)
        if audio.ndim == 2:
            audio = audio.T
        wav = encode_wav_pcm16(np.ascontiguousarray(audio, dtype=np.float32), int(res.sample_rate))
        import os
        path = os.path.join(self._ref_dir, f"ref_{abs(hash((caption, seed)))}.wav")
        with open(path, "wb") as f:
            f.write(wav)
        return path

    def _synthesize_ref(self, text: str, caption: str, seed, ref_wav: str):
        from irodori_tts.inference_runtime import SamplingRequest
        return self._runtime.synthesize(SamplingRequest(
            text=text, caption=caption, ref_wav=ref_wav, no_ref=False,
            num_steps=self._num_steps, cfg_scale_text=self._cfg_text,
            cfg_scale_caption=self._cfg_caption,
            seed=None if seed is None else int(seed)), log_fn=None)
```
`infer` を use_ref 対応に:
```python
    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int], use_ref: bool = False) -> Tuple[np.ndarray, int]:
        if self._runtime is None:
            raise RuntimeError("model not loaded")
        try:
            if use_ref and caption.strip():
                ref_wav = self._ref_cache.get(caption, seed)
                res = self._synthesize_ref(text, caption, seed, ref_wav)
            else:
                res = self._synthesize(self._runtime, text, caption, seed)
        except Exception as exc:  # ref失敗時は caption-only にフォールバック
            print(f"[vd_server] ref synth failed, fallback caption-only: {exc}", flush=True)
            res = self._synthesize(self._runtime, text, caption, seed)
        audio = res.audio.detach().to("cpu").float().numpy()
        audio = np.squeeze(audio)
        if audio.ndim == 2:
            audio = audio.T
        return np.ascontiguousarray(audio, dtype=np.float32), int(res.sample_rate)
```
> 注: `SamplingRequest` の `ref_wav` 引数名・必須/任意は実装時に `irodori_tts/inference_runtime.py` で再確認（spec確定値が出発点。`ref_normalize_db`/`ref_ensure_max` 等は既定のまま）。

- [ ] **Step 3: 構文確認＋起動スモーク（Task7で本検証）**
Run: `cd /e/project/IrodoriVDServer && .venv/Scripts/python.exe -c "import vd_server.backend; print('import ok')"`
Expected: import ok（GPU合成はTask7）

- [ ] **Step 4: コミット**
```bash
cd /e/project/IrodoriVDServer && git add vd_server/backend.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(vd-server): VoiceDesignBackend ref-clone via RefCache (use_ref) + fallback"
```

---

### Task 4: アプリ irodori_engine の use_ref / seed ヘルパ

**Repo:** `E:\project\DocuListenLLM`
**Files:** Modify `irodori_engine.py`, Test `tests/test_irodori_engine.py`

**Interfaces:**
- `synthesize_irodori(session, base_url, text, caption, seed=None, use_ref=False, timeout=180) -> bytes`（payload に `use_ref` 追加。True のときのみ含める）
- `voice_seed_for(category: str, seeds: dict, narrator_key: str = "__narrator__") -> int`（地の文系→narrator_key の seed、無ければ `caption_seed(category)`）
- `new_seed() -> int`（0..2^31-1 の擬似乱数。`random` 使用）

- [ ] **Step 1: 失敗するテスト（tests/test_irodori_engine.py に追記）**
```python
def test_synthesize_irodori_includes_use_ref_when_true():
    sess = _Session(_Resp(200, content=b"x"))
    synthesize_irodori(sess, "http://h", "a", "b", seed=3, use_ref=True)
    assert sess.calls[0]["json"]["use_ref"] is True


def test_synthesize_irodori_omits_use_ref_when_false():
    sess = _Session(_Resp(200, content=b"x"))
    synthesize_irodori(sess, "http://h", "a", "b")
    assert "use_ref" not in sess.calls[0]["json"]


def test_voice_seed_for_uses_category_seed_by_default():
    from irodori_engine import voice_seed_for, caption_seed
    assert voice_seed_for("主人公 男", {}) == caption_seed("主人公 男")


def test_voice_seed_for_uses_override_and_narrator():
    from irodori_engine import voice_seed_for
    seeds = {"主人公 男": 42, "__narrator__": 7}
    assert voice_seed_for("主人公 男", seeds) == 42
    assert voice_seed_for("ナレーション", seeds) == 7    # 地の文系は narrator キー


def test_new_seed_range():
    from irodori_engine import new_seed
    for _ in range(20):
        s = new_seed()
        assert 0 <= s < 2**31
```

- [ ] **Step 2: 失敗確認**
Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -q`
Expected: FAIL（ImportError / use_ref 無し）

- [ ] **Step 3: 実装（irodori_engine.py）**
`synthesize_irodori` を更新:
```python
def synthesize_irodori(session, base_url: str, text: str, caption: str,
                       seed=None, use_ref: bool = False, timeout: int = 180) -> bytes:
    payload = {"text": text, "caption": caption}
    if seed is not None:
        payload["seed"] = int(seed)
    if use_ref:
        payload["use_ref"] = True
    resp = session.post(f"{base_url}/synthesize", json=payload, timeout=timeout)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error", f"HTTP {resp.status_code}")
        except Exception:
            msg = f"HTTP {resp.status_code}"
        raise IrodoriSynthError(str(msg))
    return resp.content
```
末尾にヘルパを追加:
```python
import random as _random

_NARRATION_SEED_KEY = "__narrator__"


def voice_seed_for(category: str, seeds: dict, narrator_key: str = _NARRATION_SEED_KEY) -> int:
    cat = (category or "").strip()
    if cat in _NARRATION_CATEGORIES or cat not in DEFAULT_CAPTIONS:
        if narrator_key in seeds:
            return int(seeds[narrator_key])
        return caption_seed(narrator_key)
    if cat in seeds:
        return int(seeds[cat])
    return caption_seed(cat)


def new_seed() -> int:
    return _random.randrange(0, 2 ** 31)
```

- [ ] **Step 4: 成功確認**
Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -q`
Expected: PASS（既存14 + 新5 = 19 passed）

- [ ] **Step 5: コミット**
```bash
cd /e/project/DocuListenLLM && git add irodori_engine.py tests/test_irodori_engine.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): synthesize_irodori use_ref + voice_seed_for + new_seed"
```

---

### Task 5: アプリ main.py 設定＋producer連携

**Repo:** `E:\project\DocuListenLLM`
**Files:** Modify `main.py`（`__init__` 設定既定／`_save_settings`／`_producer` Irodori分岐）

**Interfaces:**
- Consumes: `irodori_engine.voice_seed_for`, `synthesize_irodori(use_ref=)`
- Produces: 設定 `caption_seeds`/`irodori_use_ref`、producer が use_ref＋カテゴリseed を送る。

- [ ] **Step 1: 設定既定を追加**（`__init__` の Irodori既定ブロックに追記）
```python
        _s.setdefault("irodori_use_ref", True)
        _s.setdefault("caption_seeds", {})
```

- [ ] **Step 2: `_save_settings` に追記**（data dict 内、captions の隣）
```python
            "irodori_use_ref":  self.use_ref_var.get() if hasattr(self, "use_ref_var") else self._settings.get("irodori_use_ref", True),
            "caption_seeds":    {c: int(v) for c, v in self._caption_seeds.items()} if hasattr(self, "_caption_seeds") else self._settings.get("caption_seeds", {}),
```

- [ ] **Step 3: `__init__` で `_caption_seeds` を読み込む**（設定既定ブロック直後）
```python
        self._caption_seeds: dict[str, int] = dict(self._settings.get("caption_seeds", {}))
```

- [ ] **Step 4: producer の Irodori 分岐を use_ref＋seed 対応に**
`_producer` 開始時スナップショットに追加（`_caption_map` 等の近く）:
```python
            _use_ref = self.use_ref_var.get() if hasattr(self, "use_ref_var") else self._settings.get("irodori_use_ref", True)
            _seeds = dict(self._caption_seeds)
```
Irodori 合成呼び出しを:
```python
                        caption = irodori_engine.resolve_caption(
                            cat, _caption_map, _narr_caption)
                        seed = irodori_engine.voice_seed_for(cat, _seeds)
                        self.after(0, lambda i=index, t=total: self._set_status(
                            f"Irodori 合成中... ({i}/{t})", "working"))
                        wav_bytes = irodori_engine.synthesize_irodori(
                            self._http_session, self._irodori.base_url, chunk, caption,
                            seed=seed, use_ref=_use_ref)
```

- [ ] **Step 5: 構文確認**
Run: `cd /e/project/DocuListenLLM && py -m py_compile main.py`
Expected: OK

- [ ] **Step 6: コミット**
```bash
cd /e/project/DocuListenLLM && git add main.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): settings caption_seeds/irodori_use_ref + producer ref wiring"
```

---

### Task 6: アプリ main.py UI（🎲リロール＋声固定チェック）

**Repo:** `E:\project\DocuListenLLM`
**Files:** Modify `main.py`（`_build_top_bar`／`_build_llm_archetypes_tab`）

**Interfaces:**
- Produces: `self.use_ref_var`(BooleanVar)、各役＋ナレーターの 🎲 ボタン→`self._reroll_voice(category)`。

- [ ] **Step 1: 声固定チェックボックス（_build_top_bar、engine セレクタ付近）**
```python
        self.use_ref_var = ctk.BooleanVar(value=self._settings.get("irodori_use_ref", True))
        ctk.CTkCheckBox(frame, text="声を固定", variable=self.use_ref_var,
                        onvalue=True, offvalue=False,
                        command=self._save_settings).pack(side="left", padx=(8, 0))
```

- [ ] **Step 2: リロールメソッド**
```python
    def _reroll_voice(self, category: str) -> None:
        self._caption_seeds[category] = irodori_engine.new_seed()
        self._save_settings()
        self._set_status(f"{category} の声をリロールしました（次の再生で反映）", "ok")
```

- [ ] **Step 3: 各役行に 🎲 ボタン（_build_llm_archetypes_tab、キャプション欄の隣 column=4）**
キャプション Entry を作る箇所（`if archetype in irodori_engine.DEFAULT_CAPTIONS:` ブロック内）の直後に:
```python
                ctk.CTkButton(scroll, text="🎲", width=32,
                              command=lambda c=archetype: self._reroll_voice(c)).grid(
                    row=row_idx, column=4, padx=(4, 0), pady=2)
```
ナレーター行（`_nar_row`）にも:
```python
        ctk.CTkButton(scroll, text="🎲", width=32,
                      command=lambda: self._reroll_voice("__narrator__")).grid(
            row=_nar_row, column=4, padx=(4, 0), pady=2)
```

- [ ] **Step 4: 手動確認**
Run: `cd /e/project/DocuListenLLM && py main.py`
手順: 「声を固定」チェックが出る／各役＋ナレーターに 🎲 が並ぶ／🎲押下でステータス表示・設定保存（再起動で `caption_seeds` 保持）。

- [ ] **Step 5: コミット**
```bash
cd /e/project/DocuListenLLM && git add main.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): voice-lock checkbox + per-category reroll buttons"
```

---

### Task 7: バンドル更新＋E2E（GPU・手動）

**Repos:** 両方
**Files:** （コード変更なし。バンドル再コピー＋実走）

- [ ] **Step 1: 配布バンドルの vd_server を更新（dev確認用）**
```bash
cp -f /e/project/IrodoriVDServer/vd_server/*.py /e/project/IrodoriVDServer/irodori-vd-runtime/Lib/site-packages/vd_server/
rm -rf /e/project/IrodoriVDServer/irodori-vd-runtime/Lib/site-packages/vd_server/__pycache__
# ref_cache.py も含まれることを確認
ls /e/project/IrodoriVDServer/irodori-vd-runtime/Lib/site-packages/vd_server/
```
（正式な配布は `build_vd_bundle.ps1` の `pip install <clone> --no-deps` で焼き込み。）

- [ ] **Step 2: E2E（VOICEVOX/Ollama起動・GPU空き状態で）**
Run: `cd /e/project/DocuListenLLM && py main.py`
手順・期待:
1. エンジン=irodori、「声を固定」ON でテキスト再生 → 初回に各声の基準生成（+数秒）後、**ナレーションが終始同じ声・カテゴリ毎に固定声**。
2. 🎲（例: ナレーター）押下→再生→**声が変わる**。
3. 「声を固定」OFF→再生→2aの caption-only 挙動（声が揺れる）に戻る（後方互換）。
4. 既存 VOICEVOX 再生も従来通り。

- [ ] **Step 3: handoff 更新**
`handoff.md §8` に 2b 完了（声固定・🎲リロール）を日付付きで追記。

---

## Self-Review
- spec カバレッジ: サーバ use_ref/refキャッシュ(Task1,2,3)・REF_PHRASE(Task3)・アプリ use_ref/seed/reroll(Task4,5,6)・UI(Task6)・後方互換(Task2,4,5 既定False/設定)・フォールバック(Task3)・バンドル(Task7) → 各Task対応 ✓
- model非依存でテスト可能化: キャッシュ責務を `RefCache` に分離（Task1）→ GPUなしで pytest ✓。GPU必須の VoiceDesignBackend(Task3) は手動E2E(Task7)。
- placeholder: Task3 の `SamplingRequest(ref_wav=...)` 引数は「実装時に inference_runtime.py で再確認」と明示（外部モデルAPI依存の不可避な確認点）。
- 型整合: `infer(...,use_ref=False)`・`synthesize_irodori(...,use_ref=False)`・`voice_seed_for(category,seeds)->int`・`RefCache(generate).get(caption,seed)->str` は全Taskで一貫 ✓
- 後方互換: `use_ref` 既定False・FakeBackend無視・設定既定で2a不変 ✓

## 次（本プラン完了後）
- サブPJ-2c（任意）: 感情/スタイル分類LLM で caption を動的化（喜怒哀楽）。ref で声を固定したまま caption で感情を載せる 3-factor。
