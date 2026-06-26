# Irodoriエンジン統合（サブPJ-2a）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 方針: **動く一本通し優先（ガチガチにしない・試しながら調整）**。純粋ロジックは新モジュール
> `irodori_engine.py` に分離して単体テスト、UI/producer配線は `main.py` で手動確認。

**Goal:** DocuListen 本体に「VOICEVOX ⇄ Irodori」切替を追加し、Irodori選択時はバンドルを遅延起動して
カテゴリ毎キャプションで複数キャラ読み上げできるようにする。

**Architecture:** 合成バックエンド抽象化（案B）。新モジュール `irodori_engine.py` に純粋ロジック
（キャプション既定値・解決・Irodori合成・サーバ管理）を置き、`main.py` が設定/UI/`_producer` から呼ぶ。
既存の2段階LLM配役（カテゴリ推定）は無改造で再利用し、各チャンクに `category` を保存する点だけ足す。

**Tech Stack:** Python 3.14（`py`）, customtkinter, requests（既存）, pytest（テスト用・要追加）。
サブPJ-1の `E:\project\IrodoriVDServer\irodori-vd-runtime`（バンドル）と `http://127.0.0.1:8770`。

## Global Constraints
- 本体実行/テストは **`py`（=Python 3.14）**。PATHの`python`は3.12で別物。
- **DocuListenLLM は現状 Git 管理外** → 成果物保全のため Task 0 で `git init`＋`.gitignore`（engine/・dist/等を除外）。以降は各Task末尾でコミット。
- 純粋ロジックは `irodori_engine.py`（customtkinter非依存）。テストは `tests/test_irodori_engine.py`、`py -m pytest` で実行。
- 既存VOICEVOX動作・settings後方互換を壊さない（新キーは既定値で無効化、`tts_engine` 既定 `"voicevox"`）。
- Irodori HTTP契約: `GET /health`→ready、`POST /synthesize {text, caption, speed?, seed?}`→`audio/wav`（16bit PCM 48kHz）。異常はJSON `{"error":...}`。
- Irodori server は speed 無視 → 再生速度は consumer 側 `_time_stretch` で適用。
- バンドル既定パス `E:\project\IrodoriVDServer\irodori-vd-runtime`、既定ポート `8770`、既定 checkpoint `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors`。

## ファイル構成
- Create: `irodori_engine.py` — `DEFAULT_CAPTIONS`, `DEFAULT_NARRATOR_CAPTION`, `resolve_caption()`, `synthesize_irodori()`, `IrodoriServerManager`
- Create: `tests/test_irodori_engine.py`
- Modify: `main.py` — settings keys / Stage2 で category 保存 / エンジン切替UI＋キャプション欄 / `_producer` Irodori分岐 / ライフサイクル / consumer の `_time_stretch`
- Modify: `.gitignore`（Task 0）

---

### Task 0: Git ベースライン（成果物保全）

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: .gitignore を作成**

```gitignore
engine/
dist/
build/
__pycache__/
*.zip
out.txt
err.txt
settings.json
.venv/
```

- [ ] **Step 2: git init＋初回コミット**

```bash
cd /e/project/DocuListenLLM
git init
git config --global --add safe.directory E:/project/DocuListenLLM
git add .gitignore main.py build.py DocuListen.spec requirements.txt handoff.md CLAUDE.md docs archive icon.ico
git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "chore: git baseline before Irodori engine integration"
```
Expected: 初回コミット作成。`engine/`・`dist/` は無視される。

---

### Task 1: キャプション既定値と解決（純粋関数）

**Files:**
- Create: `irodori_engine.py`
- Test: `tests/test_irodori_engine.py`

**Interfaces:**
- Produces:
  - `irodori_engine.DEFAULT_CAPTIONS: dict[str, str]`（14カテゴリ → 既定キャプション）
  - `irodori_engine.DEFAULT_NARRATOR_CAPTION: str`
  - `irodori_engine.resolve_caption(category: str, caption_map: dict[str, str], narrator_caption: str) -> str`
    （`caption_map` に無い／ナレーション系カテゴリは `narrator_caption` を返す。`caption_map[category]` が空文字なら既定にフォールバック）

- [ ] **Step 0: pytest を 3.14 環境へ導入（未導入なら）**

```bash
cd /e/project/DocuListenLLM && py -m pip install pytest
```

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_irodori_engine.py
from irodori_engine import (
    DEFAULT_CAPTIONS, DEFAULT_NARRATOR_CAPTION, resolve_caption,
)


def test_defaults_cover_14_categories():
    expected = {
        "主人公 女", "主人公 男", "子供 男", "子供 女", "若者 男", "若者 女",
        "中年 男", "中年 女", "老人 男", "老人 女", "ロボット",
        "人外仲間(かわいい)", "人外仲間(かっこいい)", "怪物",
    }
    assert expected.issubset(set(DEFAULT_CAPTIONS))
    assert all(isinstance(v, str) and v for v in DEFAULT_CAPTIONS.values())
    assert isinstance(DEFAULT_NARRATOR_CAPTION, str) and DEFAULT_NARRATOR_CAPTION


def test_resolve_known_category_uses_map():
    cap = resolve_caption("主人公 男", {"主人公 男": "若い男性の声"}, "ナレーター声")
    assert cap == "若い男性の声"


def test_resolve_narration_uses_narrator():
    assert resolve_caption("ナレーション", {"主人公 男": "x"}, "ナレーター声") == "ナレーター声"


def test_resolve_unknown_category_uses_narrator():
    assert resolve_caption("宇宙人", {}, "ナレーター声") == "ナレーター声"


def test_resolve_empty_map_value_falls_back_to_default():
    cap = resolve_caption("主人公 男", {"主人公 男": "   "}, "ナレーター声")
    assert cap == DEFAULT_CAPTIONS["主人公 男"]
```

- [ ] **Step 2: 失敗を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'irodori_engine'`）

- [ ] **Step 3: 最小実装**

```python
# irodori_engine.py
"""DocuListen の Irodori エンジン統合ロジック（customtkinter 非依存・テスト可能）。"""

DEFAULT_NARRATOR_CAPTION = "落ち着いた中性的なナレーターの声で、自然に淡々と読み上げてください。"

DEFAULT_CAPTIONS = {
    "主人公 女": "若い女性の明るく親しみやすい声で、自然に読み上げてください。",
    "主人公 男": "若い男性の落ち着いた自然な声で、まっすぐに読み上げてください。",
    "子供 男": "幼い男の子の元気で高い声で、無邪気に読み上げてください。",
    "子供 女": "幼い女の子のかわいらしく高い声で、無邪気に読み上げてください。",
    "若者 男": "青年男性の少し軽やかでハキハキした声で読み上げてください。",
    "若者 女": "若い女性の快活でやや高めの声で読み上げてください。",
    "中年 男": "中年男性の落ち着いた低めの声で、ゆったりと読み上げてください。",
    "中年 女": "中年女性の柔らかく落ち着いた声で読み上げてください。",
    "老人 男": "年配の男性の穏やかでゆっくりとした低い声で読み上げてください。",
    "老人 女": "年配の女性の穏やかでゆっくりとした声で読み上げてください。",
    "ロボット": "感情を抑えた無機質で平坦な機械的の声で読み上げてください。",
    "人外仲間(かわいい)": "小さくてかわいらしい人外キャラの、高くやわらかい声で読み上げてください。",
    "人外仲間(かっこいい)": "凛々しくかっこいい人外キャラの、芯のある低めの声で読み上げてください。",
    "怪物": "おどろおどろしく低く唸るような怪物の声で読み上げてください。",
}

# 地の文として narrator にフォールバックさせるカテゴリ
_NARRATION_CATEGORIES = {"ナレーション", "ナレーター", "地の文"}


def resolve_caption(category: str, caption_map: dict, narrator_caption: str) -> str:
    """チャンクの category から Irodori 用キャプションを決める。

    - ナレーション系／未知カテゴリ → narrator_caption
    - caption_map に有効値があればそれ、空なら DEFAULT_CAPTIONS、無ければ narrator_caption
    """
    cat = (category or "").strip()
    if cat in _NARRATION_CATEGORIES or cat not in DEFAULT_CAPTIONS:
        return narrator_caption
    user_val = (caption_map.get(cat) or "").strip()
    if user_val:
        return user_val
    return DEFAULT_CAPTIONS.get(cat, narrator_caption)
```

- [ ] **Step 4: 成功を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: コミット**

```bash
cd /e/project/DocuListenLLM && git add irodori_engine.py tests/test_irodori_engine.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): caption defaults + resolve_caption"
```

---

### Task 2: Irodori 合成呼び出し（HTTPモックでテスト）

**Files:**
- Modify: `irodori_engine.py`
- Test: `tests/test_irodori_engine.py`

**Interfaces:**
- Consumes: なし（`requests.Session` 風オブジェクトを引数注入）
- Produces:
  - `irodori_engine.synthesize_irodori(session, base_url: str, text: str, caption: str, seed=None, timeout: int = 180) -> bytes`
    成功時は WAV バイト列。HTTP非200は `IrodoriSynthError`（`message`属性つき）を送出。
  - `irodori_engine.IrodoriSynthError(Exception)`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_irodori_engine.py に追記
import pytest
from irodori_engine import synthesize_irodori, IrodoriSynthError


class _Resp:
    def __init__(self, status, content=b"", js=None):
        self.status_code = status
        self.content = content
        self._js = js or {}
    def json(self):
        return self._js


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []
    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self._resp


def test_synthesize_irodori_success_returns_bytes():
    sess = _Session(_Resp(200, content=b"RIFFwavdata"))
    out = synthesize_irodori(sess, "http://127.0.0.1:8770", "本文", "落ち着いた声で", seed=7)
    assert out == b"RIFFwavdata"
    call = sess.calls[0]
    assert call["url"] == "http://127.0.0.1:8770/synthesize"
    assert call["json"] == {"text": "本文", "caption": "落ち着いた声で", "seed": 7}


def test_synthesize_irodori_omits_seed_when_none():
    sess = _Session(_Resp(200, content=b"x"))
    synthesize_irodori(sess, "http://127.0.0.1:8770", "a", "b")
    assert "seed" not in sess.calls[0]["json"]


def test_synthesize_irodori_error_status_raises():
    sess = _Session(_Resp(503, js={"error": "loading"}))
    with pytest.raises(IrodoriSynthError) as ei:
        synthesize_irodori(sess, "http://127.0.0.1:8770", "a", "b")
    assert "loading" in str(ei.value)
```

- [ ] **Step 2: 失敗を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: FAIL（`ImportError: cannot import name 'synthesize_irodori'`）

- [ ] **Step 3: 実装を追記**

```python
# irodori_engine.py に追記
class IrodoriSynthError(Exception):
    pass


def synthesize_irodori(session, base_url: str, text: str, caption: str,
                       seed=None, timeout: int = 180) -> bytes:
    """Irodori サーバの /synthesize を叩き WAV バイト列を返す。

    session は requests.Session 互換（.post(url, json=, timeout=) -> resp）。
    """
    payload = {"text": text, "caption": caption}
    if seed is not None:
        payload["seed"] = int(seed)
    resp = session.post(f"{base_url}/synthesize", json=payload, timeout=timeout)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error", f"HTTP {resp.status_code}")
        except Exception:
            msg = f"HTTP {resp.status_code}"
        raise IrodoriSynthError(str(msg))
    return resp.content
```

- [ ] **Step 4: 成功を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: コミット**

```bash
cd /e/project/DocuListenLLM && git add irodori_engine.py tests/test_irodori_engine.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): synthesize_irodori HTTP call + error mapping"
```

---

### Task 3: IrodoriServerManager（遅延起動・health・再利用・停止）

**Files:**
- Modify: `irodori_engine.py`
- Test: `tests/test_irodori_engine.py`

**Interfaces:**
- Produces: `irodori_engine.IrodoriServerManager(runtime_path: str, port: int = 8770, checkpoint: str = "", session_factory=None, spawn=None, sleep=None)`
  - `.base_url -> str`（`http://127.0.0.1:<port>`）
  - `.is_healthy() -> bool`（`GET /health` が 200 かつ `ready` True）
  - `.python_path -> str`（`<runtime_path>/python.exe`）
  - `.ensure_running(on_status=None, ready_timeout=180.0) -> bool`：既に healthy なら何もせず True（外部起動を再利用）。
    さもなくば `python.exe -m vd_server --port --checkpoint --device cuda` を spawn し、ready までポーリング。
    自分が起動した場合のみ `_spawned=True`。runtime_path 不在なら `IrodoriLaunchError`。
  - `.stop()`：自分が spawn したプロセスのみ terminate。
  - `irodori_engine.IrodoriLaunchError(Exception)`
  - 注: `session_factory`/`spawn`/`sleep` はテスト用に注入可能（既定は requests.Session / subprocess.Popen / time.sleep）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_irodori_engine.py に追記
from irodori_engine import IrodoriServerManager, IrodoriLaunchError
import os


class _HealthResp:
    def __init__(self, status, ready):
        self.status_code = status
        self._ready = ready
    def json(self):
        return {"status": "ok" if self._ready else "loading", "ready": self._ready}


class _HealthSession:
    """get() が seq の応答を順に返す。尽きたら最後を繰り返す。"""
    def __init__(self, seq):
        self._seq = list(seq)
    def get(self, url, timeout=None):
        return self._seq[0] if len(self._seq) == 1 else self._seq.pop(0)


def test_base_url_and_python_path(tmp_path):
    m = IrodoriServerManager(str(tmp_path), port=8770)
    assert m.base_url == "http://127.0.0.1:8770"
    assert m.python_path == os.path.join(str(tmp_path), "python.exe")


def test_reuse_when_already_healthy(tmp_path):
    spawned = []
    m = IrodoriServerManager(
        str(tmp_path), port=8770,
        session_factory=lambda: _HealthSession([_HealthResp(200, True)]),
        spawn=lambda *a, **k: spawned.append(a) or object(),
    )
    assert m.ensure_running() is True
    assert spawned == []          # 外部起動を再利用、spawn しない
    assert m._spawned is False


def test_missing_runtime_path_raises():
    m = IrodoriServerManager("E:/no/such/dir", port=8770,
                             session_factory=lambda: _HealthSession([_HealthResp(503, False)]))
    with pytest.raises(IrodoriLaunchError):
        m.ensure_running()


def test_spawns_then_polls_until_ready(tmp_path):
    # python.exe を存在させる
    (tmp_path / "python.exe").write_text("")
    proc = type("P", (), {"terminated": False,
                          "terminate": lambda self: setattr(self, "terminated", True),
                          "poll": lambda self: None})()
    seq = [_HealthResp(503, False), _HealthResp(503, False), _HealthResp(200, True)]
    m = IrodoriServerManager(
        str(tmp_path), port=8770,
        session_factory=lambda: _HealthSession(seq),
        spawn=lambda *a, **k: proc,
        sleep=lambda s: None,
    )
    assert m.ensure_running(ready_timeout=10) is True
    assert m._spawned is True
    m.stop()
    assert proc.terminated is True
```

- [ ] **Step 2: 失敗を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: FAIL（`ImportError: cannot import name 'IrodoriServerManager'`）

- [ ] **Step 3: 実装を追記**

```python
# irodori_engine.py に追記
import os
import time as _time
import subprocess


class IrodoriLaunchError(Exception):
    pass


class IrodoriServerManager:
    def __init__(self, runtime_path: str, port: int = 8770, checkpoint: str = "",
                 device: str = "cuda", session_factory=None, spawn=None, sleep=None):
        self.runtime_path = runtime_path
        self.port = int(port)
        self.checkpoint = checkpoint
        self.device = device
        self._session_factory = session_factory or self._default_session_factory
        self._spawn = spawn or self._default_spawn
        self._sleep = sleep or _time.sleep
        self._proc = None
        self._spawned = False

    @staticmethod
    def _default_session_factory():
        import requests
        return requests.Session()

    def _default_spawn(self, cmd):
        return subprocess.Popen(cmd)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def python_path(self) -> str:
        return os.path.join(self.runtime_path, "python.exe")

    def is_healthy(self) -> bool:
        try:
            sess = self._session_factory()
            r = sess.get(f"{self.base_url}/health", timeout=2)
            return r.status_code == 200 and bool(r.json().get("ready"))
        except Exception:
            return False

    def ensure_running(self, on_status=None, ready_timeout: float = 180.0) -> bool:
        def _status(msg, kind="working"):
            if on_status:
                on_status(msg, kind)
        if self.is_healthy():
            _status("Irodori: 既存サーバに接続", "ok")
            return True
        if not os.path.isfile(self.python_path):
            raise IrodoriLaunchError(
                f"Irodori ランタイムが見つかりません: {self.python_path}（設定 irodori_runtime_path を確認）")
        cmd = [self.python_path, "-m", "vd_server", "--port", str(self.port), "--device", self.device]
        if self.checkpoint:
            cmd += ["--checkpoint", self.checkpoint]
        _status("Irodori: サーバ起動中…", "working")
        self._proc = self._spawn(cmd)
        self._spawned = True
        deadline = _time.monotonic() + ready_timeout
        while _time.monotonic() < deadline:
            if self.is_healthy():
                _status("Irodori: ready", "ok")
                return True
            self._sleep(2.0)
        _status("Irodori: 起動がタイムアウトしました", "error")
        return False

    def stop(self):
        if self._spawned and self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
        self._spawned = False
```

> 注: `_time.monotonic()` はテストで sleep をモックしても進まないため、テスト
> `test_spawns_then_polls_until_ready` は health 応答が3回目で ready になり deadline 前に True を返す。
> （`ready_timeout=10` と十分大きく、monotonic は実時間でほぼ即時に3回ループするため成立。）

- [ ] **Step 4: 成功を確認**

Run: `cd /e/project/DocuListenLLM && py -m pytest tests/test_irodori_engine.py -v`
Expected: PASS（12 passed）

- [ ] **Step 5: コミット**

```bash
cd /e/project/DocuListenLLM && git add irodori_engine.py tests/test_irodori_engine.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): IrodoriServerManager lazy launch + health poll + reuse"
```

---

### Task 4: main.py — 設定キー＋Stage2でcategory保存（後方互換）

**Files:**
- Modify: `main.py`（`_load_settings`/`_save_settings` 付近、Stage2 の `self._script[i]` 付近 L2345）

**Interfaces:**
- Consumes: `irodori_engine.DEFAULT_CAPTIONS`, `DEFAULT_NARRATOR_CAPTION`
- Produces: `self._settings` に `tts_engine`/`irodori_runtime_path`/`irodori_port`/`irodori_checkpoint`/`captions`(dict)/`narrator_caption`、
  および `self._script[i]["category"]` が保存される。

- [ ] **Step 1: import と設定読込既定を追加**

`main.py` 冒頭の import 群に追加:
```python
import irodori_engine
```
`_load_settings`/`__init__` 周辺で、保存値が無ければ既定を入れる（既存の `self._settings = self._load_settings()` の直後に）:
```python
        s = self._settings
        s.setdefault("tts_engine", "voicevox")
        s.setdefault("irodori_runtime_path", r"E:\project\IrodoriVDServer\irodori-vd-runtime")
        s.setdefault("irodori_port", 8770)
        s.setdefault("irodori_checkpoint", r"E:\project\DocuListenLLM\IrodoriTTS\model.safetensors")
        s.setdefault("narrator_caption", irodori_engine.DEFAULT_NARRATOR_CAPTION)
        caps = s.setdefault("captions", {})
        for _cat, _cap in irodori_engine.DEFAULT_CAPTIONS.items():
            caps.setdefault(_cat, _cap)
```

- [ ] **Step 2: `_save_settings` に新キーを書き出す**

`_save_settings` の `settings = {...}` 構築に以下を追加（既存キーは残す）:
```python
            "tts_engine":           self.engine_var.get() if hasattr(self, "engine_var") else self._settings.get("tts_engine", "voicevox"),
            "irodori_runtime_path": self._settings.get("irodori_runtime_path", ""),
            "irodori_port":         self._settings.get("irodori_port", 8770),
            "irodori_checkpoint":   self._settings.get("irodori_checkpoint", ""),
            "narrator_caption":     self.narrator_caption_var.get() if hasattr(self, "narrator_caption_var") else self._settings.get("narrator_caption", ""),
            "captions":             {cat: var.get() for cat, var in self.caption_vars.items()} if hasattr(self, "caption_vars") else self._settings.get("captions", {}),
```

- [ ] **Step 3: Stage2 で category を保存**

`main.py` L2345 付近、`self._script[i]["style_id"] = style_id` の直後に追加:
```python
                    self._script[i]["category"] = category
```

- [ ] **Step 4: 起動して設定の往復を手動確認**

Run: `cd /e/project/DocuListenLLM && py main.py`
手順: 起動 → 終了 → `settings.json` に `tts_engine`/`captions`/`narrator_caption` 等が出力されていること、
既存項目（archetypes 等）が壊れていないことを目視。Stage2配役を一度走らせ、`self._script` の各 entry に
`category` が入る（DEBUGログ or スクリプトエクスポートで確認）。

- [ ] **Step 5: コミット**

```bash
cd /e/project/DocuListenLLM && git add main.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): settings keys + store category per chunk"
```

---

### Task 5: main.py — エンジン切替UI＋キャプション欄

**Files:**
- Modify: `main.py`（`_build_top_bar` L819 付近、`_build_llm_archetypes_tab` L976 付近）

**Interfaces:**
- Consumes: `self._settings`（Task 4）
- Produces: `self.engine_var`(StringVar "voicevox"/"irodori")、`self.caption_vars: dict[str, StringVar]`、
  `self.narrator_caption_var`(StringVar)、`self.irodori_status_label`、`self._on_engine_changed()`。

- [ ] **Step 1: トップバーにエンジン切替＋状態表示**

`_build_top_bar` 内に追加（既存ウィジェット配置に合わせて grid/pack）:
```python
        self.engine_var = ctk.StringVar(value=self._settings.get("tts_engine", "voicevox"))
        engine_menu = ctk.CTkOptionMenu(
            <親フレーム>, values=["voicevox", "irodori"], variable=self.engine_var,
            command=lambda _v: self._on_engine_changed())
        # ラベル「エンジン:」＋ engine_menu を配置
        self.irodori_status_label = ctk.CTkLabel(<親フレーム>, text="")
        # irodori_status_label を配置
```
`_on_engine_changed` を追加（本Taskでは状態表示の更新のみ。実際の起動は Task 6）:
```python
    def _on_engine_changed(self):
        eng = self.engine_var.get()
        self._settings["tts_engine"] = eng
        if eng == "irodori":
            self.irodori_status_label.configure(text="Irodori: 未起動")
        else:
            self.irodori_status_label.configure(text="")
```

- [ ] **Step 2: AIディレクタータブにキャプション欄を追加**

`_build_llm_archetypes_tab` のアーキタイプ行ループ（L991〜）に、各 `archetype` 行へキャプション入力を追加:
```python
            cap_init = self._settings.get("captions", {}).get(
                archetype, irodori_engine.DEFAULT_CAPTIONS.get(archetype, ""))
            cap_var = ctk.StringVar(value=cap_init)
            cap_entry = ctk.CTkEntry(scroll, textvariable=cap_var, width=360,
                                     placeholder_text="Irodori キャプション")
            cap_entry.grid(row=row_idx, column=3, padx=6, pady=2, sticky="we")
            self.caption_vars[archetype] = cap_var
```
ループ前に `self.caption_vars = {}` を初期化。ナレーター用も1つ（タブ上部に）:
```python
        self.narrator_caption_var = ctk.StringVar(
            value=self._settings.get("narrator_caption", irodori_engine.DEFAULT_NARRATOR_CAPTION))
        ctk.CTkEntry(parent, textvariable=self.narrator_caption_var, width=360,
                     placeholder_text="ナレーター キャプション").pack/grid(...)
```

- [ ] **Step 3: 手動確認**

Run: `cd /e/project/DocuListenLLM && py main.py`
手順: トップバーにエンジン切替が出る／irodori選択で状態ラベルが変わる／AIディレクタータブに各役のキャプション欄が
既定文付きで並ぶ／編集して終了→再起動で保持。VOICEVOX選択時は従来UIが普通に使える。

- [ ] **Step 4: コミット**

```bash
cd /e/project/DocuListenLLM && git add main.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): engine toggle UI + caption entry fields"
```

---

### Task 6: main.py — _producer Irodori分岐＋ライフサイクル＋再生速度

**Files:**
- Modify: `main.py`（`_producer` L2490 付近、`_consumer` L2643 付近、`_start_playback`/終了処理）

**Interfaces:**
- Consumes: `irodori_engine.synthesize_irodori`, `IrodoriServerManager`, `resolve_caption`, `self.caption_vars`, `self.narrator_caption_var`, `self.engine_var`
- Produces: Irodori 経由で WAV を temp スロットに書き再生する経路。`self._irodori = IrodoriServerManager(...)`。

- [ ] **Step 1: IrodoriServerManager を生成（__init__）**

`__init__` で:
```python
        self._irodori = irodori_engine.IrodoriServerManager(
            runtime_path=self._settings.get("irodori_runtime_path", ""),
            port=int(self._settings.get("irodori_port", 8770)),
            checkpoint=self._settings.get("irodori_checkpoint", ""))
```

- [ ] **Step 2: 再生開始時に Irodori を遅延起動**

`_start_playback`（または `_llm_and_play_thread` 開始時）で、engine=irodori のとき ready 確保:
```python
        if self.engine_var.get() == "irodori":
            try:
                ok = self._irodori.ensure_running(
                    on_status=lambda m, k: self.after(0, lambda: self._set_status(m, k)))
            except irodori_engine.IrodoriLaunchError as exc:
                self.after(0, lambda e=exc: self._set_status(str(e), "error"))
                return
            if not ok:
                self.after(0, lambda: self._set_status("Irodori 起動失敗", "error"))
                return
```

- [ ] **Step 3: `_producer` に Irodori 分岐**

`_producer` の合成部（L2560〜2609 の VOICEVOX audio_query/synthesis ブロック）を、engine で分岐:
```python
                    if self.engine_var.get() == "irodori":
                        # category を取得（スクリプトに無ければナレーション扱い）
                        if self._script and chunk_idx < len(self._script):
                            cat = self._script[chunk_idx].get("category", "ナレーション")
                        else:
                            cat = "ナレーション"
                        caption = irodori_engine.resolve_caption(
                            cat,
                            {c: v.get() for c, v in self.caption_vars.items()},
                            self.narrator_caption_var.get())
                        self.after(0, lambda i=index, t=total: self._set_status(
                            f"Irodori 合成中... ({i}/{t})", "working"))
                        wav_bytes = irodori_engine.synthesize_irodori(
                            self._http_session, self._irodori.base_url, chunk, caption)
                    else:
                        # 既存 VOICEVOX 経路（audio_query → synthesis → wav_bytes）
                        ...（既存コードのまま）...
```
※ Irodori 経路は `irodori_engine.IrodoriSynthError` を投げうる → 既存の `except Exception` が拾い `SKIP` する（後方互換）。

- [ ] **Step 4: consumer で Irodori 時に再生速度を適用**

`_consumer` で、VOICEVOX は audio_query で speedScale 済みだが Irodori は等速。engine=irodori のとき、
スロット WAV 読み込み後に既存 `_time_stretch`（pedalboard）で `speed` を適用してから再生する分岐を追加
（既存の再生・無音パディング・RMS正規化の前段に挿入。実装箇所は `_consumer` 内の WAV 読み込み直後）。

- [ ] **Step 5: アプリ終了時に Irodori を停止**

ウィンドウクローズ処理（`_on_close`/`protocol("WM_DELETE_WINDOW", ...)` 相当。無ければ追加）に:
```python
        try:
            self._irodori.stop()
        except Exception:
            pass
```

- [ ] **Step 6: エンドツーエンド手動確認（受け入れ基準）**

Run: `cd /e/project/DocuListenLLM && py main.py`（VOICEVOX engine と Ollama は起動済み前提）
手順:
1. エンジン=irodori に切替 → テキスト投入 → 再生 → バンドルが遅延起動し ready 後に読み上げ開始。
2. 複数キャラのテキストで、カテゴリ毎にキャプションが反映され声が変わる。
3. 再生速度スライダーが Irodori でも効く（`_time_stretch`）。
4. エンジン=voicevox に戻すと従来通り再生（Irodori は起動しない）。
5. キャプション欄を編集 → 次の再生に反映。
6. アプリ終了で spawn した Irodori サーバが落ちる。

- [ ] **Step 7: コミット**

```bash
cd /e/project/DocuListenLLM && git add main.py && git -c user.name="DocuListen" -c user.email="noreply@local" commit -m "feat(irodori): producer branch + lazy launch + speed via time_stretch + shutdown"
```

---

## Self-Review
- spec カバレッジ: エンジン抽象化(Task6)・遅延起動(Task3,6)・カテゴリ→キャプション(Task1,6)・UI(Task5)・設定(Task4)・
  速度=_time_stretch(Task6-4)・エラー/SKIP(Task6-3)・終了停止(Task6-5)・後方互換(Task4既定/分岐) → 各Taskに対応 ✓
- category 保存の前提（Stage2がstyle_idのみ保存だった問題）を Task4-3 で解消 ✓
- 純粋ロジック（Task1-3）はGUI非依存で単体テスト、GUI(Task4-6)は手動確認（lean方針） ✓
- 型整合: `resolve_caption(category, caption_map, narrator_caption)->str`、`synthesize_irodori(session, base_url, text, caption, seed, timeout)->bytes`、`IrodoriServerManager(...).ensure_running()->bool` は全Taskで一貫 ✓

## 次（本プラン完了後）
- サブPJ-2b: 感情/スタイル分類LLM による動的キャプション（喜怒哀楽）を別 spec→plan で。
