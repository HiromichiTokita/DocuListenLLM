# DocuListen Irodoriエンジン統合 設計書（サブPJ-2a）

**日付:** 2026-06-27
**対象:** DocuListen 本体（`main.py`, Python 3.14）に Irodori VoiceDesign を VOICEVOX と切替可能な
TTSエンジンとして追加する「土台」。サブPJ-1（`E:\project\IrodoriVDServer` のHTTPサーバ／バンドル）を利用する。

> ⚠️ **方針: 完成度ガチガチではなく「動く一本通し（vertical slice）」を優先**。
> ユーザーが実際に試しながら調整する前提。テストは核心ロジックに限定、エラー処理は実用最小限。
> 感情/スタイル分類LLM による動的キャプション（喜怒哀楽）は **サブPJ-2b（別spec）** に切り出し、本書では扱わない。

---

## 背景・狙い
DocuListen は現在 VOICEVOX のみで読み上げる。Irodori VoiceDesign（自然文キャプションで声質を指定）を
切替式で追加し、まずは「カテゴリ毎の固定キャプション」で Irodori 再生を本体で動かす。
既存の2段階LLM配役（カテゴリ推定）は無改造で再利用する。

## スコープ
- IN: エンジン切替UI＋設定、Irodoriバンドルの遅延自動起動、合成バックエンド抽象化（VOICEVOX/Irodori）、
  カテゴリ→キャプション解決（UI編集可・既定値）、再生連携（速度は consumer 側 `_time_stretch`）。
- OUT（2b以降）: 感情/スタイル分類LLM、参照音声併用、配布構成の最終化。

## アーキテクチャ（合成バックエンド抽象化＝案B）
```
Stage1/2 LLM配役（無改造）→ 各チャンクに category
  → _resolve_voice(category, engine)
       voicevox: category→archetype→ speaker_id（既存ロジック）
       irodori : category→ caption（新規・カテゴリ毎の文）
  → _synthesize_chunk(text, voice, engine) -> wav_bytes（新規ディスパッチャ）
       voicevox: audio_query→synthesis（_producerから抽出。speed=speedScale）
       irodori : POST 127.0.0.1:<port>/synthesize {text, caption} -> wav
  → 一時スロットWAV → consumer 再生（irodori時は _time_stretch で再生速度適用）
```
- エンジン差分は「声の解決」と「合成呼び出し」の2箇所のみに隔離。`_producer` は薄くなる。

## コンポーネント（`main.py` に追加）
- **`IrodoriServerManager`**（小クラス）: バンドル `irodori-vd-runtime/python.exe -m vd_server --port <p> --checkpoint <c>`
  を **遅延 subprocess 起動**、`/health` を ready までポーリング（状態をUIへ）、既に `<port>` が ready なら再利用、
  アプリ終了時に**自分が起動したプロセスのみ**停止。バンドルパスは設定 `irodori_runtime_path`。
- **`_resolve_voice(category, engine)`**: VV=speaker_id / Irodori=caption。地の文・未知カテゴリは narrator にフォールバック。
- **`_synthesize_chunk(text, voice, engine) -> bytes`**: エンジン別合成。Irodori は `requests.post(.../synthesize)`。
  異常時は呼び出し側（`_producer`）の既存 `SKIP` 機構へ。
- **キャプション設定**: 14カテゴリ＋ナレーターの caption 文字列（既定値つき・UI編集可・settings保存）。

## UI
- トップバー: エンジン切替トグル「VOICEVOX / Irodori」＋ Irodori状態（停止/起動中…/ready/エラー）。
- AIディレクタータブ: 各アーキタイプ行に caption 入力欄（Irodori選択時に編集対象、VV話者選択と共存・出し分け）＋ナレーター用1欄。

## 設定キー（settings.json、後方互換・既存を壊さない）
| キー | 既定 | 用途 |
|------|------|------|
| `tts_engine` | `"voicevox"` | 選択エンジン |
| `irodori_runtime_path` | dev既定 `E:\project\IrodoriVDServer\irodori-vd-runtime`（無ければ要設定） | バンドル場所 |
| `irodori_port` | `8770` | サーバポート |
| `irodori_checkpoint` | ローカル重み `E:\project\DocuListenLLM\IrodoriTTS\model.safetensors`（無ければHF既定） | `--checkpoint` |
| `archetypes[x].caption` / `narrator_caption` | 14種＋ナレーターの既定文 | カテゴリ毎キャプション |

## 速度・既存機能の扱い
- VOICEVOX: 速度は従来 `audio_query["speedScale"]`。
- Irodori: server は speed 無視 → consumer 側で既存 `_time_stretch`（pedalboard）を適用。
- 配役キャッシュ／再生位置記憶／WAV保存等は wav_bytes 共通経路に乗るため原則そのまま動く。

## エラー処理（実用最小限）
- 起動失敗 / `load_error` / ready前タイムアウト → 状態「エラー」表示、自動でVVに戻さない（ユーザー切替）。原因明示。
- チャンク合成失敗(500等) → 既存 `SKIP` で1チャンク飛ばす。致命的接続エラーは停止。
- バンドルパス不在 → 「`irodori_runtime_path` を設定してください」。
- アプリ終了 → 自分が起動したサーバのみ停止。

## テスト方針（核心のみ）
- `_resolve_voice`（カテゴリ→speaker_id/caption、地の文・未知カテゴリのフォールバック）
- `_synthesize_chunk`（`requests` をモックし VV/Irodori 両経路の URL/ペイロード・wav_bytes・エラー写像）
- `IrodoriServerManager` のパス解決・"8770生存なら再利用" 分岐（fake health で）
- UI/実機再生（VV↔Irodori切替読み上げ）は手動確認。網羅は求めない（試行調整前提）。

## 受け入れ基準（このサブPJの「動いた」）
1. エンジンをIrodoriに切替→バンドルが遅延起動し状態が ready になる。
2. テキストを再生→各チャンクが category 毎キャプションで Irodori 合成され、複数キャラの声で読み上がる。
3. VOICEVOXに戻すと従来通り再生（後方互換）。Irodoriは起動しない。
4. キャプションをUIで編集→次の再生に反映。設定が保存される。
