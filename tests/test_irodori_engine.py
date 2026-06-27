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


def test_no_double_spawn_when_proc_alive(tmp_path):
    (tmp_path / "python.exe").write_text("")
    spawns = []

    class _AliveProc:
        def terminate(self):
            pass
        def poll(self):
            return None  # 生存中

    m = IrodoriServerManager(
        str(tmp_path), port=8770,
        session_factory=lambda: _HealthSession([_HealthResp(503, False)]),
        spawn=lambda *a, **k: (spawns.append(1), _AliveProc())[1],
        sleep=lambda s: None)
    assert m.ensure_running(ready_timeout=0.0) is False
    assert len(spawns) == 1                 # 1回目で spawn
    assert m.ensure_running(ready_timeout=0.0) is False
    assert len(spawns) == 1                 # 2回目は生存中なので再 spawn しない


def test_caption_seed_stable_and_distinct():
    from irodori_engine import caption_seed
    a = caption_seed("落ち着いた女性の声で読み上げてください。")
    assert isinstance(a, int) and a >= 0
    assert caption_seed("落ち着いた女性の声で読み上げてください。") == a  # 同一→同一
    assert caption_seed("低い男性の声で読み上げてください。") != a        # 異なる→異なる
    assert caption_seed("") == caption_seed("")                          # 空でも安定


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
    assert voice_seed_for("ナレーション", seeds) == 7


def test_new_seed_range():
    from irodori_engine import new_seed
    for _ in range(20):
        s = new_seed()
        assert 0 <= s < 2**31


def test_engine_for_global_overrides():
    from irodori_engine import engine_for
    assert engine_for("主人公 男", "voicevox", {"主人公 男": "irodori"}) == "voicevox"
    assert engine_for("主人公 男", "irodori", {}) == "irodori"


def test_engine_for_mixed_uses_category_map():
    from irodori_engine import engine_for
    ce = {"主人公 男": "irodori", "__narrator__": "voicevox"}
    assert engine_for("主人公 男", "mixed", ce) == "irodori"
    assert engine_for("ナレーション", "mixed", ce) == "voicevox"
    assert engine_for("中年 女", "mixed", ce) == "voicevox"
