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
