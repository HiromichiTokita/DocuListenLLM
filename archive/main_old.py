"""
VOICEVOX テキスト読み上げアプリケーション

動作要件:
  - engine/run.exe が隣接フォルダに存在すること (スタンドアロン配布時)
  - または VOICEVOX エンジンが http://127.0.0.1:50021 で別途起動していること
  - pip install customtkinter requests sounddevice soundfile psutil pypdf python-docx EbookLib beautifulsoup4
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from tkinter import filedialog
from typing import Optional
import customtkinter as ctk
import numpy as np
import pedalboard
import psutil
import pypdf
import requests
import sounddevice as sd
import soundfile as sf

try:
    from docx import Document as DocxDocument
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False


# ─────────────────────────────────────────
# 定数
# ─────────────────────────────────────────
VOICEVOX_URL = "http://127.0.0.1:50021"

ENGINE_STARTUP_TIMEOUT = 60
TEMP_SLOT_COUNT        = 3
SILENCE_PADDING_SEC    = 0.4
PRE_PADDING_SEC        = 0.15

DEFAULT_SPEAKER_DATA: dict[str, dict[str, int]] = {
    "四国めたん": {"ノーマル": 2},
    "ずんだもん":  {"ノーマル": 3},
}
DEFAULT_NARRATOR_CHAR = "四国めたん"
DEFAULT_DIALOGUE_CHAR = "ずんだもん"

SPEED_MIN     = 0.5
SPEED_MAX     = 3.0
SPEED_DEFAULT = 1.0

STATUS_COLORS = {
    "idle":    ("gray50",     "gray60"),
    "working": ("blue3",      "dodger blue"),
    "ok":      ("green4",     "green3"),
    "error":   ("red3",       "red2"),
    "stopped": ("orange3",    "orange2"),
    "paused":  ("goldenrod3", "goldenrod1"),
}

COLOR_PAUSE_ACTIVE = ("#3B8ED0", "#1F6AA5")
COLOR_STOP_ACTIVE  = ("#C0392B", "#922B21")
COLOR_DISABLED     = ("gray75",  "gray35")

HIGHLIGHT_TAG = "chunk_active"
HIGHLIGHT_BG  = "#1F538A"
HIGHLIGHT_FG  = "#FFFFFF"

# CPU優先度クラスのマッピング (Windows)
_PRIORITY_MAP: dict[str, int] = {
    "Normal":       psutil.NORMAL_PRIORITY_CLASS,
    "Below Normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
    "Low":          psutil.IDLE_PRIORITY_CLASS,
}


# ─────────────────────────────────────────
# パス解決
# ─────────────────────────────────────────
def _resolve_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _resolve_engine_path() -> str:
    return os.path.join(_resolve_app_dir(), "engine", "run.exe")

_APP_DIR = _resolve_app_dir()

TEMP_PATHS: list[str] = [
    os.path.join(_APP_DIR, "temp_1.wav"),
    os.path.join(_APP_DIR, "temp_2.wav"),
    os.path.join(_APP_DIR, "temp_3.wav"),
]

SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")


# ─────────────────────────────────────────
# テキスト・音声ユーティリティ
# ─────────────────────────────────────────
def _split_text(text: str) -> list[str]:
    """
    テキストをチャンクに分割する:
      - 「」で囲まれたセリフを独立したチャンクとして抽出する
      - 地の文は句点(。)と改行(\\n)でさらに分割する
    """
    parts = re.split(r"(「[^」]*」)", text)
    chunks: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        if part.startswith("「"):
            chunks.append(part.strip())
        else:
            sub = re.split(r"(?<=。)|\n", part)
            chunks.extend(c.strip() for c in sub if c.strip())
    return chunks

def _speaker_for_chunk(chunk: str, narrator_id: int, dialogue_id: int) -> int:
    return dialogue_id if chunk.startswith("「") else narrator_id

def _time_stretch(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """
    pedalboard でピッチを変えずに再生速度を調整する。speed=1.0 はスキップ。
    stretch_factor = speed: output_length = input_length / stretch_factor
    """
    if abs(speed - 1.0) < 0.01:
        return audio
    was_1d = audio.ndim == 1
    buf = audio.reshape(1, -1).astype(np.float32) if was_1d else audio.T.astype(np.float32)
    stretched = pedalboard.time_stretch(buf, sample_rate, stretch_factor=speed)
    return stretched[0] if was_1d else stretched.T

def _best_style(styles: dict[str, int]) -> str:
    """「ノーマル」があればそれを、なければ最小IDのスタイルを返す"""
    if "ノーマル" in styles:
        return "ノーマル"
    return min(styles, key=lambda name: styles[name])

def _extract_text_from_file(filepath: str) -> str:
    """ファイルからテキストを抽出する (.txt / .md / .pdf / .docx / .epub)"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".txt", ".md"):
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext == ".pdf":
        reader = pypdf.PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        if not _DOCX_AVAILABLE:
            raise ImportError(
                "python-docx がインストールされていません。"
                "pip install python-docx を実行してください。"
            )
        doc = DocxDocument(filepath)
        return "\n".join(para.text for para in doc.paragraphs)
    if ext == ".epub":
        try:
            import ebooklib
            from ebooklib import epub
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "EPUB読み込みモジュールがインストールされていません。"
                "pip install EbookLib beautifulsoup4 を実行してください。"
            )
        book = epub.read_epub(filepath)
        chapters: list[str] = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_body_content(), "html.parser")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                if text:
                    chapters.append(text)
        return "\n\n".join(chapters)
    raise ValueError(f"非対応のファイル形式: {ext}")


# ─────────────────────────────────────────
# メインアプリケーションクラス
# ─────────────────────────────────────────
class VoicevoxTTSApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VOICEVOX テキスト読み上げ")
        self.geometry("880x760")
        self.minsize(700, 620)

        # 話者データ
        self._speaker_data: dict[str, dict[str, int]] = dict(DEFAULT_SPEAKER_DATA)

        # スレッド制御フラグ
        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()
        self._is_paused   = False
        self._is_playing  = False

        # 再生セッション管理 (シーク競合対策)
        self._play_generation:  int = 0
        self._seek_pending_gen: int = 0

        # プロデューサー → コンシューマーのキュー
        self._audio_queue: Optional[queue.Queue] = None
        self._slot_semaphore = threading.Semaphore(2)

        # スレッド参照 (シーク時の終了待機に使用する)
        self._producer_thread: Optional[threading.Thread] = None
        self._consumer_thread: Optional[threading.Thread] = None

        # エンジンサブプロセス
        self._engine_proc: Optional[subprocess.Popen] = None

        # チャンク情報
        self._chunks: list[str] = []
        self._chunk_tb_positions: list[tuple[str, str]] = []
        # 前回ハイライトしたチャンクのインデックス (-1 = なし)
        self._highlighted_chunk_idx: int = -1

        self._programmatic_slider_update = False

        # HTTPコネクションプール (TCPハンドシェイクのオーバーヘッドを削減する)
        self._http_session = requests.Session()

        # 設定ファイルを読み込む
        self._settings: dict = self._load_settings()

        self._build_ui()
        self._set_controls_enabled(False)
        self._set_status("エンジン起動中...", "working")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._start_engine_and_init, daemon=True).start()

    # ─── 設定ファイル ─────────────────────────
    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "narrator_char":   self.narrator_char_var.get(),
            "narrator_style":  self.narrator_style_var.get(),
            "dialogue_char":   self.dialogue_char_var.get(),
            "dialogue_style":  self.dialogue_style_var.get(),
            "cpu_priority":    self.cpu_priority_var.get(),
            "playback_speed":  round(self.speed_slider.get(), 1),
            "silence_padding": round(self.padding_slider.get(), 1),
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ─── エンジンライフサイクル ───────────────
    def _start_engine_and_init(self) -> None:
        engine_exe = _resolve_engine_path()

        if os.path.isfile(engine_exe):
            try:
                self._engine_proc = subprocess.Popen(
                    [engine_exe],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError as exc:
                self.after(0, lambda e=str(exc): self._set_status(
                    f"エンジン起動失敗: {e}", "error"))
                self.after(0, lambda: self._set_controls_enabled(True))
                return

        for elapsed in range(ENGINE_STARTUP_TIMEOUT):
            try:
                if self._http_session.get(
                        f"{VOICEVOX_URL}/version", timeout=2).status_code == 200:
                    break
            except Exception:
                pass

            if self._engine_proc and self._engine_proc.poll() is not None:
                self.after(0, lambda: self._set_status("エンジンが予期せず終了しました", "error"))
                self.after(0, lambda: self._set_controls_enabled(True))
                return

            self.after(0, lambda e=elapsed + 1: self._set_status(
                f"エンジン起動中... ({e}秒)", "working"))
            time.sleep(1)
        else:
            self.after(0, lambda: self._set_status(
                f"エンジンの起動が {ENGINE_STARTUP_TIMEOUT}秒 でタイムアウトしました", "error"))
            self.after(0, lambda: self._set_controls_enabled(True))
            return

        # エンジン起動後にCPUリソース制限を適用する
        self.after(0, self._apply_engine_resource_limits)
        self._fetch_speakers()

    def _terminate_engine(self) -> None:
        if self._engine_proc and self._engine_proc.poll() is None:
            self._engine_proc.terminate()
        self._engine_proc = None

    def _on_close(self) -> None:
        self._terminate_engine()
        self.destroy()

    # ─── CPUリソース管理 ─────────────────────
    def _apply_engine_resource_limits(self) -> None:
        """エンジンプロセスにCPU優先度を適用する"""
        if self._engine_proc is None or self._engine_proc.poll() is not None:
            return
        try:
            proc = psutil.Process(self._engine_proc.pid)
            priority_str = self.cpu_priority_var.get()
            proc.nice(_PRIORITY_MAP.get(priority_str, psutil.BELOW_NORMAL_PRIORITY_CLASS))
        except (psutil.Error, AttributeError, ValueError, OSError):
            pass

    def _on_cpu_settings_changed(self, _: str = "") -> None:
        """CPU優先度が変更されたとき: 設定保存 + 即時適用"""
        self._save_settings()
        self._apply_engine_resource_limits()

    # ─── 話者一覧の動的取得 ──────────────────
    def _fetch_speakers(self) -> None:
        try:
            resp = self._http_session.get(f"{VOICEVOX_URL}/speakers", timeout=5)
            resp.raise_for_status()
            speaker_data: dict[str, dict[str, int]] = {}
            for character in resp.json():
                char_name = character["name"]
                styles: dict[str, int] = {
                    s["name"]: s["id"]
                    for s in character.get("styles", [])
                    if s.get("type", "talk") == "talk"
                }
                if styles:
                    speaker_data[char_name] = styles
            if speaker_data:
                self.after(0, lambda d=speaker_data: self._update_speaker_menus(d))
            else:
                self.after(0, lambda: self._set_status("待機中", "idle"))
                self.after(0, lambda: self._set_controls_enabled(True))
        except Exception:
            self.after(0, lambda: self._set_status("待機中", "idle"))
            self.after(0, lambda: self._set_controls_enabled(True))

    def _update_speaker_menus(self, speaker_data: dict[str, dict[str, int]]) -> None:
        self._speaker_data = speaker_data
        char_list = list(speaker_data.keys())

        def _resolve_char(saved: Optional[str], default: str) -> str:
            if saved and saved in speaker_data:
                return saved
            return default if default in speaker_data else char_list[0]

        narrator_char = _resolve_char(self._settings.get("narrator_char"), DEFAULT_NARRATOR_CHAR)
        dialogue_char = _resolve_char(self._settings.get("dialogue_char"), DEFAULT_DIALOGUE_CHAR)

        self.narrator_char_menu.configure(values=char_list)
        self.narrator_char_var.set(narrator_char)
        self.dialogue_char_menu.configure(values=char_list)
        self.dialogue_char_var.set(dialogue_char)

        self._apply_char_change(
            narrator_char, self.narrator_style_menu, self.narrator_style_var,
            saved_style=self._settings.get("narrator_style"),
        )
        self._apply_char_change(
            dialogue_char, self.dialogue_style_menu, self.dialogue_style_var,
            saved_style=self._settings.get("dialogue_style"),
        )

        total_styles = sum(len(v) for v in speaker_data.values())
        self._set_status(
            f"話者一覧を取得しました ({len(char_list)}キャラ / {total_styles}スタイル)", "ok")
        self._set_controls_enabled(True)

    def _apply_char_change(
        self,
        char: str,
        style_menu: ctk.CTkOptionMenu,
        style_var: ctk.StringVar,
        saved_style: Optional[str] = None,
    ) -> None:
        styles = self._speaker_data.get(char, {})
        if not styles:
            return
        style_menu.configure(values=list(styles.keys()))
        if saved_style and saved_style in styles:
            style_var.set(saved_style)
        else:
            style_var.set(_best_style(styles))

    def _on_narrator_char_changed(self, char: str) -> None:
        self._apply_char_change(char, self.narrator_style_menu, self.narrator_style_var)
        self._save_settings()

    def _on_dialogue_char_changed(self, char: str) -> None:
        self._apply_char_change(char, self.dialogue_style_menu, self.dialogue_style_var)
        self._save_settings()

    def _on_narrator_style_changed(self, _: str) -> None:
        self._save_settings()

    def _on_dialogue_style_changed(self, _: str) -> None:
        self._save_settings()

    def _get_speaker_id(self, char: str, style: str, fallback: int) -> int:
        return self._speaker_data.get(char, {}).get(style, fallback)

    # ─── UI 構築 ─────────────────────────────
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)   # TextFrame が縦方向に伸縮
        self._build_top_bar()                 # row 0
        self._build_text_frame()              # row 1
        self._build_navigation_frame()        # row 2
        self._build_voice_setting_frame()     # row 3
        self._build_system_setting_frame()    # row 4
        self._build_control_frame()           # row 5

    def _build_top_bar(self) -> None:
        """TopFrame: クイックアクションバー"""
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))

        self.paste_play_btn = ctk.CTkButton(
            frame, text="▶ ペーストして再生", width=220,
            fg_color="#28a745", hover_color="#218838",
            command=self._on_paste_and_play)
        self.paste_play_btn.pack(side="left", padx=(0, 8))

        self.paste_btn = ctk.CTkButton(
            frame, text="📋 ペースト", width=120, command=self._on_paste_and_reset)
        self.paste_btn.pack(side="left", padx=(0, 14))

        self.import_btn = ctk.CTkButton(
            frame, text="📂 ファイル", width=120, command=self._on_import)
        self.import_btn.pack(side="left", padx=(0, 6))

        self.clear_btn = ctk.CTkButton(
            frame, text="🗑 クリア", width=100, command=self._on_clear)
        self.clear_btn.pack(side="left")

    def _build_text_frame(self) -> None:
        """TextFrame: メインテキストエディタ"""
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        self.textbox = ctk.CTkTextbox(frame, font=ctk.CTkFont(size=14), wrap="word")
        self.textbox.grid(row=0, column=0, sticky="nsew")
        self.textbox.insert("1.0", "ここにテキストを入力してください。")

        self.textbox._textbox.tag_configure(
            HIGHLIGHT_TAG, background=HIGHLIGHT_BG, foreground=HIGHLIGHT_FG)

    def _build_navigation_frame(self) -> None:
        """NavigationFrame: タイムスライダー (再生位置の表示と操作)"""
        frame = ctk.CTkFrame(self, corner_radius=8)
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="位置:", width=45, anchor="e").grid(
            row=0, column=0, padx=(10, 4), pady=8, sticky="e")

        self.time_slider = ctk.CTkSlider(
            frame, from_=0, to=1, number_of_steps=1,
            command=self._on_time_slider_change)
        self.time_slider.set(0)
        self.time_slider.grid(row=0, column=1, padx=6, pady=8, sticky="ew")

        self.time_label = ctk.CTkLabel(frame, text="0 / 0", width=70, anchor="w")
        self.time_label.grid(row=0, column=2, padx=(4, 10), pady=8)

    def _build_voice_setting_frame(self) -> None:
        """VoiceSettingFrame: 地の文/セリフのキャラクターとスタイル選択"""
        frame = ctk.CTkFrame(self, corner_radius=8)
        frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))

        char_list = list(self._speaker_data.keys())
        narrator_styles = list(
            self._speaker_data.get(DEFAULT_NARRATOR_CHAR, {"ノーマル": 2}).keys())
        dialogue_styles = list(
            self._speaker_data.get(DEFAULT_DIALOGUE_CHAR, {"ノーマル": 3}).keys())

        init_narrator_char  = self._settings.get("narrator_char",  DEFAULT_NARRATOR_CHAR)
        init_narrator_style = self._settings.get(
            "narrator_style",
            _best_style(self._speaker_data.get(DEFAULT_NARRATOR_CHAR, {"ノーマル": 2})))
        init_dialogue_char  = self._settings.get("dialogue_char",  DEFAULT_DIALOGUE_CHAR)
        init_dialogue_style = self._settings.get(
            "dialogue_style",
            _best_style(self._speaker_data.get(DEFAULT_DIALOGUE_CHAR, {"ノーマル": 3})))

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(padx=10, pady=(8, 8), anchor="w")
        inner.grid_columnconfigure(1, minsize=180)
        inner.grid_columnconfigure(3, minsize=160)

        # 地の文 (ナレーター)
        ctk.CTkLabel(inner, text="地の文:", width=55, anchor="e").grid(
            row=0, column=0, padx=(0, 4), pady=3, sticky="e")
        self.narrator_char_var = ctk.StringVar(value=init_narrator_char)
        self.narrator_char_menu = ctk.CTkOptionMenu(
            inner, values=char_list, variable=self.narrator_char_var,
            width=180, command=self._on_narrator_char_changed)
        self.narrator_char_menu.grid(row=0, column=1, padx=(0, 6), pady=3)

        ctk.CTkLabel(inner, text="スタイル:", width=60, anchor="e").grid(
            row=0, column=2, padx=(0, 4), pady=3, sticky="e")
        self.narrator_style_var = ctk.StringVar(value=init_narrator_style)
        self.narrator_style_menu = ctk.CTkOptionMenu(
            inner, values=narrator_styles, variable=self.narrator_style_var,
            width=160, command=self._on_narrator_style_changed)
        self.narrator_style_menu.grid(row=0, column=3, pady=3)

        # セリフ (ダイアログ)
        ctk.CTkLabel(inner, text="セリフ:", width=55, anchor="e").grid(
            row=1, column=0, padx=(0, 4), pady=3, sticky="e")
        self.dialogue_char_var = ctk.StringVar(value=init_dialogue_char)
        self.dialogue_char_menu = ctk.CTkOptionMenu(
            inner, values=char_list, variable=self.dialogue_char_var,
            width=180, command=self._on_dialogue_char_changed)
        self.dialogue_char_menu.grid(row=1, column=1, padx=(0, 6), pady=3)

        ctk.CTkLabel(inner, text="スタイル:", width=60, anchor="e").grid(
            row=1, column=2, padx=(0, 4), pady=3, sticky="e")
        self.dialogue_style_var = ctk.StringVar(value=init_dialogue_style)
        self.dialogue_style_menu = ctk.CTkOptionMenu(
            inner, values=dialogue_styles, variable=self.dialogue_style_var,
            width=160, command=self._on_dialogue_style_changed)
        self.dialogue_style_menu.grid(row=1, column=3, pady=3)

    def _build_system_setting_frame(self) -> None:
        """SystemSettingFrame: CPU優先度の設定"""
        frame = ctk.CTkFrame(self, corner_radius=8)
        frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 0))

        init_priority = self._settings.get("cpu_priority", "Below Normal")

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(padx=10, pady=(8, 8), anchor="w")

        # CPU優先度ドロップダウン
        ctk.CTkLabel(inner, text="CPU優先度:", width=80, anchor="e").grid(
            row=0, column=0, padx=(0, 4), pady=3, sticky="e")
        self.cpu_priority_var = ctk.StringVar(value=init_priority)
        ctk.CTkOptionMenu(
            inner,
            values=["Normal", "Below Normal", "Low"],
            variable=self.cpu_priority_var,
            width=140,
            command=self._on_cpu_settings_changed,
        ).grid(row=0, column=1, pady=3)

    def _build_control_frame(self) -> None:
        """ControlFrame: 再生/一時停止/停止ボタン + 話速スライダー + ステータス"""
        frame = ctk.CTkFrame(self, corner_radius=8)
        frame.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 12))

        self.play_btn = ctk.CTkButton(
            frame, text="▶  再生", width=90, command=self._on_play)
        self.play_btn.pack(side="left", padx=(10, 6), pady=8)

        self.pause_btn = ctk.CTkButton(
            frame, text="⏸  一時停止", width=120,
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=self._on_pause_resume)
        self.pause_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            frame, text="⏹  停止", width=90,
            state="disabled", fg_color=COLOR_DISABLED, hover=False,
            command=self._on_stop)
        self.stop_btn.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(frame, text="話速:").pack(side="left", padx=(0, 4))
        saved_speed = self._settings.get("playback_speed", SPEED_DEFAULT)
        self.speed_slider = ctk.CTkSlider(
            frame, from_=SPEED_MIN, to=SPEED_MAX, number_of_steps=25,
            width=150, command=self._on_speed_change)
        self.speed_slider.set(saved_speed)
        self.speed_slider.pack(side="left", padx=(0, 6))
        self.speed_label = ctk.CTkLabel(
            frame, text=f"{round(saved_speed, 1):.1f}x", width=50, anchor="w")
        self.speed_label.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(frame, text="余白:").pack(side="left", padx=(0, 4))
        saved_padding = self._settings.get("silence_padding", SILENCE_PADDING_SEC)
        self.padding_slider = ctk.CTkSlider(
            frame, from_=0.0, to=1.0, number_of_steps=10,
            width=100, command=self._on_padding_change)
        self.padding_slider.set(saved_padding)
        self.padding_slider.pack(side="left", padx=(0, 4))
        self.padding_label = ctk.CTkLabel(
            frame, text=f"{saved_padding:.1f}s", width=40, anchor="w")
        self.padding_label.pack(side="left", padx=(0, 10))

        self.status_label = ctk.CTkLabel(
            frame, text="エンジン起動中...", text_color=STATUS_COLORS["working"])
        self.status_label.pack(side="right", padx=14)

    # ─── チャンク管理 ─────────────────────────
    def _update_chunks(self) -> None:
        """テキストを再分割し、スライダー範囲とテキストボックス内の位置インデックスを更新する"""
        text = self.textbox.get("1.0", "end-1c")
        self._chunks = _split_text(text)
        self._chunk_tb_positions = self._compute_chunk_positions(text, self._chunks)
        n = len(self._chunks)
        if n > 1:
            self.time_slider.configure(from_=0, to=n - 1, number_of_steps=n - 1)
        else:
            self.time_slider.configure(from_=0, to=1, number_of_steps=1)
        self._update_time_label(int(self.time_slider.get()))

    def _compute_chunk_positions(
        self, text: str, chunks: list[str]
    ) -> list[tuple[str, str]]:
        """各チャンクのテキストボックス内開始・終了インデックス ("line.col") を計算する"""
        positions: list[tuple[str, str]] = []
        search_start = 0
        for chunk in chunks:
            idx = text.find(chunk, search_start)
            if idx < 0:
                fallback = positions[-1] if positions else ("1.0", "1.0")
                positions.append(fallback)
                continue
            end_idx = idx + len(chunk)
            positions.append((
                self._offset_to_tb_index(text, idx),
                self._offset_to_tb_index(text, end_idx),
            ))
            search_start = end_idx
        return positions

    @staticmethod
    def _offset_to_tb_index(text: str, offset: int) -> str:
        """文字オフセットを tkinter Text の "line.col" 形式に変換する"""
        before = text[:offset]
        line   = before.count("\n") + 1
        col    = len(before) - (before.rfind("\n") + 1)
        return f"{line}.{col}"

    def _highlight_chunk(self, chunk_idx: int) -> None:
        """
        指定チャンクをハイライトする。
        前回のチャンクのタグだけをピンポイントで削除し、全体スキャンを避ける。
        """
        tb = self.textbox._textbox
        # 前回ハイライトしたチャンクのタグのみを削除する
        if (self._highlighted_chunk_idx >= 0
                and self._highlighted_chunk_idx < len(self._chunk_tb_positions)):
            old_start, old_end = self._chunk_tb_positions[self._highlighted_chunk_idx]
            if old_start != old_end:
                tb.tag_remove(HIGHLIGHT_TAG, old_start, old_end)
        # 新しいチャンクにタグを付与してスクロールする
        if self._chunk_tb_positions and chunk_idx < len(self._chunk_tb_positions):
            start, end = self._chunk_tb_positions[chunk_idx]
            if start != end:
                tb.tag_add(HIGHLIGHT_TAG, start, end)
                tb.see(start)
        self._highlighted_chunk_idx = chunk_idx

    def _clear_all_highlights(self) -> None:
        """すべてのハイライトを一括解除してインデックスをリセットする"""
        self.textbox._textbox.tag_remove(HIGHLIGHT_TAG, "1.0", "end")
        self._highlighted_chunk_idx = -1

    def _update_time_label(self, idx: int) -> None:
        n = len(self._chunks)
        self.time_label.configure(text=f"{idx + 1 if n else 0} / {n}")

    # ─── イベントハンドラ ───────────────────
    def _on_clear(self) -> None:
        self.textbox.delete("1.0", "end")
        self._chunks = []
        self._chunk_tb_positions = []
        self._clear_all_highlights()
        self.time_slider.configure(from_=0, to=1, number_of_steps=1)
        self.time_slider.set(0)
        self._update_time_label(0)

    def _get_clipboard_text(self) -> str:
        try:
            return self.clipboard_get()
        except Exception:
            return ""

    def _on_paste_and_reset(self) -> None:
        text = self._get_clipboard_text()
        if not text:
            self._set_status("クリップボードが空です", "error")
            return
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self._clear_all_highlights()
        self._update_chunks()
        self.time_slider.set(0)
        self._update_time_label(0)
        if self._chunks:
            self._highlight_chunk(0)
        self._set_status("ペースト完了", "ok")

    def _on_paste_and_play(self) -> None:
        self._on_paste_and_reset()
        if self._chunks:
            self._start_playback(0)

    def _on_import(self) -> None:
        """ファイルダイアログを開いてテキストを読み込む"""
        filetypes = [
            ("対応ファイル",       "*.txt *.md *.pdf *.docx *.epub"),
            ("テキストファイル",   "*.txt"),
            ("Markdown",          "*.md"),
            ("PDFファイル",        "*.pdf"),
            ("Word ファイル",      "*.docx"),
            ("EPUBファイル",       "*.epub"),
            ("すべてのファイル",   "*.*"),
        ]
        filepath = filedialog.askopenfilename(
            title="ファイルを選択してください", filetypes=filetypes)
        if not filepath:
            return
        try:
            text = _extract_text_from_file(filepath)
        except ImportError as exc:
            self._set_status(str(exc), "error")
            return
        except Exception as exc:
            self._set_status(f"読み込みエラー: {exc}", "error")
            return

        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self._clear_all_highlights()
        self._update_chunks()
        self.time_slider.set(0)
        self._update_time_label(0)
        self._highlight_chunk(0)
        self._set_status(f"読み込み完了: {os.path.basename(filepath)}", "ok")

    def _on_time_slider_change(self, value: float) -> None:
        """タイムスライダーの手動操作コールバック"""
        if self._programmatic_slider_update:
            return
        idx = int(round(value))
        if self._chunks:
            idx = min(idx, len(self._chunks) - 1)
        self._update_time_label(idx)
        self._highlight_chunk(idx)
        if self._is_playing:
            self._seek_to(idx)

    def _on_speed_change(self, value: float) -> None:
        self.speed_label.configure(text=f"{round(value, 1):.1f}x")

    def _on_padding_change(self, value: float) -> None:
        self.padding_label.configure(text=f"{value:.1f}s")
        self._save_settings()

    def _on_play(self) -> None:
        """再生ボタン: スライダーの現在位置からチャンク再生を開始する"""
        text = self.textbox.get("1.0", "end").strip()
        if not text:
            self._set_status("テキストを入力してください。", "error")
            return
        self._update_chunks()
        start_index = 0
        if self._chunks:
            raw_idx = int(round(self.time_slider.get()))
            start_index = min(raw_idx, len(self._chunks) - 1)
        self._start_playback(start_index)

    def _start_playback(self, start_index: int) -> None:
        """指定チャンクインデックスから再生セッションを開始する"""
        text = self.textbox.get("1.0", "end").strip()
        narrator_id = self._get_speaker_id(
            self.narrator_char_var.get(), self.narrator_style_var.get(), fallback=2)
        dialogue_id = self._get_speaker_id(
            self.dialogue_char_var.get(), self.dialogue_style_var.get(), fallback=3)

        self._stop_event.clear()
        self._pause_event.clear()
        self._is_paused  = False
        self._is_playing = True

        self._cleanup_temp_files()
        self._audio_queue    = queue.Queue()
        self._slot_semaphore = threading.Semaphore(2)

        self._play_generation += 1
        gen = self._play_generation

        self._set_controls_enabled(False)
        n = len(self._chunks)
        self._set_status(f"処理を開始します... ({start_index + 1}/{n})", "working")

        self._producer_thread = threading.Thread(
            target=self._producer,
            args=(text, narrator_id, dialogue_id, start_index, gen),
            daemon=True,
        )
        self._consumer_thread = threading.Thread(
            target=self._consumer,
            args=(gen,),
            daemon=True,
        )
        self._producer_thread.start()
        self._consumer_thread.start()

    def _on_pause_resume(self) -> None:
        if not self._is_paused:
            self._is_paused = True
            self._pause_event.set()
            sd.stop()
            self.pause_btn.configure(text="▶  再開")
            self._set_status("一時停止中", "paused")
        else:
            self._is_paused = False
            self._pause_event.clear()
            self.pause_btn.configure(text="⏸  一時停止")
            self._set_status("再開します...", "working")

    def _on_stop(self) -> None:
        """停止ボタン: 再生/合成スレッドへ停止シグナルを送る"""
        self._stop_event.set()
        self._pause_event.clear()
        self._is_paused = False
        sd.stop()
        if self._audio_queue is not None:
            try:
                self._audio_queue.put_nowait(None)
            except Exception:
                pass
        self._set_status("停止しました", "stopped")

    def _seek_to(self, idx: int) -> None:
        """再生中にスライダーが動いた場合: 旧セッションを無効化して新位置から再起動する"""
        self._play_generation += 1
        seek_gen = self._play_generation
        self._seek_pending_gen = seek_gen

        # ① 停止シグナルを送信してオーディオハードウェアを即座に停止する
        self._stop_event.set()
        sd.stop()

        # ② コンシューマーが queue.get() でブロックしている場合に備えて終端を投入し、
        #    キューの残留データをすべてクリアする
        if self._audio_queue is not None:
            try:
                self._audio_queue.put_nowait(None)
            except Exception:
                pass
            while True:
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

        # ③ バックグラウンドスレッドで旧スレッドの完全終了を待ってから再起動する
        threading.Thread(
            target=self._wait_and_restart,
            args=(idx, seek_gen),
            daemon=True,
        ).start()

    def _wait_and_restart(self, idx: int, seek_gen: int) -> None:
        """旧スレッドの完全終了を待機してから新セッションをUIスレッドで起動する"""
        # sounddevice がファイルハンドルを完全に解放するまで待機する
        time.sleep(0.1)

        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=2.0)
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=2.0)

        if seek_gen != self._seek_pending_gen:
            return
        if not self._is_playing:
            return

        self.after(0, lambda: self._apply_seek(idx, seek_gen))

    def _apply_seek(self, idx: int, seek_gen: int) -> None:
        """シーク後の再起動 (最新のシーク要求のみ有効)"""
        if seek_gen != self._seek_pending_gen:
            return
        if not self._is_playing:
            return
        self._update_chunks()
        idx = min(idx, max(0, len(self._chunks) - 1))
        self._start_playback(idx)

    # ─── プロデューサースレッド (合成) ─────────
    def _producer(
        self,
        text: str,
        narrator_id: int,
        dialogue_id: int,
        start_index: int,
        gen: int,
    ) -> None:
        """
        テキストをチャンク分割し、VOICEVOX API で合成して静的スロットファイルに書き込む。
        セマフォで最大2スロット先行に制限し、コンシューマーの再生ペースに同期する。
        スロット割り当ては start_index からリセットされる:
          start_index     → temp_1.wav
          start_index + 1 → temp_2.wav
          start_index + 2 → temp_3.wav
          start_index + 3 → temp_1.wav  (以降ローテーション)
        """
        assert self._audio_queue is not None
        try:
            chunks = _split_text(text)
            total  = len(chunks)

            for index, chunk in enumerate(chunks, start=1):
                chunk_idx = index - 1

                if chunk_idx < start_index:
                    continue

                if self._stop_event.is_set() or gen != self._play_generation:
                    break

                while self._pause_event.is_set():
                    if self._stop_event.is_set() or gen != self._play_generation:
                        break
                    time.sleep(0.05)
                if self._stop_event.is_set() or gen != self._play_generation:
                    break

                # start_index を基点にローテーションをリセットする
                slot_path = TEMP_PATHS[(chunk_idx - start_index) % TEMP_SLOT_COUNT]
                slot_acquired = False
                while True:
                    if self._stop_event.is_set() or gen != self._play_generation:
                        break
                    if self._slot_semaphore.acquire(timeout=0.1):
                        slot_acquired = True
                        break
                if not slot_acquired:
                    break

                if gen != self._play_generation:
                    self._slot_semaphore.release()
                    break

                if not chunk.endswith(("。", "！", "？", "!", "?")):
                    chunk += "。"
                speaker_id = _speaker_for_chunk(chunk, narrator_id, dialogue_id)

                try:
                    # ② audio_query (セッションの接続プールを再利用する)
                    self.after(0, lambda i=index, t=total: self._set_status(
                        f"音声クエリを送信中... ({i}/{t})", "working"))
                    query_resp = self._http_session.post(
                        f"{VOICEVOX_URL}/audio_query",
                        params={"text": chunk, "speaker": speaker_id},
                        timeout=30,
                    )
                    query_resp.raise_for_status()
                    audio_query = query_resp.json()
                    del query_resp  # レスポンスオブジェクトを即時解放する
                    audio_query["postPhonemeLength"] = (
                        audio_query.get("postPhonemeLength", 0.0) + 0.15
                    )

                    # ③ synthesis
                    self.after(0, lambda i=index, t=total: self._set_status(
                        f"WAVデータを合成中... ({i}/{t})", "working"))
                    synthesis_resp = self._http_session.post(
                        f"{VOICEVOX_URL}/synthesis",
                        params={"speaker": speaker_id},
                        json=audio_query,
                        timeout=60,
                    )
                    synthesis_resp.raise_for_status()
                    del audio_query

                    if gen != self._play_generation:
                        self._slot_semaphore.release()
                        break

                    wav_bytes = synthesis_resp.content
                    del synthesis_resp  # レスポンスオブジェクトを即時解放する

                    # ④ PermissionError が発生した場合は 0.05秒待機してリトライする (最大5回)
                    write_ok = False
                    for _attempt in range(5):
                        try:
                            with open(slot_path, "wb") as f:
                                f.write(wav_bytes)
                            write_ok = True
                            break
                        except PermissionError:
                            time.sleep(0.05)
                    del wav_bytes  # バイト列を解放する
                    if not write_ok:
                        raise PermissionError(
                            f"一時ファイルへの書き込みが5回失敗しました: "
                            f"{os.path.basename(slot_path)}"
                        )

                    # ⑤ コンシューマーにスロットパスを通知する
                    self._audio_queue.put((slot_path, index, total, chunk_idx))

                except Exception:
                    self._slot_semaphore.release()
                    raise

        except requests.exceptions.ConnectionError:
            self.after(0, lambda: self._set_status(
                "接続エラー: VOICEVOXエンジンが起動していません", "error"))
            self._stop_event.set()
        except requests.exceptions.Timeout:
            self.after(0, lambda: self._set_status(
                "タイムアウト: VOICEVOXの応答が遅延しています", "error"))
            self._stop_event.set()
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            self.after(0, lambda: self._set_status(f"APIエラー: HTTP {code}", "error"))
            self._stop_event.set()
        except Exception as exc:
            msg = str(exc)
            self.after(0, lambda: self._set_status(f"予期しないエラー: {msg}", "error"))
            self._stop_event.set()
        finally:
            self._audio_queue.put(None)

    # ─── コンシューマースレッド (再生) ─────────
    def _consumer(self, gen: int) -> None:
        """
        audio_queue からスロットパスを取り出し、WAV を RAM に読み込んでスロットを解放する。
        タイムストレッチと無音パディングを適用してから再生する。
        UIの最終リセットはこのスレッドが担う (世代チェックで保護する)。
        """
        assert self._audio_queue is not None
        try:
            while True:
                while self._pause_event.is_set():
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.05)

                if self._stop_event.is_set():
                    break

                item = self._audio_queue.get()
                if item is None:
                    break

                slot_path, index, total, chunk_idx = item

                self.after(0, lambda ci=chunk_idx: self._on_consumer_progress(ci))
                self.after(0, lambda i=index, t=total: self._set_status(
                    f"再生中... ({i}/{t})", "working"))

                # ① スロットファイルを RAM に読み込む
                # FileNotFoundError → スキップ / PermissionError → リトライ (最大5回)
                audio_data: Optional[np.ndarray] = None
                sample_rate: Optional[int] = None
                for _attempt in range(5):
                    try:
                        audio_data, sample_rate = sf.read(slot_path, dtype="float32")
                        break
                    except FileNotFoundError:
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.05)

                # ② スロットを解放する (ファイルは RAM に展開済みなので上書き可能)
                self._slot_semaphore.release()

                if audio_data is None:
                    break

                # ③ 話速スライダーをリアルタイムに読み取りタイムストレッチを適用する
                speed = round(self.speed_slider.get(), 1)
                audio_processed = _time_stretch(audio_data, sample_rate, speed)
                del audio_data  # 元波形データを即時解放する

                # ④ 前後に無音パディングを付加する
                #    先頭: DACウェイクアップレイテンシによる冒頭クリップを防ぐ
                #    末尾: ハードウェアバッファの早期フラッシュを防ぐ
                pre_len     = int(sample_rate * PRE_PADDING_SEC)
                silence_len = int(sample_rate * self.padding_slider.get())
                if audio_processed.ndim == 1:
                    pre_silence = np.zeros(pre_len,     dtype=np.float32)
                    silence     = np.zeros(silence_len, dtype=np.float32)
                else:
                    pre_silence = np.zeros(
                        (pre_len,     audio_processed.shape[1]), dtype=np.float32)
                    silence     = np.zeros(
                        (silence_len, audio_processed.shape[1]), dtype=np.float32)
                padded = np.concatenate([pre_silence, audio_processed, silence])
                del pre_silence, audio_processed, silence  # 結合前の配列を解放する

                # ⑤ 再生 (停止時は sd.stop() でここから即座に抜ける)
                sd.play(padded, samplerate=sample_rate)
                sd.wait()
                del padded  # 再生完了後に RAM を解放する

                if self._stop_event.is_set():
                    break

            if gen == self._play_generation and not self._stop_event.is_set():
                self.after(0, lambda: self._set_status("完了", "ok"))

        except Exception as exc:
            msg = str(exc)
            if gen == self._play_generation:
                self.after(0, lambda: self._set_status(f"再生エラー: {msg}", "error"))
        finally:
            if gen == self._play_generation:
                self._is_playing = False
                self._cleanup_temp_files()
                self._is_paused = False
                self._pause_event.clear()
                self.after(0, lambda: self.pause_btn.configure(text="⏸  一時停止"))
                self.after(0, lambda: self._set_controls_enabled(True))
                self.after(0, self._clear_all_highlights)

    def _on_consumer_progress(self, chunk_idx: int) -> None:
        """コンシューマーから呼ばれる進捗更新: スライダーとハイライトを同期する"""
        self._programmatic_slider_update = True
        if self._chunks:
            self.time_slider.set(chunk_idx)
        self._update_time_label(chunk_idx)
        self._programmatic_slider_update = False
        self._highlight_chunk(chunk_idx)

    # ─── ヘルパー ────────────────────────────
    def _set_status(self, message: str, level: str = "idle") -> None:
        color = STATUS_COLORS.get(level, STATUS_COLORS["idle"])
        self.status_label.configure(text=message, text_color=color)

    def _set_controls_enabled(self, enabled: bool) -> None:
        idle_state = "normal" if enabled else "disabled"
        for widget in (
            self.play_btn, self.paste_btn, self.paste_play_btn,
            self.clear_btn, self.import_btn,
            self.narrator_char_menu, self.narrator_style_menu,
            self.dialogue_char_menu, self.dialogue_style_menu,
        ):
            widget.configure(state=idle_state)
        # 話速スライダーとタイムスライダーは常に操作可能
        self.speed_slider.configure(state="normal")
        self.time_slider.configure(state="normal")
        if enabled:
            for btn in (self.pause_btn, self.stop_btn):
                btn.configure(state="disabled", fg_color=COLOR_DISABLED, hover=False)
        else:
            self.pause_btn.configure(
                state="normal", fg_color=COLOR_PAUSE_ACTIVE, hover=True)
            self.stop_btn.configure(
                state="normal", fg_color=COLOR_STOP_ACTIVE, hover=True)

    def _cleanup_temp_files(self) -> None:
        """3つの静的一時WAVファイルをディスクから削除する"""
        for path in TEMP_PATHS:
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def destroy(self) -> None:
        """ウィンドウ終了時に再生・エンジンを停止し、一時ファイルを後片付けする"""
        self._stop_event.set()
        self._pause_event.clear()
        sd.stop()
        if self._audio_queue is not None:
            try:
                self._audio_queue.put_nowait(None)
            except Exception:
                pass
        self._cleanup_temp_files()
        self._terminate_engine()
        self._http_session.close()
        super().destroy()


# ─────────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────────
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = VoicevoxTTSApp()
    app.mainloop()
