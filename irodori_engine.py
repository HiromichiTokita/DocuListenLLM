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


import os
import time as _time
import subprocess
import threading


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
        self._session = None
        self._lock = threading.Lock()

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
            if self._session is None:
                self._session = self._session_factory()
            r = self._session.get(f"{self.base_url}/health", timeout=2)
            return r.status_code == 200 and bool(r.json().get("ready"))
        except Exception:
            return False

    def ensure_running(self, on_status=None, ready_timeout: float = 180.0) -> bool:
        def _status(msg, kind="working"):
            if on_status:
                on_status(msg, kind)
        # ロックで直列化（再生を続けて起こしても二重起動しない）
        with self._lock:
            if self.is_healthy():
                _status("Irodori: 既存サーバに接続", "ok")
                return True
            # 自分が起動済みで生存中なら再 spawn しない（ready 待ちに入る）
            already_alive = (self._spawned and self._proc is not None
                             and self._proc.poll() is None)
            if not already_alive:
                if not os.path.isfile(self.python_path):
                    raise IrodoriLaunchError(
                        f"Irodori ランタイムが見つかりません: {self.python_path}（設定 irodori_runtime_path を確認）")
                cmd = [self.python_path, "-m", "vd_server",
                       "--port", str(self.port), "--device", self.device]
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
