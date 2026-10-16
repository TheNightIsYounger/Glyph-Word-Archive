"""Explicit per-user launcher/shortcut integration; never copy the image out."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from paths import APP_ID, APP_ROOT, ASSET_DIR, CONFIG_DIR, DATA_DIR


def install(niri=False, niri_config=None, uninstall=False):
    image = Path(os.environ.get("APPIMAGE", ""))
    if not image.is_absolute() or not image.is_file():
        raise RuntimeError("请从保存好的 AppImage 文件执行安装；不要移动已安装的文件。")
    binary = Path.home() / ".local/bin/glyph"
    desktop = DATA_DIR.parent / "applications" / f"{APP_ID}.desktop"
    icon = DATA_DIR.parent / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    command = "#!/bin/sh\n# Glyph AppImage integration\nexec " + shlex.quote(str(image)) + ' "$@"\n'
    if uninstall:
        # Use the original installer's include-removal logic, without moving or
        # deleting any source installation or the user's AppImage/personal data.
        integration = CONFIG_DIR / "hotkeys.json"
        if integration.exists():
            import json
            from hotkeys import kdl_string
            metadata = json.loads(integration.read_text())
            root = Path(metadata["config"]); bindings = CONFIG_DIR / "niri-bindings.kdl"
            if root.exists():
                line = f"include optional=true {kdl_string(bindings)}"
                rows = root.read_text().splitlines()
                root.write_text("\n".join(row for row in rows if row not in (line, "// Glyph managed shortcut include")) + "\n")
            bindings.unlink(missing_ok=True); integration.unlink()
        if binary.is_file() and binary.read_text() == command: binary.unlink()
        if desktop.is_file() and "X-Glyph-AppImage=true" in desktop.read_text():
            desktop.unlink(); icon.unlink(missing_ok=True)
        return "已移除 Glyph 启动入口和快捷键集成；AppImage、词库和网页数据保留。"
    # Validate the explicit compositor integration before changing launch entries.
    if niri:
        sys.path.insert(0, str(APP_ROOT))
        from install import niri_integration
        niri_integration(CONFIG_DIR.parent, Path(niri_config) if niri_config else CONFIG_DIR.parent / "niri/config.kdl")
    binary.parent.mkdir(parents=True, exist_ok=True)
    if binary.exists() and binary.read_text() != command:
        backup = binary.with_name("glyph.before-appimage")
        if backup.exists(): raise RuntimeError(f"已有启动器备份，请先处理：{backup}")
        shutil.copy2(binary, backup)
    binary.write_text(command); binary.chmod(0o755)
    icon.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ASSET_DIR / "glyph.svg", icon)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(image).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    desktop.write_text(f'[Desktop Entry]\nType=Application\nName=Glyph\nExec="{escaped}"\nIcon={APP_ID}\nTerminal=false\nCategories=Education;Languages;\nKeywords=Vocabulary;English;Dictionary;生词本;词典;\nX-Glyph-AppImage=true\n')
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(desktop.parent)], check=False)
    return "已安装 Glyph 启动入口。请保留 AppImage 在当前位置；移动后需重新安装入口。"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--niri", action="store_true")
    parser.add_argument("--niri-config")
    args = parser.parse_args()
    try: print(install(args.niri, args.niri_config, args.uninstall))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: parser.exit(1, f"集成失败：{error}\n")
