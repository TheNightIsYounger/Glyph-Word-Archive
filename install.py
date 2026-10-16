#!/usr/bin/env python3
"""Per-user installation, with an explicit opt-in niri integration."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app"))
from paths import APP_ID
from hotkeys import kdl_string, idle_config


def paths(home=None):
    home = Path(home or Path.home())
    return (Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")),
            Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")),
            home / ".local/bin")


def niri_integration(config_home, root_config):
    root_config = root_config.expanduser().resolve()
    if not root_config.is_file():
        raise RuntimeError(f"niri 配置不存在：{root_config}")
    previous = root_config.read_text()
    bindings = config_home / "glyph/niri-bindings.kdl"
    marker = "// Glyph managed shortcut include"
    line = f"include optional=true {kdl_string(bindings)}"
    if line not in previous:
        changed = previous.rstrip() + f"\n\n{marker}\n{line}\n"
        # Validate a sibling file so relative includes keep their meaning.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kdl", dir=root_config.parent, delete=False) as temporary:
            temporary.write(changed)
            candidate = Path(temporary.name)
        try:
            result = subprocess.run(["niri", "validate", "--config", str(candidate)], capture_output=True, text=True)
            if result.returncode: raise RuntimeError("新增 include 未通过 niri 校验，配置没有修改")
            backup = root_config.with_name(root_config.name + ".before-glyph")
            if not backup.exists(): shutil.copy2(root_config, backup)
            root_config.write_text(changed)
        finally:
            candidate.unlink(missing_ok=True)
    bindings.parent.mkdir(parents=True, exist_ok=True)
    if not bindings.exists(): bindings.write_text(idle_config())
    (bindings.parent / "hotkeys.json").write_text(json.dumps({"backend": "niri", "config": str(root_config)}, indent=2))


def install(args):
    data, config, binary = paths(args.home)
    destination = data / "glyph/application"
    if args.uninstall:
        remove_installation(data, config, binary, destination)
        return
    if destination.resolve() == ROOT:
        raise RuntimeError("请从下载解压后的目录运行安装器，而非已安装目录")
    # Copy only application resources; never copy a developer's personal data.
    destination.mkdir(parents=True, exist_ok=True)
    for folder in ("app", "assets", "bin", "licenses", "scripts"):
        shutil.copytree(ROOT / folder, destination / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "requirements.txt", "install.py"):
        shutil.copy2(ROOT / name, destination / name)
    dictionary_target = destination / "dictionaries"
    dictionary_target.mkdir(exist_ok=True)
    for name in ("dictionary.db", "wordnet.db", "manifest.json"):
        source = ROOT / "dictionaries" / name
        if source.exists(): shutil.copy2(source, dictionary_target / name)
    binary.mkdir(parents=True, exist_ok=True)
    launcher = binary / "glyph"
    if launcher.exists() and not launcher.is_symlink():
        # Preserve an unrelated executable before replacing the entry point.
        shutil.copy2(launcher, launcher.with_name("glyph.before-install"))
    launcher.unlink(missing_ok=True)
    # The shell launcher derives the app root from its location; use a wrapper,
    # rather than a symlink whose dirname would point to ~/.local/bin.
    import shlex
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(str(destination / "bin/glyph")) + ' "$@"\n')
    launcher.chmod(0o755)
    for path in (destination / "bin").iterdir(): path.chmod(0o755)
    # Keep the interpreter used for installation (including virtualenvs).
    for entry, module in (("glyph", "main_qt.py"), ("capture-word", "capture.py"), ("ocr-word", "ocr_capture.py")):
        executable = destination / "bin" / entry
        executable.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(destination / "app" / module)) + ' "$@"\n')
        executable.chmod(0o755)
    icon = data / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    icon.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / "assets/glyph.svg", icon)
    desktop = data / "applications" / f"{APP_ID}.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    escaped_exec = str(destination / "bin/glyph").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    desktop.write_text(f'[Desktop Entry]\nType=Application\nName=Glyph\nComment=Local-first vocabulary notebook\nExec="{escaped_exec}"\nIcon={APP_ID}\nTerminal=false\nCategories=Education;Languages;\nKeywords=Vocabulary;Dictionary;English;单词;词典;生词本;\nStartupNotify=true\n')
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(desktop.parent)], check=False)
    if args.niri:
        niri_integration(config, Path(args.niri_config) if args.niri_config else config / "niri/config.kdl")
    print(f"Glyph 已安装：{destination}\n启动：{launcher}\n个人词库和浏览数据不会随升级或卸载删除。")


def remove_installation(data, config, binary, destination):
    integration = config / "glyph/hotkeys.json"
    if integration.exists():
        metadata = json.loads(integration.read_text())
        root_config = Path(metadata["config"])
        bindings = config / "glyph/niri-bindings.kdl"
        if root_config.exists():
            line = f"include optional=true {kdl_string(bindings)}"
            original = root_config.read_text()
            root_config.write_text("\n".join(row for row in original.splitlines() if row not in (line, "// Glyph managed shortcut include")) + "\n")
        bindings.unlink(missing_ok=True); integration.unlink()
    wrapper = binary / "glyph"
    if wrapper.is_file() and str(destination / "bin/glyph") in wrapper.read_text(): wrapper.unlink()
    (data / "applications" / f"{APP_ID}.desktop").unlink(missing_ok=True)
    (data / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg").unlink(missing_ok=True)
    if destination.is_dir():
        trash = data / "glyph" / "uninstalled-application"
        if trash.exists(): raise RuntimeError(f"已有可恢复卸载副本，请先处理：{trash}")
        destination.rename(trash)
    print("已移除启动入口和 Glyph 快捷键 include。应用文件移至 uninstalled-application，可恢复；个人数据保留。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--niri", action="store_true", help="明确启用 niri 全局快捷键集成")
    parser.add_argument("--niri-config", help="非默认 niri 配置位置")
    parser.add_argument("--home", type=Path, help="测试或自定义用户安装根目录")
    parser.add_argument("--uninstall", action="store_true")
    options = parser.parse_args()
    try: install(options)
    except (OSError, ValueError, RuntimeError) as error: parser.exit(1, f"安装失败：{error}\n")
