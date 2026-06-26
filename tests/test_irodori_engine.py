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
