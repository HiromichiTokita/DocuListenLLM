# Irodori VoiceDesign HTTPサーバ 設計書（サブPJ-1）

**日付:** 2026-06-25
**対象:** DocuListenLLM への IrodoriTTS 導入（切替式併存）の基盤となるTTSサーバ

---

## 背景・狙い

DocuListen に VOICEVOX と切替可能な TTS エンジンとして **IrodoriTTS** を追加したい。
狙いは **声の表現力（感情）**。Irodori の **VoiceDesign**（自然文キャプションで声質・感情・
話し方を指定）を使い、地の文は落ち着いた声、会話・心の声は感情を込めて読む。

ただし公式の OpenAI 互換サーバ（`Irodori-TTS-Server`）は **ベースモデル 500M-v3 専用**で、
`voice`(参照音声)＋絵文字までしか扱えず、**VoiceDesign キャプションを HTTP で渡せない**
（`irodori` オプションは推論ハイパラのみ・caption フィールド無し。2026-06-25 調査で確認）。

→ 本サブPJで **VoiceDesign を HTTP 公開する自前サーバ**を用意する。
本体アプリ（サブPJ-2・別spec）はこのサーバの HTTP 契約だけに依存する。

### 全体分割（再掲）
- **サブPJ-1（本書）**: Irodori VoiceDesign HTTPサーバ。単体で curl 検証できる独立成果物。
- **サブPJ-2（別spec）**: DocuListen 本体改造（エンジン切替・感情分類LLM・男女キャプション組立・再生連携）。

---

## 前提・制約

- **VoiceDesign は caption-only で運用**（`infer.py ... --no-ref` 相当）。男女・声質・感情は
  すべてキャプションで表現する。参照音声併用（3分岐の ref）は将来オプションとしてスコープ外。
- **実行環境**: torch + CUDA 12.8 + モデル(600M)。本体アプリは Python **3.14** だが torch の
  3.14 wheel は未整備の可能性が高い → 本サーバは **別 Python（3.11/3.12）の別プロセス**で動かす。
  VOICEVOX エンジンと同じ「外部ローカルサービス」の立ち位置。
- **GPU 前提**（ユーザー環境は NVIDIA CUDA あり）。CPU でも動くが実用外。配布先も NVIDIA GPU 必須。
- **配布方式 = ポータブルPython同梱＋本体が自動起動（2026-06-25 決定）**:
  python-build-standalone（埋め込み Python 3.11）＋ torch/CUDA/Irodori-TTS/`vd_server` 一式を
  **フォルダごと同梱**し、本体アプリが起動時に `python.exe -m vd_server` を**自動起動**する
  （VOICEVOX エンジンと同じ自動起動方式）。**torch を PyInstaller に通さない**ことで安定性を確保。
  - 本サブPJの成果物に **ポータブルバンドルの構築手順＋スモークテスト**を含める。
  - 本体からの**自動起動ロジック**はサブPJ-2 が担当。
  - モデル重み(約1.3GB)は **初回起動時に HuggingFace から自動DL**し、インストーラには焼かない
    （初回のみネット必要）。
  - ⚠️ 配布物は VOICEVOX(2.16GB)＋torch/CUDA(約3GB) で **6〜7GB級**になる。Irodori は本体常時同梱の
    既定ではなく **「高品質オプション」**としての位置づけ（配布構成の最終判断はサブPJ-2/リリース時）。

---

## HTTP 契約

ベース URL: `http://127.0.0.1:8770`（ポートは引数で変更可）。
本体アプリは VOICEVOX 同様 `requests` で直接叩くため、**OpenAI 互換にはせず最小の独自API**とする。

### `GET /health`
- モデルロード状況を返す。
- ロード中: `503` + `{"status":"loading","ready":false}`
- 完了後: `200` + `{"status":"ok","ready":true,"sample_rate":<int>,"model":"<checkpoint>"}`

### `POST /synthesize`
- リクエスト（JSON）:
  ```json
  {
    "text": "こんにちは。これはテストです。",
    "caption": "落ち着いた女性の声で、近い距離感でやわらかく自然に読み上げてください。",
    "speed": 1.0,
    "seed": 1234
  }
  ```
  | フィールド | 型 | 必須 | 説明 |
  |-----------|----|----|------|
  | `text` | string | ◯ | 読み上げる本文（1チャンク） |
  | `caption` | string | ◯ | VoiceDesign キャプション（声質＋感情） |
  | `speed` | number | – | 既定 1.0。範囲 0.25–4.0（範囲外は clamp） |
  | `seed` | integer | – | 再現用。未指定なら毎回ランダム |
- レスポンス（成功）: `200`、`Content-Type: audio/wav`、**WAV バイト列**。
  - モデル出力（float32 numpy + sample_rate）を `soundfile` で **WAV / 16-bit PCM（`subtype="PCM_16"`）**
    にエンコードして返す（VOICEVOX の 16-bit wav と同等。アプリ consumer は `dtype="float32"` で読むため
    どちらでも可だが、サイズ・互換のため 16-bit に固定）。**SR はモデルのものを wav ヘッダに埋める**（アプリ側は `sf.read` で
    SR を取得。既存の再生・時間伸縮・リサンプル・BGM 合成は SR 非依存なのでそのまま動く）。
- レスポンス（異常）: JSON `{"error": "<message>"}` ＋ ステータス
  - `400`: `text` 空 / JSON 不正 / 型不正
  - `503`: モデル未ロード（起動直後）
  - `500`: 推論中の例外

### `GET /` （任意）
- 簡単な情報・使い方を返す（人間向け）。実装は任意。

---

## サーバ内部設計

ファイル: `irodori_vd_server.py`（Irodori-TTS リポジトリ直下に配置し、その venv で実行）。

### 起動・モデルロード
- 起動引数: `--host 127.0.0.1 --port 8770 --checkpoint Aratako/Irodori-TTS-600M-v3-VoiceDesign --device cuda`
- 起動時に **モデルを1回だけロード**（プロセス常駐）。`gradio_app_voicedesign.py` のロード/推論
  コードを流用する（実装時に `InferenceRuntime` 等の**実APIをリポジトリで確認**してから確定）。
- ロード完了フラグを持ち、`/health` と `/synthesize` の 503 判定に使う。
- 起動直後に短いウォームアップ推論を1回行い、初回レイテンシを平準化（任意・推奨）。

### 並行制御
- GPU 推論は非スレッドセーフかつ同時1件 → **`threading.Lock` で `/synthesize` を直列化**。
  単一ワーカーで起動（uvicorn `--workers 1`）。本体 producer は HTTP の戻りで自然にスロットルされる。

### 推論フロー（`/synthesize`）
1. リクエスト検証（`text` 必須・非空、`caption` 必須）。
2. `speed` を 0.25–4.0 に clamp、`seed` があれば固定。
3. Lock 取得 → `runtime.infer(text=..., caption=..., no_ref=True, ...)` 相当を呼ぶ
   → `(audio: np.ndarray float32, sample_rate: int)`。
4. `soundfile.write(BytesIO, audio, sample_rate, format="WAV")` で WAV 化。
5. `Response(content=wav_bytes, media_type="audio/wav")`。
6. 例外は捕捉して `500` + `{"error": ...}`。

### 技術スタック
- `fastapi` + `uvicorn`（軽量・単一ファイルで完結）。
- 既存の Irodori 推論依存（torch/transformers/safetensors/einops/peft）は **Irodori-TTS の venv に既に入る**前提。
  サーバ追加分は `fastapi`・`uvicorn`・`soundfile`（無ければ追加）。

---

## 成果物

- `vd_server/` パッケージ（サーバ本体: `app.py` / `backend.py` / `wav.py` / `__main__.py`）。
  `python -m vd_server --host 127.0.0.1 --port 8770` で起動。
- 開発用起動スクリプト（`run_irodori_server.ps1`）と README（セットアップ・curl 検証）。
- **ポータブルPythonバンドル構築手順＋スモークテスト**（配布用）:
  python-build-standalone(3.11)＋torch(CUDA12.8)＋Irodori-TTS＋`vd_server` を1フォルダ化し、
  そのフォルダ内の `python.exe -m vd_server` 単体で起動できることを確認する手順。
  モデル重みは**初回起動時にHF自動DL**（バンドルには焼かない）。
- ※ ソース/バンドルは **Irodori-TTS のクローン側**に置く（DocuListen 本体は HTTP 契約のみ依存）。
  本体からの**自動起動はサブPJ-2**が担当（本サブPJはバンドルが単体起動できる所まで）。

---

## 検証（単体・受け入れ基準）

1. `python irodori_vd_server.py` 起動 → 初期 `/health` が 503(loading)、ロード後 200(ready, sample_rate>0)。
2. `curl -X POST http://127.0.0.1:8770/synthesize -H "Content-Type: application/json" \
   -d '{"text":"こんにちは。これはテストです。","caption":"落ち着いた女性の声で、近い距離感でやわらかく自然に読み上げてください。"}' \
   --output out.wav` → 再生可能な WAV が得られる（`soundfile` で読めて SR>0、無音でない）。
3. 別キャプション（例: 「深く傷つき声を震わせ悲痛なトーンで弱々しく話す」）で**声色・感情が変わる**ことを耳で確認。
4. 異常系: 空 `text`→400、不正 JSON→400、起動直後→503。
5. 連続 5 リクエストが Lock で直列化され、クラッシュせず順に WAV を返す。
6. **バンドルスモーク**: 配布フォルダ内の `python.exe -m vd_server` を**クリーン環境（開発venv非依存）**で
   起動し、上記 1–2 が通ること（自動DL後）。

---

## スコープ外（サブPJ-2・別spec で扱う）

- DocuListen のエンジン切替 UI / 設定保存
- 感情・スタイル分類（軽量 Ollama）と男女基本キャプションの組立
- 再生時の男女選択 UI、producer のバックエンド抽象化、未起動時の案内
- 参照音声併用（声の同一性ピン留め）

---

## 確認済み事項（2026-06-26・`E:\project\Irodori-TTS-code` をクローンして確定）

- **実API**: `InferenceRuntime.from_key(RuntimeKey(checkpoint, model_device, codec_repo, model_precision,
  codec_device, codec_precision, ...))` → `runtime.synthesize(SamplingRequest(text, caption, no_ref=True,
  num_steps=40, cfg_scale_text=3.0, cfg_scale_caption=3.0, seed=...), log_fn=None)` →
  `SamplingResult(audio: torch.Tensor, sample_rate: int, used_seed, audios, ...)`。
- `SamplingRequest` は **`text` のみ必須**、他は既定値。caption-only は `no_ref=True`＋`caption` を渡すだけ。
- **`speed` はモデルに無い**（速度は DocuListen consumer の `_time_stretch` で処理。server の speed 引数は無視）。
- **出力サンプルレート = 48000Hz**（DACVAE codec `Aratako/Semantic-DACVAE-Japanese-32dim`）。wav ヘッダに埋める。
- `audio` は **torch.Tensor** → `.detach().to("cpu").float().numpy()` で numpy 化、(ch,N)なら転置して `encode_wav_pcm16` へ。
- 推奨 `cfg_scale`: 既定 `cfg_scale_text=3.0 / cfg_scale_caption=3.0`、`num_steps=40`（速度↔品質で調整可）。
- **環境**: GitHubコード `E:\project\Irodori-TTS-code`（`uv` 管理・torch 2.10 cu128）、モデル重みは
  `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors`（600M-v3-VoiceDesign）。GPU: RTX 5070 Ti 16GB。
