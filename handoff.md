# DocuListenLLM 引継ぎ資料（handoff）

> 最終更新: 2026-06-26 ／ 対象バージョン: **v1.3.0**
> 本書は開発を引き継ぐ／再開する際の**単一の現状把握ドキュメント**です。
> （旧 `HANDOVER.md` / `DEVELOPMENT_HISTORY.md` を本書に統合・一本化しました。）

---

## 0. 重要ステータス（最初に読む）

- ✅ **バージョン文字列の不整合は解消済み**（2026-06-26）: `main.py` の `APP_VERSION` を
  **`v1.3.0`** に修正し、配布物（`dist/DocuListen_v1.3.0/`）と一致。`build.py` は `APP_VERSION` を
  正規表現で自動参照するため全箇所に反映。`py -m py_compile main.py` 通過確認済み。
- ✅ **`miniaudio` 依存は不要**（2026-06-26）: BGM機能を削除したため。`requirements.txt` /
  `DocuListen.spec` / `main.py` のいずれにも残存なしを確認済み。
- ⚠️ **実行 Python は 3.14**（`C:\Users\toki0\AppData\Local\Python\pythoncore-3.14-64\python.exe`、`py` のデフォルト）。
  PATH の `python` は **3.12 で別物**（customtkinter 等が入っていない）。
  pip install・実行・ビルドは必ず **`py main.py` / `py build.py`（=3.14）** で行うこと。
- ⚠️ **Git 未導入**（本体リポジトリ）。履歴・ロールバック不能。**削除は復元不可**。`git init` を最優先で推奨。
- 🚧 **IrodoriTTS サーバ（サブPJ）は実装未着手**。設計・環境準備は完了。詳細は §8。

---

## 1. プロジェクト概要

**DocuListenLLM**（アプリ名: DocuListen）は、テキスト/文書ファイルをローカル LLM で
登場人物・セリフ解析し、VOICEVOX で「複数キャラの声を自動配役して読み上げる」
デスクトップアプリ（AI Audio Director）。すべてローカル完結（クラウド送信なし）。

- 言語/UI: Python + customtkinter（CTk）
- TTS: VOICEVOX エンジン（同梱、`engine/`、ローカル `http://127.0.0.1:50021`）
- LLM: Ollama（ローカル `http://127.0.0.1:11434`、デフォルト定数 `llama3.2`）
- 配布形態: PyInstaller `--onefile --noconsole` で単一 exe 化 + `engine/` 同梱

---

## 2. リポジトリ現状

| 項目 | 状態 |
|------|------|
| バージョン管理 | **Git 管理外**（本体）。バックアップは手動。`IrodoriTTS/` と `E:\project\Irodori-TTS-code` は各々独立した git |
| メインソース | `main.py`（約2,895行。v1.3.0で14機能追加・BGM実装→削除） |
| 旧ソース | `archive/main_old.py`（v0.0.1相当・1,202行、参照用） |
| ビルド | `build.py`（PyInstaller ラッパー。`APP_VERSION` を自動参照）、`DocuListen.spec` |
| 設定 | `settings.json`（全UI状態を保存。削除でデフォルトに戻る） |
| 依存 | `requirements.txt`（実依存と一致。`miniaudio`/`librosa` は不要） |
| エンジン | `engine/`（VOICEVOX 一式・約2.16GB、`*.vvm` モデル・DLL・キャラ情報） |
| 配布物 | `dist/DocuListen_v1.3.0/DocuListen_v1.3.0.zip`（約1.87GB） |
| アイコン | `icon.ico` |
| 提案資料 | `docs/presentation_DocuListenLLM.md` |

---

## 3. バージョン履歴（時系列）

```
2026-06-01  v0.0.1   初の安定版。AI Audio Director の基礎が完成
2026-06-02  v1.2.1   実用化フェーズ：自動抽出・広域文脈配役・目次スキップ
2026-06-14  v1.2.2   EPUB取込の堅牢化（黒箱だった処理を全面改修）
2026-06-15  v1.2.3   ルビ起因の不具合修正＋ルビ→かな変換オプション
2026-06-17  ―        リポジトリ軽量化・整理（依存整理／不要コード削除）
2026-06-25  v1.3.0   14機能追加（BGM等）・提案資料作成
2026-06-26  ―        BGM削除／APP_VERSION整合／handoff資料一本化
```

開発スタイル: **ユーザーの「読めない／おかしい」報告を起点に、原因を切り分けて修正する反復改善型**。

### v0.0.1（2026-06-01）基盤の確立
- VOICEVOX TTS 統合（producer/consumer のストリーミング再生）
- 2配役モード: ルールベース（地の文/セリフ）／ AI Director（14アーキタイプ自動配役）
- 2段階 LLM パイプライン（Stage1: 人物プロファイリング、Stage2: セリフ単位の話者推定）
- ファイル取込 `.txt/.md/.pdf/.docx/.epub`、再生制御、Ollamaモデル選択、デバッグログ窓

### v1.2.1 まで（2026-06-02）実用化と精度向上
- **dirtyフラグ方式の自動抽出**: テキスト変更で `_char_dict_dirty=True`、初回再生時のみ Stage1 自動実行
- **Stage2 = 「per-chunk ±10チャンク 広域文脈」配役**（一括版より精度重視で確定）
  対象行を `===> [TARGET DIALOGUE TO CLASSIFY]:` でマーキング、前後両方の手がかりを参照
- ステータスバー `(n/total)` 進捗、目次(TOC)自動スキップ
- コンテキスト溢れ対策（Stage1 8000字切詰め＋`num_ctx:16384`、Stage2 `num_ctx:8192`）
- ルビ除去（EPUB `<rt>/<rp>`、DOCX `w:rt`、TXT/MD 青空文庫 `《》`/`｜`）
- デフォルト声「主人公 男」= 玄野武宏 → **黒沢冴白**

### v1.2.2（2026-06-14）EPUB取込の堅牢化
- デバッグログ追加（章ごと抽出文字数・スキップ・合計）、読み順を spine 順に修正
- タグ非依存抽出（`get_text`）、過剰スキップ撤廃（自動生成nav `EpubNav` のみ除外）
- 空時フォールバック＋原因切り分け（本文<50字で画像≥5なら「画像形式で読めない」等を `ValueError`）
- **結論**: 「読めないEPUB」はバグでなく**ファイル種別**の問題。画像型EPUB（KCC変換等）は本文テキスト0でOCR必要・対象外

### v1.2.3（2026-06-15）ルビ起因の修正と新オプション
- **1文字段落バグ修正**: 本文抽出をブロック要素境界のみ改行する方式へ（`_doc_text`）
- **ルビ→かな変換オプション**（ツールバー、初期OFF、設定保存）。`_extract_text_from_file(filepath, ruby_to_kana=False)` ＋ `_convert_aozora_ruby()`
- **既知の制約（ユーザー合意）**: ルビが大文字かなで記録されたEPUBは `御者`→`ぎよしや` になる。
  原因はソースEPUB側（拗音・促音を小書きしない流儀）。機械的な大文字→小文字変換は
  `りよう→りょう` 等を壊す誤変換リスクがあるため**自動変換は入れず現状維持**

### 整理作業（2026-06-17）
- `requirements.txt` を実依存に修正、未使用 `BATCH_ATTRIBUTION_PROMPT` 削除、`main_old.py` を `archive/` へ

### v1.3.0（2026-06-25）14機能追加
1. VOICEVOXポート設定（`VOICEVOX_PORT`）
2. 再生位置の記憶（本文MD5＋チャンクindex）
3. 配役キャッシュ（同一テキストは2回目以降 LLM 不要）
4. キーボードショートカット一覧（`?` キー）
5. スクリプトエクスポート（CSV/JSON、💾）
6. ログウィンドウボタン（📋）
7. 音量均一化（RMS正規化、`_rms_normalize`）
8. 数字の読み方設定（そのまま / ひとつずつ）
9. チャンクプレビュー窓（🔍）
10. WAV保存（🎵、全チャンク合成→1ファイル）
11. 前処理カスタム除去パターン（正規表現）
12. Ollamaベンチマーク
13. ~~BGMオーバーレイ~~ → **2026-06-26 削除**（§7）
14. 連続ファイル再生キュー（📂）
- バグ修正: Spaceショートカット、LONE_SKIP拡張、TOC正規表現改善、タイムスライダー、エンジン起動エラー早期検知、TTSチャンクスキップ非致命化、`DEBUG`フラグ導入
- ※ 上記は `docs/superpowers/` の各 spec/plan（volume-slider / ui-overhaul / streaming-cast / subtab）で設計・実装された機能群。すべて出荷済み。

---

## 4. 技術アーキテクチャ（現行）

### 2段階 LLMパイプライン
```
入力文書 → チャンク分割(_split_text)
  → Stage1: 人物プロファイリング(PROFILING_PROMPT) → {"characters":[{name,category}]}
            （dirtyフラグで初回再生時のみ自動実行）
  → Stage2: セリフ配役(ATTRIBUTION_PROMPT) per-chunk ±10チャンク文脈で話者カテゴリ推定
            （失敗・"ナレーション"・未知カテゴリ時は直前話者にフォールバック）
  → VOICEVOX 合成 → producer/consumer ストリーミング再生
```

### 14カテゴリ（固定）
`主人公 女/男、子供 男/女、若者 男/女、中年 男/女、老人 男/女、ロボット、
人外仲間(かわいい)、人外仲間(かっこいい)、怪物`（＋地の文用「ナレーション」）

### `main.py` の地図（行番号は v1.2.x 時点の目安。現在約2,895行なので `Grep` で関数名検索推奨）
```
定数 (L35-)          VOICEVOX_URL / OLLAMA_URL / DEFAULT_ARCHETYPES / 各PROMPT / APP_VERSION(L51)
ヘルパ関数           _resolve_app_dir, _resolve_engine_path, _extract_text_from_file
_TeeStream           stdout→ログウィンドウ転送
VoicevoxTTSApp       メインクラス
  _start_engine_and_init     エンジン起動
  _fetch_ollama_models / _fetch_speakers   API取得
  _extraction_thread          Stage1 手動抽出
  _split_text                 本文をチャンク分割
  _llm_and_play_thread        ★Stage1自動+Stage2配役+再生開始
  _start_playback / _producer / _consumer  ストリーミング再生
  _seek_to / _apply_seek      シーク
```
音声ヘルパ（モジュール直下）: `_rms_normalize`（RMS正規化）／`_time_stretch`（再生速度・pedalboard）

主要プロンプト定数: `PROFILING_PROMPT`（Stage1）／`ATTRIBUTION_PROMPT`（Stage2・現行使用）

### 配布
- `py build.py`（PyInstaller `--onefile --noconsole`）。出力 `dist/DocuListen_<APP_VERSION>/`
- ⚠️ `build.py` は冒頭で **`build/` と `dist/` を丸ごと削除**する
- hidden-import: `sounddevice/soundfile/cffi/_sounddevice_data`、`pedalboard` は `collect_all`（`DocuListen.spec`）

---

## 5. 開発上の重要な学び・判断

| テーマ | 学び・判断 |
|--------|-----------|
| 配役の速度 vs 精度 | 一括15件（高速）より per-chunk広域文脈（高精度）を選択（v1.2.1） |
| EPUBの「読めない」 | バグではなくファイル種別の問題。画像型EPUBはOCR必要で対象外と明確化 |
| ルビ→かな変換 | 機械変換は誤変換リスク。自動拗音化は見送り（ユーザー合意） |
| 黒箱の可視化 | デバッグログ追加で原因切り分けが一気に進んだ（EPUB処理） |
| BGM | チャンク毎リサンプル/ミキシングがレイテンシ要因で再生が止まる→撤去（§7） |
| 実行環境 | 実行Pythonは3.14。PATHの3.12とは別物（ハマりどころ） |

---

## 6. 現在の設定値（`settings.json`）

- ナレーター: 四国めたん / 主役女: 春日部つむぎ / 主役男: 黒沢冴白
- 再生速度: 2.5、無音パディング: 0.4、CPU優先度: Low
- Ollamaモデル: `hf.co/mmnga/Llama-3.1-Swallow-8B-Instruct-v0.5-gguf:latest`（日本語特化。デフォルト定数 `llama3.2` とは別）
- 引用符: quote1=「」, quote2=『』, quote3=なし
- `character_rules`: 「本好きの下剋上」系の人物14名がプリセット保存済み

> ⚠️ 配布時注意: `settings.json` に**特定作品の人物リストが残存**。一般配布時は人物リストを空にしたクリーン版を用意すること。

---

## 7. BGM（実装→削除の経緯）

- v1.3.0 で BGMオーバーレイを実装（MP3/OGG/FLAC=`miniaudio`、WAV=`soundfile`、`_consumer`内で混合）。
  無音バグ（librosa未導入＋ステレオ転置）を numpy 線形補間に置換して一旦修正。
- **2026-06-26 機能削除**: 実機で**会話中に再生が頻繁に止まる**（チャンク毎のリサンプル/ミキシングが
  レイテンシ要因）ためユーザー判断で撤去。設定キー `bgm_path`/`bgm_volume`・UI・`_select_bgm_file`・
  `_consumer`内BGM処理・`_resample_linear` を削除、`miniaudio` を `requirements.txt`/`DocuListen.spec` からも除去。
  `py -m py_compile main.py` 通過。`main.py` 内に BGM/miniaudio 関連の残存なしを確認済み。

---

## 8. IrodoriTTS サブプロジェクト（VOICEVOX切替式の感情表現TTS）

**狙い**: DocuListen に VOICEVOX と切替可能な TTS として **IrodoriTTS VoiceDesign**（自然文キャプションで
声質・感情・話し方を指定）を追加し、地の文は落ち着いた声、会話・心の声は感情を込めて読む。

### 現状: **✅ サブPJ-1（HTTPサーバ）完了（2026-06-27）。次はサブPJ-2（本体改造）**
Task 0〜8＋最終レビュー＋配布バンドルのGPUスモークまで全て完了。`E:\project\IrodoriVDServer` に
動作する常駐TTSサーバ＋自己完結ポータブルバンドルが揃い、コミット18個で保全済み。

作業先は **`E:\project\IrodoriVDServer`**（新規・独立git・独自venv Python3.12）。
`IrodoriTTS`/`Irodori-TTS-code` はどちらもクローン取得物なので成果物は置かない（前回 Task1/Task3 消失の教訓）。

#### 実装進捗（IrodoriVDServer リポジトリ、コミット履歴に保全）
- ✅ **Task 0**: ワークスペース確立（git init・venv3.12・サーバ依存導入・pyproject/gitignore）
- ✅ **Task 1**: WAVエンコーダ `vd_server/wav.py`（PCM_16）— 2 tests green（`a7ff722`）
- ✅ **Task 2**: `SynthBackend` Protocol + `FakeBackend`（`caf5a0e`）
- ✅ **Task 3**: FastAPI `/health`（`3ed0d1e`）
- ✅ **Task 4**: `/synthesize`（検証・speed clamp・`threading.Lock`直列化・エラー写像）+ レビュー指摘修正
  （503未ロード時の body を spec準拠の `{"error":...}` に修正）— **計15 tests green**（`c9a31e0`+`6c0b3e3`）
- ✅ **Task 5**: 実 `VoiceDesignBackend` + CLI `__main__.py`（`36f4c39`）。**GPU実機検証 合格**（`33f8a6f`）:
  `python -m vd_server` 起動→`/health` が ready遷移（SR=48000）→ 2キャプションで**異なる非無音WAVを生成**確認。
  環境: torch2.11+cu128 / torchaudio2.11 / transformers4.57 / dacvae+descript-audiotools+einops / silentcipher
  （透かし。初回に `sony/silentcipher` 自動DL）。**torchcodec は不要**。完全な依存は `requirements-frozen.txt`。
- ✅ **Task 6**: `requirements-vd-server.txt` / `run_irodori_server.ps1` / `VD_SERVER_README.md`（`2c929a2`）。
  受け入れ検証は httpx で実施（Windows curl は日本語UTF-8が壊れ400になるため README に明記）。CPUテスト15件green。
- ✅ **Task 7（ビルド完成）**: 配布用ポータブルPythonバンドル `irodori-vd-runtime/`（gitignore）を構築（`0632bc6`/`13ad89e`）。
  埋め込みPython3.12.13＋torch2.11+cu128＋torchaudio＋推論依存＋dacvae/silentcipher＋
  **irodori_tts/vd_server を非editableコピー**。自己完結を確認（中立cwdからimportがバンドル内を解決）。
  生成スクリプト `build_vd_bundle.ps1`、起動 `irodori-vd-runtime/start.ps1`、`BUNDLE_README.md`。
  🚧 **GPUスモークテスト（start.ps1→/health ready→synth）のみ保留**（ユーザーがComfyUIでGPU使用中のため）。
- ✅ **最終コードレビュー（全branch・sonnet）完了**（`bd2cfdc`、16 tests green）: `/health` でロード失敗を
  `{"status":"error","error":...}` として返すよう改善（永久503の不可視問題を解消）＋テスト強化。
  バンドル内 vd_server コピーも修正版に更新済み。
- ✅ **Task 7 GPUスモークテスト合格**（2026-06-27、`c48e5ee`）: バンドルの `python.exe` を**中立cwdから起動**→
  `/health` ready（SR=48000）→ 2キャプションで**異なる非無音WAV**生成を確認。配布バンドルは自己完結で動作。
- ✅ **サブPJ-1 完了**。コミット18個・`requirements-frozen.txt` で再現可能。

#### 既知の制約（合意済み・対応保留）
- `/synthesize` の GPU 推論は async ハンドラ内で同期実行のため、推論中（数秒）はイベントループが塞がり
  `/health` 応答が待たされる。単一ユーザのローカル用途では許容（必要なら `asyncio.to_thread`＋`asyncio.Lock` 化）。

#### サブPJ-2a（本体統合・土台）— 設計/計画 着手（2026-06-27）
方針: **ガチガチにせず「動く一本通し」優先（試しながら調整）**。感情分類LLMは 2b に分離。
- 設計: `docs/superpowers/specs/2026-06-27-irodori-engine-integration-design.md`
- 計画: `docs/superpowers/plans/2026-06-27-irodori-engine-integration.md`（Task 0〜6）
- 構成: 純粋ロジックを新モジュール **`irodori_engine.py`**（caption既定値・`resolve_caption`・`synthesize_irodori`・
  `IrodoriServerManager`）に分離しpytest、`main.py` はエンジン切替UI/キャプション欄/`_producer`分岐/遅延起動/終了停止を配線。
- 重要前提: Stage2は `category` を保存せず `style_id` のみ（`main.py:2345`）→ Task4で各チャンクに `category` 保存を追加。
- 速度はIrodori時 consumer の `_time_stretch` で適用。後方互換（`tts_engine` 既定 voicevox）。

**進捗（2026-06-27）**:
- ✅ **Task 0**: DocuListenLLM を `git init`＋`.gitignore`（engine/・dist除外、handoff TODO#1消化）。baseline `53a59a4`。
- ✅ **Task 1–3**: `irodori_engine.py` 完成（`DEFAULT_CAPTIONS`・`resolve_caption`・`synthesize_irodori`＋`IrodoriSynthError`・
  `IrodoriServerManager`＋`IrodoriLaunchError`）。**pytest 12件 green**（`870e5e0`/`038a2f5`/`b7c5978`）。
  customtkinter非依存でテスト可能な純粋ロジック層が完成。
- ✅ **Task 4**: main.py に設定キー（tts_engine/irodori_*/captions/narrator_caption）＋既定値補完、`_save_settings`追記、
  Stage2で各チャンクに `category` 保存（`21ff927`）。py_compile OK。
- ✅ **Task 5**: トップバーにエンジン切替（voicevox/irodori）＋状態ラベル＋`_on_engine_changed`、AIディレクタータブの
  各役にキャプション入力欄＋ナレーター欄。`_on_close` に `_save_settings()`＋`_irodori.stop()`（guard）追加（`21ff927`）。
  ※ **GUIは未起動確認**（要: `py main.py` で目視。エンジン切替が出る/キャプション欄が並ぶ/編集が再起動で保持）。
- ✅ **Task 6（コード完成）**（`208d201`/`62ff0c7`）: `__init__`で`IrodoriServerManager`生成、`_producer`をエンジン分岐
  （irodori時 category→`resolve_caption`→`synthesize_irodori`）、producerスレッド先頭で遅延起動`ensure_running`、
  エンジン/キャプションは開始時にスナップショット（スレッド安全）。`_on_close`でstop。
  **重要**: 速度は既存 `_consumer` が全WAVに `_time_stretch` 適用済み＝Irodoriも自動で速度が乗る（追加不要だった）。
  「ナレーション」のキャプションは専用ナレーター欄に一本化（`62ff0c7`）。
  ✅ **E2E実走で読み上げ成功**（2026-06-27、ユーザー確認）: irodori選択→遅延起動→ready→Irodoriの声で連続読み上げ。
  - 🐞 **無音バグを修正**（`1919a06`）: `sd.play(samplerate=48000)` が一部環境で最初のチャンクで詰まり無音化。
    `_resample_linear` で **48kHz→24kHz にリサンプル**してVOICEVOXと同じ実績ある再生経路に統一（`PLAYBACK_SR=24000`）。
    speech/感情表現は24kHzで実質劣化なし。診断用 `[IRODBG]` ログは撤去済み。
  - 🐞 **二重起動→残留サーバ修正**（`00405d0`）: `ensure_running` にロック＋「生存中なら再spawnしない」ガード（+test、13 green）。
  - 🐞 **声の一貫性 修正試行（seed固定, `b84cedb`）→ 効果不十分**: `caption_seed()` で同一キャプション→同一seedにしたが、
    **caption-only の Irodori は同キャプション・同seedでもテキストが変わると声（話者）が変わる**ことが実走で判明
    （ログ上ナレーションは全て同カテゴリ＝同キャプション＝同seedなのに声が揺れる）。seed配線は正常・determinism目的では有効。
  → **sub-PJ-2a の配線（切替/起動/再生/速度/seed）は完成・動作確認済み。ただし声の一貫性は caption-only の限界で未達**。

#### ⚠️ 重要な設計学び（声の一貫性には参照音声が必須）
caption-only では話者同一性を固定できない（キャプション＝声の"種類"は決まるが、毎回の生成で具体的な声がテキスト依存で変動）。
**カテゴリ毎に一貫した声**にするには **参照音声（ボイスクローン）** が必要:
- サーバ拡張: `/synthesize` で参照音声を受ける、または `/voice {voice_id,caption,seed}` で基準音声を1回生成・サーバ側キャッシュ→
  `/synthesize {text, voice_id}` で `ref_wav`/`no_ref=False` 合成（モデルは ref をサポート済み）。
- アプリ: カテゴリ毎に基準音声を1回登録→以降そのカテゴリは voice_id で合成。
これは spec で「参照音声併用＝スコープ外（2b）」とした領域。

#### サブPJ-2b（参照音声で声を固定）— 設計/計画 着手（2026-06-27）
- 設計: `docs/superpowers/specs/2026-06-27-irodori-reference-voice-design.md`
- 計画: `docs/superpowers/plans/2026-06-27-irodori-reference-voice.md`（Task 1〜7、2リポジトリ）
- 方針: approach A=**サーバ側refキャッシュ**。`/synthesize` に `use_ref` 追加、サーバが `(caption,seed)` 毎に
  基準音声を1回自動生成→キャッシュ→`ref_wav` クローン。キャッシュ責務は model非依存 `RefCache` に分離しpytest。
  アプリは カテゴリ毎seed＋🎲リロール＋「声を固定」チェックを追加。後方互換厳守（`use_ref` 既定False＝2a同一）。
- 基準フレーズ `REF_PHRASE`。GPU必須の `VoiceDesignBackend` ref合成(Task3)＋E2E(Task7)は手動・GPU空き時。
- サーバ改修につき配布バンドル `irodori-vd-runtime` の vd_server 再コピーが必要（Task7）。

**進捗（2026-06-27）**:
- ✅ **Task 1**（IrodoriVDServer）: `vd_server/ref_cache.py` `RefCache`（2 tests、`43c68f3`）
- ✅ **Task 2**（IrodoriVDServer）: `/synthesize` に `use_ref`＋FakeBackend記録＋VoiceDesignBackend.infer署名拡張（計20 tests、`0b5b876`）
- ✅ **Task 4**（DocuListenLLM）: `synthesize_irodori(use_ref)`＋`voice_seed_for`＋`new_seed`（計19 tests、`7800f18`）
- ✅ **Task 3**（IrodoriVDServer, `10c2bb0`）: `VoiceDesignBackend` に `REF_PHRASE`＋`RefCache`＋`_generate_ref`/`_synthesize_ref`、
  `infer(use_ref)` で `(caption,seed)` 基準音声を1回生成→`ref_wav`クローン、失敗時caption-onlyフォールバック。import OK。
  併せて `pytest.ini`（testpaths=tests、バンドルのsklearnテスト収集を除外）追加。サーバ計20 tests green。
- ✅ **Task 5**（DocuListenLLM, `b75a563`）: 設定 `irodori_use_ref`(既定True)/`caption_seeds`、`_save_settings`追記、
  producerが `voice_seed_for` のカテゴリ毎seed＋`use_ref` で合成。
- ✅ **Task 6**（DocuListenLLM, `b75a563`）: トップバー「声を固定」チェック＋各役/ナレーターに🎲リロールボタン＋`_reroll_voice`。py_compile OK・19 tests green。
- ✅ **Task 7 Step1**: 配布バンドル `irodori-vd-runtime` の vd_server を更新（ref_cache.py含む・use_ref反映・import OK）。
- ⏳ **Task 7 Step2（E2E・GPU）のみ未**: irodori＋「声を固定」ON で再生→同カテゴリ一貫・🎲で変化・OFFで2a互換、を実走確認。
  → **2b はコード完成・バンドル準備済み。残りはGPU空き時のE2Eのみ**。

#### サブPJ-2b（表現力・将来）
セリフ単位の感情/スタイル分類LLM による動的キャプション（喜怒哀楽）を別 spec→plan で。

> 注意点（判明事項）: `Irodori-TTS-code/.venv` は **torch が壊れている**（`torch.hub` 欠落）ためフォールバック不可。
> `pip install -e` の全依存は gradio5/wandb/datasets 等を含み10GB級になるため、**推論に必要な最小依存のみ**導入する方針。
> `VoiceDesignBackend._load` はロード失敗時に `load_error` を記録する try/except 入り（プランからの小改善、最終レビュー報告対象）。
> 実装計画: `docs/superpowers/plans/2026-06-26-irodori-voicedesign-server.md`（Task 0〜8）。

### 完了している準備
| 項目 | 状態 |
|------|------|
| モデル重み | `IrodoriTTS/model.safetensors`（600M-v3-VoiceDesign）DL済み |
| 公式コード | `E:\project\Irodori-TTS-code` にクローン＋`.venv`構築済み |
| 実API確認 | 下記の通り実コードで確定済み |
| GPU | RTX 5070 Ti 16GB |

### 確認済みの実API（再計画時に再利用可・2026-06-26 確定）
- `InferenceRuntime.from_key(RuntimeKey(checkpoint, model_device, codec_repo, model_precision,
  codec_device, codec_precision, ...))`
  → `runtime.synthesize(SamplingRequest(text, caption, no_ref=True, num_steps=40,
  cfg_scale_text=3.0, cfg_scale_caption=3.0, seed=...), log_fn=None)`
  → `SamplingResult(audio: torch.Tensor, sample_rate: int, used_seed, ...)`
- `SamplingRequest` は **`text` のみ必須**。caption-only は `no_ref=True`＋`caption` を渡すだけ。
- **`speed` はモデルに無い**（速度は DocuListen consumer の `_time_stretch` で処理）。
- **出力サンプルレート = 48000Hz**（DACVAE codec `Aratako/Semantic-DACVAE-Japanese-32dim`）。
- `audio` は torch.Tensor → `.detach().to("cpu").float().numpy()` で numpy 化。

### 設計上の決定（再計画の出発点）
- VoiceDesign を **caption-only**（`--no-ref` 相当）で運用。男女・声質・感情はすべてキャプションで表現。
- サーバは torch 前提のため、本体（Python3.14）とは**別Python（3.11/3.12）の別プロセス**で常駐。
  VOICEVOX エンジンと同じ「外部ローカルサービス」の立ち位置。
- HTTP契約（独自最小API、`http://127.0.0.1:8770`）:
  - `GET /health` → ロード状況（503 loading → 200 ready, sample_rate, model）
  - `POST /synthesize` `{text, caption, speed?, seed?}` → `audio/wav`（16-bit PCM、SRはモデル値）
  - GPU推論は `threading.Lock` で直列化（同時1件）
- 配布方式: ポータブルPython同梱フォルダを本体が自動起動（torchをPyInstallerに通さない）。
  モデル重みは初回起動時にHF自動DL。配布物は6〜7GB級になるため「高品質オプション」位置づけ。
- 分割: サブPJ-1（HTTPサーバ単体）／サブPJ-2（本体改造: エンジン切替UI・感情分類LLM・男女キャプション組立・再生連携）。

> **再計画済み（2026-06-26）**: 旧設計を踏襲し、新しい実装計画
> `docs/superpowers/plans/2026-06-26-irodori-voicedesign-server.md` を作成（Task 0〜8）。
> 設計of record は `docs/superpowers/specs/2026-06-25-irodori-voicedesign-server-design.md`。
>
> **作業先（重要・確定）**: `IrodoriTTS`（モデル重み）も `Irodori-TTS-code`（上流コード）も**どちらもクローン取得物**で
> 再クローンすると成果物が消える（前回 Task1・Task3 消失の原因）。よって vd_server は**独立新フォルダ
> `E:\project\IrodoriVDServer`**（独自git・独自venv: Python3.12 + torch cu128）に置く。
> `irodori_tts` は `pip install -e E:\project\Irodori-TTS-code`（editable）で参照、モデル重みは
> `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors` を**読み取り専用 checkpoint** として参照。
> Task 0 で git init＋ベースラインコミット、各Task末尾で必ずコミットして再発防止。
> **進捗は本§8冒頭「現状」を参照（Task 0〜4完了・Task 5 GPU環境構築中）。**

---

## 9. 既知の課題・引継ぎTODO

- [ ] **`git init`** + `.gitignore`（`dist/`, `build/`, `__pycache__/`, `engine/`大容量, `*.zip`, `out.txt`, `err.txt`）— 最優先
- [ ] 配布用クリーン `settings.json`（人物リスト空）の用意
- [ ] **大容量同梱**（`engine/` 約2.16GB ＋ `dist/*.zip`）の配布/バックアップ運用方針の整理
- [ ] IrodoriTTS サーバの再計画＋実装（§8）
- [x] ~~`APP_VERSION` を v1.3.0 に統一~~（2026-06-26 完了）
- [x] ~~`requirements.txt` を実依存に更新／`miniaudio`・`librosa` 不要化~~（完了）
- [x] ~~バージョン番号の一元管理~~（`APP_VERSION` へ集約済み）

---

## 10. 参考: メモリ（`~/.claude/.../memory/`）

- `project_milestone_v130.md` — v1.3.0 機能サマリ（2026-06-25時点）
- `project_milestone_v122.md` — v1.2.3 機能サマリ（2026-06-15時点。ファイル名はv122だが内容v1.2.3）
- `project_milestone_v121.md` — v1.2.1 機能サマリ（2026-06-02時点）
- `project_milestone_v001.md` — v0.0.1 初回安定版（2026-06-01）
