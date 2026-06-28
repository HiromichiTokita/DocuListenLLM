# DocuListen

どんな日本語テキストでも、ローカルで朗読できるデスクトップアプリです。

TXT / EPUB / PDF / DOCX を読み込んでボタン一つで再生。
インターネット不要・テキストの外部送信なし・完全ローカル動作。

---

## 主な機能

- **VOICEVOX** による日本語音声（45以上のキャラクター）
- 話速 0.5x〜3.0x（タイムストレッチ方式）
- 読んだ位置を自動記憶、次回起動時に続きから再生
- プレイリストによる複数ファイル連続自動再生
- ファイルのドラッグ＆ドロップ対応
- WAVファイルへの書き出し
- 青空文庫ルビ（`《よみ》` 形式）の自動かな変換
- 目次・不要テキストの自動スキップ
- **AI自動配役**（ローカルLLM / Ollama 使用、研究中機能）

---

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10 / 11（64bit） |
| Python | 3.14（`py` コマンド） |
| VOICEVOX エンジン | `engine/` フォルダに配置（別途取得が必要） |
| Ollama | AI配役を使う場合のみ必要（任意） |

> **注意：** `engine/` フォルダ（VOICEVOXエンジン一式、約2GB）はリポジトリに含まれていません。
> 別途準備してプロジェクトルートの `engine/` に配置してください。

---

## セットアップ

```bash
# 依存パッケージのインストール
py -m pip install -r requirements.txt

# 起動
py main.py
```

---

## ビルド（配布用 exe 作成）

```bash
py build.py
```

`dist/` フォルダに `DocuListen_vX.X.X/` が生成されます。

---

## フォルダ構成

```
DocuListenLLM/
├── main.py               # メインソース
├── irodori_engine.py     # IrodoriTTS エンジン連携モジュール
├── build.py              # ビルドスクリプト
├── requirements.txt      # 依存パッケージ
├── icon.ico              # アプリアイコン
├── CLAUDE.md             # AI開発支援向け指示
├── handoff.md            # 開発引継ぎ資料
├── docs/                 # ドキュメント
│   └── presentation_DocuListenLLM.md
├── tests/                # テストコード
└── engine/               # VOICEVOXエンジン（git管理外）
```

---

## 使用技術・クレジット

- **[VOICEVOX](https://voicevox.hiroshiba.jp/)** — 音声合成エンジン（無料・商用利用可、クレジット表記要）
- **[customtkinter](https://github.com/TomSchimansky/CustomTkinter)** — UI フレームワーク
- **[Ollama](https://ollama.ai/)** — ローカルLLM実行環境（AI配役機能）

---

## ライセンス・注意事項

- 本ソフトウェアのソースコードのライセンスは別途定めます。
- VOICEVOX を使用する場合は、キャラクターごとの利用規約を確認してください。
- AI配役機能はローカルLLMを使用するため、Ollama と対応モデルの別途インストールが必要です。
