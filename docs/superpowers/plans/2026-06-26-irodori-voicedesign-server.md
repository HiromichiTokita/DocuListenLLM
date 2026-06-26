# Irodori VoiceDesign HTTPサーバ Implementation Plan（再計画 v2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 旧プラン `2026-06-25-irodori-voicedesign-server.md` の作り直し。設計は踏襲（変更なし）。
> 前回は Task1（WAVエンコーダ）と Task3（/health）まで着手したが、作業先が**クローン取得物**
> （`Irodori-TTS-code`）だったため成果物が消失。今回は **独立した新フォルダ `E:\project\IrodoriVDServer`**
> に独自gitリポジトリを作り、`irodori_tts` はクローンから editable install で参照する。
> **Task 0 でリポジトリ初期化＋ベースラインコミットし、各 Task 末尾で必ずコミット**して再発を防ぐ。
> 設計of record: `docs/superpowers/specs/2026-06-25-irodori-voicedesign-server-design.md`。

**Goal:** Irodori VoiceDesign を `POST /synthesize`（`{text, caption}` → WAV）で公開する小さなローカルHTTPサーバを作り、配布用のポータブルPython同梱フォルダまで用意する。

**Architecture:** 純粋な HTTP/検証/WAVエンコード層（GPU不要・FakeBackendで単体テスト可能）と、重い Irodori 推論層（`VoiceDesignBackend`、GPU+モデル必須・curlで受け入れ検証）を分離する。FastAPI + uvicorn 単一ワーカー、GPU推論は `threading.Lock` で直列化。配布は **ポータブルPython同梱フォルダ**（torchはPyInstallerに通さず埋め込みPythonへ）にし、本体アプリ(サブPJ-2)が自動起動する。

**Tech Stack:** Python 3.11/3.12（torch+CUDA12.8 の venv）, FastAPI, uvicorn, soundfile, numpy, pytest, httpx(TestClient), Irodori-TTS（`Aratako/Irodori-TTS-600M-v3-VoiceDesign`）。

## Global Constraints

- 配置先は **新規独立フォルダ `E:\project\IrodoriVDServer`**（独自gitリポジトリ・独自venv・別プロセス）。DocuListen 本体(Python3.14)とは別。git コミットはこの新フォルダ内で行う。
- **`Irodori-TTS-code`（上流コードのクローン）と `IrodoriTTS`（モデル重みのクローン）はどちらもクローン取得物なので成果物を置かない。** `irodori_tts` パッケージは `Irodori-TTS-code` から **editable install**（`pip install -e E:\project\Irodori-TTS-code`）で参照し、モデル重みは `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors` を**読み取り専用 checkpoint** として参照する。
- **本体リポジトリ(DocuListenLLM)のコードは触らない。** 例外は `handoff.md`（進捗記録、Task 8）。
- **caption-only 運用**（`--no-ref` 相当）。男女・声質・感情はすべてキャプションで表現。参照音声併用はスコープ外。
- ベースURL `http://127.0.0.1:8770`（ポートは CLI 引数 `--port` で可変、既定 8770）。
- 既定チェックポイント `Aratako/Irodori-TTS-600M-v3-VoiceDesign`、`--device cuda`。
- レスポンスWAVは **16-bit PCM（soundfile `subtype="PCM_16"`）**、SRはモデル出力のもの（**48000Hz**）を wav ヘッダに埋める。
- `speed` は **0.25–4.0 に clamp**するが**モデルには渡さない**（速度は本体consumerの`_time_stretch`が担当）。`/synthesize` は **GPU推論を直列化**（同時1件）。
- ステータス規約: 成功 200(audio/wav)／入力不正 400(JSON `{"error":..}`)／未ロード 503／推論失敗 500。
- OpenAI互換にはしない（独自最小API）。
- **進捗があれば本体の `handoff.md` §8 を更新する**（DocuListenLLM プロジェクトルール）。

### 確認済みの実API（2026-06-26、`E:\project\Irodori-TTS-code` で確定）
- `InferenceRuntime.from_key(RuntimeKey(checkpoint, model_device, codec_repo, model_precision, codec_device, codec_precision, codec_deterministic_encode, codec_deterministic_decode, compile_model, compile_dynamic))`
- `runtime.synthesize(SamplingRequest(text, caption, no_ref=True, num_steps=40, cfg_scale_text=3.0, cfg_scale_caption=3.0, seed=...), log_fn=None)` → `SamplingResult(audio: torch.Tensor, sample_rate: int, used_seed, audios, ...)`
- `SamplingRequest` は `text` のみ必須。caption-only は `no_ref=True`＋`caption`。出力 **48kHz**。`audio` は torch.Tensor。

---

### Task 0: 新規ワークスペースとベースラインの確保（成果物消失の再発防止）

**Files:**
- Create: `E:\project\IrodoriVDServer\`（新規フォルダ・独立gitリポジトリ）
- Create: `pyproject.toml`（最小・`vd_server` を import 可能にする）
- Create: `.gitignore`
- Create: 独自 venv `.venv`（Python 3.11/3.12）

**Interfaces:**
- Consumes: なし
- Produces: `E:\project\IrodoriVDServer` の git リポジトリ＋ venv（サーバ依存導入済み）、`vd_server` を editable install できる `pyproject.toml`

- [ ] **Step 1: 新規フォルダと git リポジトリを作る**

```bash
mkdir -p /e/project/IrodoriVDServer
cd /e/project/IrodoriVDServer
git init
git config --global --add safe.directory E:/project/IrodoriVDServer
```
Expected: `Initialized empty Git repository`。

- [ ] **Step 2: 独自 venv を作成（Python 3.11/3.12）**

```bash
# 3.12 を想定（torch cu128 wheel があるバージョン）。py ランチャで明示。
py -3.12 -m venv .venv
.venv/Scripts/python.exe --version
```
Expected: `Python 3.12.x`（無ければ 3.11 で代替）。

- [ ] **Step 3: 最小 pyproject.toml を作成**

```toml
# pyproject.toml
[project]
name = "vd-server"
version = "0.1.0"
description = "Irodori VoiceDesign HTTP server for DocuListen"
requires-python = ">=3.11"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["vd_server*"]
```

- [ ] **Step 4: .gitignore を作成**

```gitignore
.venv/
__pycache__/
*.wav
irodori-vd-runtime/
py.tar.gz
*.egg-info/
```

- [ ] **Step 5: サーバ依存（GPU不要分）を venv に入れる**

Task 1–4 は torch/irodori_tts 不要。先に純Python依存だけ入れてTDDを回せるようにする。
```bash
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install fastapi "uvicorn[standard]" soundfile numpy pytest httpx
```
Expected: 正常インストール。（torch + `pip install -e E:\project\Irodori-TTS-code` は Task 5 で追加。）

- [ ] **Step 6: ベースラインをコミット**

```bash
git add pyproject.toml .gitignore
git commit -m "chore(vd-server): new workspace baseline (pyproject, gitignore)"
```

> 以降の Task 1–7 のコマンド `python` / `pytest` は、この新フォルダの
> `.venv/Scripts/python.exe` を指す（例: `.venv/Scripts/python.exe -m pytest ...`）。
> カレントディレクトリは常に `E:\project\IrodoriVDServer`。

---

### Task 1: WAVエンコーダ（純粋関数）

**Files:**
- Create: `vd_server/__init__.py`
- Create: `vd_server/wav.py`
- Test: `tests/test_wav.py`

**Interfaces:**
- Consumes: なし
- Produces: `vd_server.wav.encode_wav_pcm16(audio: np.ndarray, sample_rate: int) -> bytes`（float32/任意shapeの mono(1D) または (N,ch) を 16-bit PCM WAV バイト列にする）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wav.py
import io
import numpy as np
import soundfile as sf
from vd_server.wav import encode_wav_pcm16


def test_encode_roundtrip_mono():
    audio = (np.sin(np.linspace(0, 6.28, 2400)) * 0.5).astype(np.float32)
    data = encode_wav_pcm16(audio, 24000)
    assert isinstance(data, bytes) and len(data) > 44  # WAVヘッダ超え
    back, sr = sf.read(io.BytesIO(data), dtype="float32")
    assert sr == 24000
    assert back.shape[0] == 2400
    assert np.max(np.abs(back)) > 0.1  # 無音でない


def test_encode_subtype_is_pcm16():
    audio = np.zeros(100, dtype=np.float32)
    info = sf.info(io.BytesIO(encode_wav_pcm16(audio, 16000)))
    assert info.subtype == "PCM_16"
    assert info.samplerate == 16000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wav.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'vd_server.wav'`）

- [ ] **Step 3: Write minimal implementation**

```python
# vd_server/__init__.py
# (空でよい)
```

```python
# vd_server/wav.py
import io
import numpy as np
import soundfile as sf


def encode_wav_pcm16(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 numpy 音声を 16-bit PCM WAV バイト列に変換する。"""
    arr = np.asarray(audio, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, arr, int(sample_rate), format="WAV", subtype="PCM_16")
    return buf.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wav.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add vd_server/__init__.py vd_server/wav.py tests/test_wav.py
git commit -m "feat(vd-server): add PCM_16 WAV encoder"
```

---

### Task 2: バックエンド・インターフェイスと FakeBackend

**Files:**
- Create: `vd_server/backend.py`
- Test: `tests/test_backend.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `vd_server.backend.SynthBackend`（Protocol）: 属性 `ready: bool`, `sample_rate: int | None`, `model_name: str`、メソッド `infer(text: str, caption: str, speed: float, seed: int | None) -> tuple[np.ndarray, int]`
  - `vd_server.backend.FakeBackend(ready: bool = True, sample_rate: int = 24000)`: 上記を満たすテスト用実装。`infer` は長さ `int(sample_rate*0.1)` の正弦波(float32)と `sample_rate` を返す。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend.py
import numpy as np
from vd_server.backend import FakeBackend


def test_fake_ready_and_metadata():
    b = FakeBackend()
    assert b.ready is True
    assert b.sample_rate == 24000
    assert isinstance(b.model_name, str) and b.model_name


def test_fake_infer_returns_audio_and_sr():
    b = FakeBackend(sample_rate=16000)
    audio, sr = b.infer("こんにちは", "落ち着いた声で", 1.0, None)
    assert sr == 16000
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert audio.shape[0] == 1600
    assert np.max(np.abs(audio)) > 0.1


def test_fake_not_ready():
    assert FakeBackend(ready=False).ready is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backend.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'vd_server.backend'`）

- [ ] **Step 3: Write minimal implementation**

```python
# vd_server/backend.py
from typing import Optional, Protocol, Tuple
import numpy as np


class SynthBackend(Protocol):
    ready: bool
    sample_rate: Optional[int]
    model_name: str

    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int]) -> Tuple[np.ndarray, int]:
        ...


class FakeBackend:
    """テスト用。モデルをロードせず正弦波を返す。"""

    def __init__(self, ready: bool = True, sample_rate: int = 24000):
        self.ready = ready
        self.sample_rate = sample_rate
        self.model_name = "fake-voicedesign"

    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int]) -> Tuple[np.ndarray, int]:
        n = int(self.sample_rate * 0.1)
        t = np.linspace(0, 0.1, n, endpoint=False)
        audio = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
        return audio, self.sample_rate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backend.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add vd_server/backend.py tests/test_backend.py
git commit -m "feat(vd-server): add SynthBackend protocol and FakeBackend"
```

---

### Task 3: FastAPI アプリと `/health`

**Files:**
- Create: `vd_server/app.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `vd_server.backend.FakeBackend`
- Produces: `vd_server.app.create_app(backend: SynthBackend) -> fastapi.FastAPI`（`/health` を実装。`/synthesize` は Task 4 で追加）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health.py
from fastapi.testclient import TestClient
from vd_server.app import create_app
from vd_server.backend import FakeBackend


def test_health_ready():
    client = TestClient(create_app(FakeBackend(ready=True, sample_rate=24000)))
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["sample_rate"] == 24000
    assert "model" in body


def test_health_loading():
    client = TestClient(create_app(FakeBackend(ready=False)))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["ready"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'vd_server.app'`）

- [ ] **Step 3: Write minimal implementation**

```python
# vd_server/app.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from vd_server.backend import SynthBackend


def create_app(backend: SynthBackend) -> FastAPI:
    app = FastAPI(title="Irodori VoiceDesign Server")

    @app.get("/health")
    def health():
        if not backend.ready:
            return JSONResponse(
                status_code=503,
                content={"status": "loading", "ready": False},
            )
        return {
            "status": "ok",
            "ready": True,
            "sample_rate": backend.sample_rate,
            "model": backend.model_name,
        }

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add vd_server/app.py tests/test_health.py
git commit -m "feat(vd-server): add FastAPI app with /health"
```

---

### Task 4: `/synthesize`（検証・clamp・直列化・エラー対応）

**Files:**
- Modify: `vd_server/app.py`
- Test: `tests/test_synthesize.py`

**Interfaces:**
- Consumes: `vd_server.backend.SynthBackend`, `vd_server.wav.encode_wav_pcm16`
- Produces: `create_app` に `POST /synthesize` を追加。リクエスト JSON `{"text": str, "caption": str, "speed": float=1.0, "seed": int|null}`。成功時 200・`Content-Type: audio/wav`・16-bit PCM WAV バイト列。検証失敗 400・未ロード 503・推論例外 500（いずれも JSON `{"error": str}`）。GPU直列化のため `threading.Lock` で `backend.infer` をくくる。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesize.py
import io
import threading
import time
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
from vd_server.app import create_app
from vd_server.backend import FakeBackend


def _client(**kw):
    return TestClient(create_app(FakeBackend(**kw)))


def test_synthesize_success_returns_wav():
    r = _client().post("/synthesize",
                       json={"text": "こんにちは。", "caption": "落ち着いた声で。"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    audio, sr = sf.read(io.BytesIO(r.content), dtype="float32")
    assert sr == 24000 and audio.shape[0] > 0


def test_synthesize_empty_text_is_400():
    r = _client().post("/synthesize", json={"text": "   ", "caption": "x"})
    assert r.status_code == 400
    assert "error" in r.json()


def test_synthesize_missing_caption_is_400():
    r = _client().post("/synthesize", json={"text": "あ"})
    assert r.status_code == 400


def test_synthesize_invalid_json_is_400():
    r = _client().post("/synthesize", data="not json",
                       headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_synthesize_not_ready_is_503():
    r = _client(ready=False).post("/synthesize",
                                  json={"text": "あ", "caption": "x"})
    assert r.status_code == 503


def test_synthesize_clamps_speed():
    r = _client().post("/synthesize",
                       json={"text": "あ", "caption": "x", "speed": 99.0})
    assert r.status_code == 200


def test_synthesize_backend_error_is_500():
    class Boom(FakeBackend):
        def infer(self, *a, **k):
            raise RuntimeError("boom")
    client = TestClient(create_app(Boom()))
    r = client.post("/synthesize", json={"text": "あ", "caption": "x"})
    assert r.status_code == 500
    assert "error" in r.json()


def test_synthesize_serialized_by_lock():
    active = {"now": 0, "max": 0}
    lk = threading.Lock()

    class Slow(FakeBackend):
        def infer(self, *a, **k):
            with lk:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.05)
            with lk:
                active["now"] -= 1
            return super().infer(*a, **k)

    client = TestClient(create_app(Slow()))

    def call():
        client.post("/synthesize", json={"text": "あ", "caption": "x"})

    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert active["max"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: FAIL（`/synthesize` 未実装で 404 等）

- [ ] **Step 3: Write minimal implementation**

`vd_server/app.py` を以下に置き換える（`/health` は維持しつつ `/synthesize` と各種ハンドラを追加）:

```python
# vd_server/app.py
import threading
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError
from vd_server.backend import SynthBackend
from vd_server.wav import encode_wav_pcm16

SPEED_MIN, SPEED_MAX = 0.25, 4.0


class SynthRequest(BaseModel):
    text: str
    caption: str
    speed: float = 1.0
    seed: Optional[int] = None


def create_app(backend: SynthBackend) -> FastAPI:
    app = FastAPI(title="Irodori VoiceDesign Server")
    infer_lock = threading.Lock()

    @app.get("/health")
    def health():
        if not backend.ready:
            return JSONResponse(status_code=503,
                                content={"status": "loading", "ready": False})
        return {"status": "ok", "ready": True,
                "sample_rate": backend.sample_rate, "model": backend.model_name}

    @app.post("/synthesize")
    async def synthesize(request: Request):
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(status_code=400,
                                content={"error": "invalid JSON body"})
        try:
            req = SynthRequest(**raw)
        except (ValidationError, TypeError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        if not req.text.strip():
            return JSONResponse(status_code=400,
                                content={"error": "text must not be empty"})
        if not req.caption.strip():
            return JSONResponse(status_code=400,
                                content={"error": "caption must not be empty"})

        if not backend.ready:
            return JSONResponse(status_code=503,
                                content={"status": "loading", "ready": False})

        speed = max(SPEED_MIN, min(SPEED_MAX, req.speed))
        try:
            with infer_lock:
                audio, sr = backend.infer(req.text, req.caption, speed, req.seed)
            wav = encode_wav_pcm16(audio, sr)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})
        return Response(content=wav, media_type="audio/wav")

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthesize.py tests/test_health.py -v`
Expected: PASS（health 2 + synthesize 8、計 10 passed）

- [ ] **Step 5: Commit**

```bash
git add vd_server/app.py tests/test_synthesize.py
git commit -m "feat(vd-server): add /synthesize with validation, clamp, lock, error mapping"
```

---

### Task 5: 実 VoiceDesignBackend と CLI 起動（GPU統合）

**Files:**
- Modify: `vd_server/backend.py`
- Create: `vd_server/__main__.py`

**Interfaces:**
- Consumes: Irodori-TTS の VoiceDesign 推論API（Global Constraints に確定済み）、`vd_server.app.create_app`
- Produces:
  - `vd_server.backend.VoiceDesignBackend(checkpoint: str, device: str = "cuda")`: `SynthBackend` を満たす。`__init__` で**バックグラウンドロード開始**、完了まで `ready=False`、完了後 `ready=True`・`sample_rate` 設定。`infer(text, caption, speed, seed)` は **caption-only（no-ref）**。
  - `python -m vd_server --host 127.0.0.1 --port 8770 --checkpoint <hf> --device cuda` で uvicorn 単一ワーカー起動。

> 本Taskはモデル・GPU必須のため pytest 単体テストは課さず、Step 4 と Task 6 の curl 受け入れ検証で確認する。

- [ ] **Step 0: torch(cu128) と irodori_tts を新フォルダの venv に入れる**

`E:\project\IrodoriVDServer` の venv に GPU依存を追加する（数GB DL）。
```bash
cd /e/project/IrodoriVDServer
.venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python.exe -m pip install -e E:/project/Irodori-TTS-code
.venv/Scripts/python.exe -c "import torch, irodori_tts; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
```
Expected: `cuda True`、`irodori_tts` import 成功。
（`Irodori-TTS-code` が `uv` 前提でpip editable不可の場合は、その `.venv` の site-packages を流用するか、`PYTHONPATH` に `E:\project\Irodori-TTS-code` を追加する方式へ切替。Step 1 で判断。）

- [ ] **Step 1: 実APIの最終確認（caption-only 推論を1回通す）**

クローン `E:\project\Irodori-TTS-code` の `infer.py` を新フォルダのvenvで実行（モデル重みは読み取り専用参照）:
```bash
.venv/Scripts/python.exe E:/project/Irodori-TTS-code/infer.py \
  --checkpoint E:/project/DocuListenLLM/IrodoriTTS/model.safetensors \
  --text "こんにちは。これはテストです。" \
  --caption "落ち着いた女性の声で、近い距離感でやわらかく自然に読み上げてください。" \
  --no-ref --model-device cuda --codec-device cuda --output-wav vd_test.wav
```
Expected: `vd_test.wav` が生成され再生可能。ログで出力SR（48000）を確認。
（`infer.py` の実引数名が異なる場合は `--help` で確認して読み替える。`RuntimeKey`/`SamplingRequest` の引数は Global Constraints の確定値に従う。）

- [ ] **Step 2: `VoiceDesignBackend` を実装**

```python
# vd_server/backend.py に追記
import threading as _threading
from typing import Optional, Tuple
import numpy as np


class VoiceDesignBackend:
    """Irodori VoiceDesign を caption-only でロード・推論する実バックエンド。"""

    def __init__(self, checkpoint: str, device: str = "cuda",
                 codec_repo: str = "Aratako/Semantic-DACVAE-Japanese-32dim",
                 num_steps: int = 40, cfg_scale_text: float = 3.0,
                 cfg_scale_caption: float = 3.0):
        self.ready = False
        self.sample_rate: Optional[int] = None
        self.model_name = checkpoint
        self._device = device
        self._codec_repo = codec_repo
        self._num_steps = num_steps
        self._cfg_text = cfg_scale_text
        self._cfg_caption = cfg_scale_caption
        self._runtime = None
        _threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        rt = InferenceRuntime.from_key(RuntimeKey(
            checkpoint=self.model_name, model_device=self._device,
            codec_repo=self._codec_repo, model_precision="fp32",
            codec_device=self._device, codec_precision="fp32",
            codec_deterministic_encode=True, codec_deterministic_decode=True,
            compile_model=False, compile_dynamic=False))
        res = self._synthesize(rt, "テスト", "落ち着いた声で。", None)  # ウォームアップ
        self._runtime = rt
        self.sample_rate = int(res.sample_rate)
        self.ready = True

    def _synthesize(self, rt, text: str, caption: str, seed: Optional[int]):
        from irodori_tts.inference_runtime import SamplingRequest
        return rt.synthesize(SamplingRequest(
            text=text, caption=caption, no_ref=True,
            num_steps=self._num_steps, cfg_scale_text=self._cfg_text,
            cfg_scale_caption=self._cfg_caption,
            seed=None if seed is None else int(seed)), log_fn=None)

    def infer(self, text: str, caption: str, speed: float,
              seed: Optional[int]) -> Tuple[np.ndarray, int]:
        if self._runtime is None:
            raise RuntimeError("model not loaded")
        res = self._synthesize(self._runtime, text, caption, seed)  # speed は無視
        audio = res.audio.detach().to("cpu").float().numpy()
        audio = np.squeeze(audio)              # mono → (N,)
        if audio.ndim == 2:                    # (ch, N) → (N, ch)
            audio = audio.T
        return np.ascontiguousarray(audio, dtype=np.float32), int(res.sample_rate)
```

> 注: `RuntimeKey`/`SamplingRequest` の正確な引数名・必須/任意は Step 1 実行時に `irodori_tts/inference_runtime.py` を開いて最終確認し、相違があれば本コードを合わせて修正する（Global Constraints の確定値が出発点）。

- [ ] **Step 3: CLI エントリを実装**

```python
# vd_server/__main__.py
import argparse
import uvicorn
from vd_server.app import create_app
from vd_server.backend import VoiceDesignBackend


def main():
    p = argparse.ArgumentParser(description="Irodori VoiceDesign HTTP server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--checkpoint", default="Aratako/Irodori-TTS-600M-v3-VoiceDesign")
    p.add_argument("--device", default="cuda")
    args = p.parse_args()

    backend = VoiceDesignBackend(checkpoint=args.checkpoint, device=args.device)
    app = create_app(backend)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 起動して `/health` が ready に遷移することを確認**

Run（Irodori-TTS venv 内）: `.venv/Scripts/python.exe -m vd_server --port 8770`
別シェルで: `curl -s http://127.0.0.1:8770/health`
Expected: 起動直後 503(loading)、モデルロード後 `{"status":"ok","ready":true,"sample_rate":48000,...}`

- [ ] **Step 5: Commit**

```bash
git add vd_server/backend.py vd_server/__main__.py
git commit -m "feat(vd-server): add VoiceDesignBackend and CLI entry"
```

---

### Task 6: 依存・起動スクリプト・README・受け入れ検証

**Files:**
- Create: `requirements-vd-server.txt`
- Create: `run_irodori_server.ps1`
- Create: `VD_SERVER_README.md`

**Interfaces:**
- Consumes: Task 1–5 の成果物すべて
- Produces: セットアップ〜起動〜curl検証までの手順一式（DocuListen 本体=サブPJ-2 が参照する HTTP 契約の確定）

- [ ] **Step 1: サーバ追加依存を記述**

```text
# requirements-vd-server.txt
# Irodori-TTS の venv（torch+CUDA12.8 済み）に追加で入れるサーバ依存
fastapi>=0.110
uvicorn>=0.29
soundfile>=0.12
numpy>=1.24
# dev/test
pytest>=8.0
httpx>=0.27
```

- [ ] **Step 2: 依存をインストールして全テストを通す**

```bash
.venv/Scripts/python.exe -m pip install -r requirements-vd-server.txt
.venv/Scripts/python.exe -m pytest tests/ -v
```
Expected: Task1–4 の全テスト（2+3+2+8 = 15 passed）。

- [ ] **Step 3: 起動スクリプトを作成**

```powershell
# run_irodori_server.ps1
param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8770,
  [string]$Checkpoint = "Aratako/Irodori-TTS-600M-v3-VoiceDesign",
  [string]$Device = "cuda"
)
# Irodori-TTS の venv を有効化した状態で実行すること
python -m vd_server --host $BindHost --port $Port --checkpoint $Checkpoint --device $Device
```

- [ ] **Step 4: README を作成**

````markdown
# Irodori VoiceDesign HTTP Server（DocuListen 用）

DocuListen から VOICEVOX と切替で使う Irodori VoiceDesign TTS を HTTP 公開する常駐サーバ。

## セットアップ
このプロジェクトは独立フォルダ `E:\project\IrodoriVDServer`（独自venv）。
1. venv 作成: `py -3.12 -m venv .venv`
2. torch(CUDA12.8): `.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu128`
3. Irodori 本体（コードのクローンから editable）: `.venv\Scripts\python -m pip install -e E:\project\Irodori-TTS-code`
4. サーバ依存: `.venv\Scripts\python -m pip install -r requirements-vd-server.txt`
5. モデルは初回起動時に HuggingFace から自動DL（`Aratako/Irodori-TTS-600M-v3-VoiceDesign`）。
   ローカルに `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors` がある場合は `--checkpoint` で指定可。

## 起動
```powershell
./run_irodori_server.ps1            # 127.0.0.1:8770
```

## API
- `GET /health` → ロード状況（503 loading → 200 ready）
- `POST /synthesize` `{ "text": str, "caption": str, "speed"?: float, "seed"?: int }` → `audio/wav`

## 動作確認（curl）
```bash
curl -s http://127.0.0.1:8770/health

curl -X POST http://127.0.0.1:8770/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"こんにちは。これはテストです。","caption":"落ち着いた女性の声で、近い距離感でやわらかく自然に読み上げてください。"}' \
  --output out.wav
```
`out.wav` が再生でき、別キャプション（例「深く傷つき声を震わせ悲痛なトーンで弱々しく話す」）で声色・感情が変われば成功。
````

- [ ] **Step 5: 受け入れ検証（spec の受け入れ基準を実機で実施）**

Run: README の手順でサーバ起動 → 上記 curl 2 種を実行。
Expected:
- `/health` が loading→ready に遷移
- `out.wav` が `soundfile` で読め、無音でない（SR=48000）
- 異なる caption で感情・声色が変化（耳で確認）
- 空 text→400、不正 JSON→400、起動直後→503
- 連続5リクエストがクラッシュせず順に WAV を返す（Lock 直列化）

- [ ] **Step 6: Commit**

```bash
git add requirements-vd-server.txt run_irodori_server.ps1 VD_SERVER_README.md
git commit -m "docs(vd-server): add deps, run script, README and acceptance steps"
```

---

### Task 7: 配布用ポータブルPythonバンドル（自動起動可能なフォルダ化）

**Files:**
- Create: `build_vd_bundle.ps1`
- Create: `BUNDLE_README.md`

**Interfaces:**
- Consumes: Task 1–6 の `vd_server` パッケージ一式
- Produces: 単体で `irodori-vd-runtime\python.exe -m vd_server ...` が起動できる**自己完結フォルダ** `irodori-vd-runtime\`（埋め込みPython3.11 + torch(CUDA12.8) + Irodori-TTS + vd_server）。本体アプリ（サブPJ-2）はこのフォルダの `python.exe` をサブプロセス起動する。

> GPU/ネット/容量を伴うops作業のため pytest 単体テストは課さず、スモーク起動で受け入れる。torch は **PyInstaller に通さない**（埋め込みPythonにそのまま入れる）方針。

- [ ] **Step 1: 埋め込みPythonを取得して土台を作る**

```powershell
# build_vd_bundle.ps1（抜粋）
$ErrorActionPreference = "Stop"
$Root = "irodori-vd-runtime"
$PyUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20250610/cpython-3.11.9+20250610-x86_64-pc-windows-msvc-install_only.tar.gz"
if (Test-Path $Root) { Remove-Item -Recurse -Force $Root }
New-Item -ItemType Directory -Force $Root | Out-Null
curl.exe -L $PyUrl -o py.tar.gz
tar -xzf py.tar.gz -C $Root --strip-components=1
Remove-Item py.tar.gz
```

- [ ] **Step 2: torch(CUDA12.8) と Irodori-TTS と vd_server 依存を埋め込みPythonへインストール**

```powershell
# build_vd_bundle.ps1（続き）
$Py = ".\$Root\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install torch --index-url https://download.pytorch.org/whl/cu128
# Irodori-TTS 本体（コードのクローンを editable で）:
& $Py -m pip install -e E:\project\Irodori-TTS-code
# vd_server 自身（この新フォルダ）を editable で:
& $Py -m pip install -e .
& $Py -m pip install -r requirements-vd-server.txt
```

> 注: `pip install -e .`（vd_server）と `-e E:\project\Irodori-TTS-code`（irodori_tts）の2つを埋め込みPythonへ入れる。
> 前者は Task 0 の `pyproject.toml` が要る。Irodori-TTS 本体の install 方法（`uv` 前提か pip editable 可か）は
> Task 5 Step 0/1 の確認時に確定する。editable が不可なら site-packages へコピー or `PYTHONPATH` 方式へ切替。
> ⚠️ バンドルは `Irodori-TTS-code` のパスに editable 依存するため、配布時は irodori_tts を
> **非editable**（`pip install <ビルド済みwheel>` か `git+https`）でバンドルに焼き込む方式へ切替検討（Task 7 で判断）。

- [ ] **Step 3: スモーク起動スクリプトを用意**

```powershell
# irodori-vd-runtime\start.ps1
& "$PSScriptRoot\python.exe" -m vd_server --host 127.0.0.1 --port 8770 --device cuda
```

- [ ] **Step 4: クリーン環境でスモーク受け入れ**

Run（開発venvを無効化した新しいシェルで）: `./irodori-vd-runtime/start.ps1`
別シェルで:
```bash
curl -s http://127.0.0.1:8770/health
curl -X POST http://127.0.0.1:8770/synthesize -H "Content-Type: application/json" \
  -d '{"text":"こんにちは。","caption":"落ち着いた女性の声で。"}' --output bundle_out.wav
```
Expected: 初回はモデル自動DL後、`/health` ready→ `bundle_out.wav` が再生可能。開発venvに一切依存しない。

- [ ] **Step 5: BUNDLE_README とコミット**

`BUNDLE_README.md` に「`build_vd_bundle.ps1` 実行 → `irodori-vd-runtime\` 生成 → start.ps1 起動 → 本体アプリ(サブPJ-2)はこのフォルダの `python.exe -m vd_server` を自動起動する」旨を記載。

```bash
git add build_vd_bundle.ps1 BUNDLE_README.md
git commit -m "build(vd-server): portable python bundle for auto-launch distribution"
```

---

### Task 8: handoff 更新（DocuListenLLM ルール）

**Files:**
- Modify: `E:\project\DocuListenLLM\handoff.md`（§8 IrodoriTTS サブプロジェクト）

**Interfaces:**
- Consumes: Task 1–7 の完了状況
- Produces: 本体 handoff.md にサーバ実装完了の事実を反映

- [ ] **Step 1: handoff.md §8 を更新**

§8 の「現状: 設計・環境準備は完了、サーバ実装は未着手」を「サーバ実装（サブPJ-1）完了」へ更新し、
`E:\project\IrodoriVDServer` リポジトリに `vd_server/` 一式・テスト・起動スクリプト・バンドルが
あること、受け入れ検証(curl)が通ったこと、次は **サブPJ-2（本体改造）** であることを日付(2026-06-26〜)付きで追記。

- [ ] **Step 2: Commit（本体はGit管理外のため記録のみ。Irodori側は不要）**

handoff.md は本体側（Git管理外）。保存のみで可。サブPJ-2 着手前のステータスとして残す。

---

## Self-Review

**Spec coverage:**
- HTTP契約 `/health`・`/synthesize`（入出力・ステータス規約）→ Task 3,4 ✓
- WAV/16-bit PCM・SR(48000)をヘッダに → Task 1,4 ✓
- caption-only・speed clamp(モデルには渡さない)・seed → Task 4,5 ✓
- GPU直列化（Lock）→ Task 4（test_synthesize_serialized_by_lock）✓
- モデル1回ロード・ready遷移・ウォームアップ → Task 5 ✓
- 別Python別プロセス・起動スクリプト/README → Task 6 ✓
- 単体受け入れ（curl）→ Task 6 ✓
- 配布用ポータブルPythonバンドル＋スモーク → Task 7 ✓
- モデル初回自動DL → Task 5(_load)/Task 7 Step 4 ✓
- 成果物消失の再発防止（独立フォルダ `IrodoriVDServer` + git init + 毎Taskコミット）→ Task 0 ✓（新規）
- handoff 更新ルール → Task 8 ✓（新規）

**Placeholder scan:** 実コード・実テスト・実コマンドを各ステップに記載。Task 5 の import は「Step 1 の確認結果に合わせて置換」と明示（モデルAPIが外部リポジトリ依存のため不可避な確認ポイント）。

**Type consistency:** `SynthBackend`(ready/sample_rate/model_name/infer)・`encode_wav_pcm16(audio,sr)->bytes`・`create_app(backend)->FastAPI`・`infer(text,caption,speed,seed)->(np.ndarray,int)` は全Taskで一貫。

---

## 次（本プラン完了後）
- サブPJ-2: DocuListen 本体の改造（エンジン切替・感情分類LLM・男女キャプション組立・再生連携）を別 spec→plan で。
