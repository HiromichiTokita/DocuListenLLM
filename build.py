"""
DocuListen ビルドスクリプト

実行方法:
  python build.py

出力:
  dist/DocuListen_Release/DocuListen.exe   実行ファイル
  dist/DocuListen_Release/engine/          VOICEVOXエンジン一式
  dist/DocuListen_Release/settings.json    ユーザー設定 (存在する場合)
"""
import glob
import os
import re as _re
import pathlib as _pathlib
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 各パッケージのアセットパスを動的に取得
import customtkinter
import pedalboard
ctk_path = os.path.dirname(customtkinter.__file__)
pb_path  = os.path.dirname(pedalboard.__file__)

script_dir   = os.path.dirname(os.path.abspath(__file__))
engine_src   = os.path.join(script_dir, "engine")
settings_src = os.path.join(script_dir, "settings.json")
icon_path    = os.path.join(script_dir, "icon.ico")

APP_NAME    = "DocuListen"
_main_src = _pathlib.Path(os.path.join(script_dir, "main.py")).read_text(encoding="utf-8")
VERSION   = _re.search(r'^APP_VERSION\s*=\s*["\'](.+)["\']', _main_src, _re.M).group(1)
RELEASE_DIR = os.path.join("dist", f"{APP_NAME}_{VERSION}")

# ─── 1. 古いビルドデータを削除する ──────────────────────────────
print("🧹 古いビルドデータを削除中...")

for artifact in ("build", "dist"):
    try:
        if os.path.isdir(artifact):
            shutil.rmtree(artifact)
            print(f"   削除: {artifact}/")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"   警告: {artifact} の削除に失敗しました — {exc}")

for spec_file in glob.glob(os.path.join(script_dir, "*.spec")):
    try:
        os.remove(spec_file)
        print(f"   削除: {os.path.basename(spec_file)}")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"   警告: {spec_file} の削除に失敗しました — {exc}")

# ─── 2. PyInstaller でビルドする ─────────────────────────────────
print()
print(f"🔨 {APP_NAME}.exe をビルド中 (数分かかります)...")

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconsole",
    "--onefile",
    f"--name={APP_NAME}",
    f"--add-data={ctk_path};customtkinter",
    "--collect-all", "pedalboard",
    "--hidden-import", "sounddevice",
    "--hidden-import", "soundfile",
    "--hidden-import", "cffi",
    "--hidden-import", "_sounddevice_data",
]

# icon.ico が存在する場合のみ --icon フラグを追加する
if os.path.isfile(icon_path):
    cmd.append(f"--icon={icon_path}")
else:
    print(f"   情報: icon.ico が見つかりません。デフォルトアイコンでビルドします。")

cmd.append("main.py")

print(f"   コマンド: {' '.join(cmd)}")
print()

result = subprocess.run(cmd, cwd=script_dir, check=False)

if result.returncode != 0:
    print()
    print(f"❌ ビルド失敗 (終了コード: {result.returncode})")
    sys.exit(result.returncode)

print()

# ─── 3. 配布用フォルダを作成する ─────────────────────────────────
print("📦 配布用フォルダを作成中...")

# dist/DocuListen_Release/ を作成する
if os.path.isdir(RELEASE_DIR):
    shutil.rmtree(RELEASE_DIR)
os.makedirs(RELEASE_DIR)
print(f"   作成: {RELEASE_DIR}/")

# dist/DocuListen.exe → dist/DocuListen_Release/DocuListen.exe
exe_src = os.path.join("dist", f"{APP_NAME}.exe")
exe_dst = os.path.join(RELEASE_DIR, f"{APP_NAME}.exe")
shutil.move(exe_src, exe_dst)
print(f"   移動: {APP_NAME}.exe → {exe_dst}")

# engine/ → dist/DocuListen_Release/engine/
engine_dst = os.path.join(RELEASE_DIR, "engine")
if os.path.isdir(engine_src):
    shutil.copytree(engine_src, engine_dst)
    print(f"   コピー: engine/ → {engine_dst}/")
else:
    print(f"   警告: engine フォルダが見つかりません ({engine_src})")
    print(f"         engine フォルダを手動で {RELEASE_DIR}/ に配置してください。")

# settings.json → dist/DocuListen_Release/settings.json (存在する場合のみ)
settings_dst = os.path.join(RELEASE_DIR, "settings.json")
if os.path.isfile(settings_src):
    shutil.copy2(settings_src, settings_dst)
    print(f"   コピー: settings.json → {settings_dst}")
else:
    print(f"   情報: settings.json が見つかりません。スキップします。")

# ─── 4. 完了メッセージ ───────────────────────────────────────────
print()
print(f"✨ ビルド完了！ dist/{APP_NAME}_{VERSION} を確認してください。")
print()
print(f"   配布フォルダ: {os.path.abspath(RELEASE_DIR)}")
print(f"   ├─ {APP_NAME}.exe")
if os.path.isdir(engine_dst):
    print(f"   ├─ engine/")
if os.path.isfile(settings_dst):
    print(f"   └─ settings.json")
