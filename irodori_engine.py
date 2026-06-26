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
