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
    assert spawned == []
    assert m._spawned is False


def test_missing_runtime_path_raises():
    m = IrodoriServerManager("E:/no/such/dir", port=8770,
                             session_factory=lambda: _HealthSession([_HealthResp(503, False)]))
    with pytest.raises(IrodoriLaunchError):
        m.ensure_running()


def test_spawns_then_polls_until_ready(tmp_path):
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
