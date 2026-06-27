# Irodori 参照音声による声の固定 設計書（サブPJ-2b）

**日付:** 2026-06-27
**対象:** sub-PJ-2a で判明した「caption-only では声がテキスト毎に変わる」問題を、**参照音声（ボイスクローン）**で解決する。
サーバ（`E:\project\IrodoriVDServer` の `vd_server`）とアプリ（`E:\project\DocuListenLLM` の `main.py`/`irodori_engine.py`）の両方を拡張する。

> ⚠️ **方針: lean（動く一本通し優先・試しながら調整）**。核心ロジックのみ pytest、GUI/E2E は手動（GPU要）。
> 後方互換を厳守（`use_ref` 無し＝2aの caption-only と完全同一）。

---

## 背景・問題
caption-only の Irodori は、同一キャプション・同一seedでも**テキストが変わると話者（声）が変わる**（2a実走で確認）。
話者同一性を固定する手段が caption-only に無いため、ナレーションが1文ごとに別の声になり違和感がある。

## 解決方針（approach A: サーバ側refキャッシュ）
カテゴリ毎に**基準音声を1回だけ自動生成**してサーバにキャッシュし、そのカテゴリの全チャンクを**その基準音声でクローン**する。
基準音声はキャプション＋seedから自動生成（録音不要）。🎲リロールでseedを変えれば別の声を選べる。

## スコープ
- IN: サーバ `/synthesize` の `use_ref` 拡張＋ (caption,seed) 毎の基準音声キャッシュ／アプリのカテゴリ毎seed・🎲リロール・声固定チェックボックス／producer連携／バンドル再ビルド手順。
- OUT: ユーザー提供の参照音声ファイル、感情/スタイル分類LLM（別途）、複数基準のブレンド等。

## サーバ設計（vd_server）
- **基準音声キャッシュ**: `VoiceDesignBackend` 内インメモリ `dict[(caption, seed), ref_wav_path]`（一時ファイル）。プロセス内のみ（遅延起動なので許容）。`threading.Lock` 下でアクセス。
- **基準フレーズ（定数）**: `REF_PHRASE = "こんにちは。今日はいい天気ですね。少しお話しします。"`（数秒・クローン用）。
- **`/synthesize` 拡張**: リクエスト `{text, caption, speed?, seed?, use_ref?: bool=False}`。
  - `use_ref=True` かつ caption 非空:
    1. `(caption, seed)` 未キャッシュ → `REF_PHRASE` を caption-only（`no_ref=True`）＋caption＋seed で合成→一時WAV→キャッシュ。
    2. `text` を `ref_wav=基準WAV, no_ref=False, caption, seed` で合成し返す（声をクローン）。
  - `use_ref=False`／caption空: 現状の caption-only（2a互換・無改造）。
  - 例外時: 当該リクエストは caption-only にフォールバック（無音化させない）。失敗はログ。
- **backend API 拡張**: `SynthBackend.infer(text, caption, speed, seed, use_ref: bool = False)`。`FakeBackend` は `use_ref` を受け取り**記録のみ**（音は従来通り）。`VoiceDesignBackend` がキャッシュ＋ref合成を担当。
- pydantic は余剰フィールドを無視（前方互換）。

## アプリ設計（main.py / irodori_engine.py）
- `irodori_engine.synthesize_irodori(session, base_url, text, caption, seed=None, use_ref=False, timeout=180)`: payload に `use_ref` を追加（True のときのみ含める）。
- **カテゴリ毎seed**: 設定 `caption_seeds: dict[str,int]`（キーは14カテゴリ名＋`"__narrator__"`）。既定は `caption_seed(カテゴリ名)`（安定）。取得ヘルパ `irodori_engine.voice_seed_for(category, seeds, default_fn)`。
- **🎲リロール**: 各役＋ナレーター行にボタン。押下→新ランダムseed（`irodori_engine.new_seed()`）→ `caption_seeds` 更新→保存。
- **声固定チェックボックス**: 設定 `irodori_use_ref: bool`（既定 True）。`self.use_ref_var`。トップバー付近。
- **producer（irodori時）**: `caption=resolve_caption(cat, _caption_map, _narr_caption)`、`seed=voice_seed_for(cat, _seeds, ...)`、`use_ref=_use_ref` を送信。スナップショットは再生開始時に取得（スレッド安全、2aと同様）。

## データフロー / レイテンシ
```
再生 → 各チャンク(category) → /synthesize {text, caption, seed=カテゴリseed, use_ref}
  サーバ: (caption,seed) 初回のみ基準音声生成(+数秒)→キャッシュ／以降refクローンで即合成
  → WAV → 24kリサンプル(2aの_resample_linear) → 再生
🎲リロール → seed変更 → 次回再生で新しい基準音声
```

## 後方互換・配布
- `use_ref` 無し＝2aと完全同一。`FakeBackend` は `use_ref` 無視で既存テスト不変。
- サーバ改修のため配布バンドル `irodori-vd-runtime` の `vd_server` を再コピー（`build_vd_bundle.ps1` の非editableコピー手順に含まれる／devは editable のクローン側を直接編集）。

## テスト方針（核心ユニット＋手動E2E）
- サーバ: `/synthesize` が `use_ref` を backend へ渡す（FakeBackend記録）／`VoiceDesignBackend` のrefキャッシュは同 `(caption,seed)` で基準を**1回だけ生成**し再利用（runtimeモックで呼数検証）／`use_ref=False` でref生成を呼ばない。
- アプリ: `synthesize_irodori(use_ref=True)` の payload に `use_ref`／`voice_seed_for`・`new_seed`・既定seed のロジック。
- E2E（GPU・手動）: 声固定ONで同カテゴリ一貫・カテゴリ毎別声・🎲で変化・OFFで2a挙動。

## 受け入れ基準
1. 声固定ONで同カテゴリ（特にナレーション）が最後まで同じ声。
2. カテゴリ毎に別の固定声。
3. 🎲リロールで声が変わり設定保存。
4. 声固定OFFは2aと同一。
5. 初回の基準生成レイテンシ以外、追加コストなし。
