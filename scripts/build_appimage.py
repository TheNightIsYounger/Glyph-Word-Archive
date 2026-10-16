#!/usr/bin/env python3
"""Build on Ubuntu 24.04 amd64, using verified wheels and a type-2 runtime.

Native dependencies must already exist in the build sysroot. This script never
copies the build user's home, application settings, browser profile or word DB.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
APPDIR = BUILD / "Glyph.AppDir"
VERSION = "0.1.0"
PYQT_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtPrintSupport"}
PLUGIN_DIRS = {"platforms", "platforminputcontexts", "imageformats", "iconengines", "tls", "styles", "wayland-decoration-client", "wayland-graphics-integration-client", "wayland-shell-integration"}
# Host graphics dispatch/drivers and glibc must remain host-provided. Do not
# replace these with libraries from the build machine.
SYSTEM_LIBS = re.compile(r"^(?:ld-linux.*|lib(?:c|m|pthread|dl|rt|resolv|util|anl)\.so\..*|lib(?:GL|GLX|EGL|OpenGL|GLdispatch|gbm|drm|vulkan)\.so\..*|lib(?:glib-2\.0|gobject-2\.0|gio-2\.0|gmodule-2\.0|stdc\+\+|gcc_s|fontconfig|freetype|harfbuzz|wayland-client|wayland-cursor|wayland-egl)\.so\..*)$")


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=True)


def elf(path):
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except (OSError, IsADirectoryError):
        return False


def stage(dictionary_dir):
    if APPDIR.exists():
        # Only a fixed, internally chosen build artifact is replaced.
        shutil.rmtree(APPDIR)
    APPDIR.mkdir(parents=True)
    for folder in ("app", "assets", "licenses"):
        shutil.copytree(ROOT / folder, APPDIR / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("LICENSE", "README.md", "APPIMAGE.md", "THIRD_PARTY_NOTICES.md", "install.py"):
        copy(ROOT / name, APPDIR / name)
    copy(ROOT / "scripts/AppRun", APPDIR / "AppRun"); (APPDIR / "AppRun").chmod(0o755)
    copy(ROOT / "assets/glyph.svg", APPDIR / "local.glyph.Glyph.svg")
    (APPDIR / ".DirIcon").symlink_to("local.glyph.Glyph.svg")
    (APPDIR / "local.glyph.Glyph.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Glyph\nExec=AppRun\nIcon=local.glyph.Glyph\n"
        "Comment=Local-first vocabulary notebook\nTerminal=false\nCategories=Education;Languages;\n")
    # Read only the two specifically validated dictionary snapshots.
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_release import archive
    import tempfile
    with tempfile.TemporaryDirectory(prefix="glyph-dictionary-stage-") as temporary:
        bundle = archive(dictionary_dir, temporary)
        with tarfile.open(bundle) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if len(parts) == 3 and parts[1] == "dictionaries" and member.isfile():
                    target = APPDIR / "dictionaries" / parts[-1]
                    target.parent.mkdir(exist_ok=True)
                    with tar.extractfile(member) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out)
    stdlib = Path(sysconfig.get_path("stdlib"))
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use the documented Ubuntu 24.04 Python 3.12 build environment")
    copy(Path("/usr/bin/python3.12"), APPDIR / "usr/bin/python3.12")
    (APPDIR / "usr/bin/python3").symlink_to("python3.12")
    shutil.copytree(stdlib, APPDIR / "usr/lib/python3.12", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "site-packages", "dist-packages"))
    wheel_dir = BUILD / "downloads/wheels"
    lock = json.loads((ROOT / "scripts/appimage-lock.json").read_text())
    wheels = []
    for item in lock["wheels"]:
        wheel = wheel_dir / item["file"]
        if sha(wheel) != item["sha256"]: raise RuntimeError(f"Unverified wheel: {wheel.name}")
        wheels.append(wheel)
    run(sys.executable, "-m", "pip", "install", "--no-index", "--no-compile", "--find-links", wheel_dir,
        "--no-deps", "--target", APPDIR / "usr/lib/python3.12/site-packages", *wheels)
    site = APPDIR / "usr/lib/python3.12/site-packages"
    pyqt = site / "PyQt6"
    qt = pyqt / "Qt6"
    for item in list(pyqt.iterdir()):
        if (item.name.startswith("Qt") and item.name != "Qt6" and item.name.split(".")[0] not in PYQT_MODULES) or item.name in {"uic", "lupdate", "bindings"}:
            if item.is_dir(): shutil.rmtree(item)
            else: item.unlink()
    for item in (qt / "plugins").iterdir():
        if item.is_dir() and item.name not in PLUGIN_DIRS: shutil.rmtree(item)
    for item in (qt / "translations").rglob("*"):
        if item.is_file() and not re.search(r"(?:en(?:[-_]US)?|zh[-_]CN|zh[-_]TW)\.(?:qm|pak)$", item.name): item.unlink()
    for name in ("qml", "include", "mkspecs", "bin"):
        if (qt / name).is_dir(): shutil.rmtree(qt / name)
    for helper in ("grim", "slurp", "wl-paste", "tesseract", "notify-send"):
        copy(Path(shutil.which(helper)), APPDIR / "usr/bin" / helper)
    # NSS dlopens these modules, so ldd alone cannot discover them.
    for name in ("libnssckbi.so", "libsoftokn3.so", "libfreebl3.so", "libfreeblpriv3.so"):
        copy(Path("/usr/lib/x86_64-linux-gnu") / name, APPDIR / "usr/lib" / name)
    copy(Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata"), APPDIR / "usr/share/tessdata/eng.traineddata")
    # Use Ubuntu's CA roots; personal/system-local CA additions are not copied.
    certs = sorted(Path("/usr/share/ca-certificates/mozilla").glob("*.crt"))
    if not certs: raise RuntimeError("Missing distro Mozilla certificate roots")
    target = APPDIR / "usr/share/glyph/ca-certificates.crt"; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\n".join(p.read_bytes() for p in certs))
    closure(qt)
    notices(site)
    print(f"Staged {APPDIR}", flush=True)


def closure(qt):
    central = APPDIR / "usr/lib"; qtlib = qt / "lib"
    copied = {}
    scan = [p for p in APPDIR.rglob("*") if p.is_file() and elf(p) and qtlib not in p.parents]
    # WebEngineProcess is outside lib; it brings in all browser/Qt dependencies.
    seen = set()
    while scan:
        path = scan.pop().resolve()
        if path in seen: continue
        seen.add(path)
        # ldd resolves wheel RUNPATH first and remaining libs inside this sysroot.
        result = subprocess.run(["ldd", str(path)], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "=> not found" in line: raise RuntimeError(f"Unresolved dependency {path}: {line}")
            match = re.match(r"\s*(\S+) => (/\S+)", line)
            if not match: continue
            soname, source = match.groups(); source = Path(source).resolve()
            if SYSTEM_LIBS.match(soname): continue
            if APPDIR in source.parents:
                scan.append(source)
            else:
                target = central / soname
                if not target.exists(): copy(source, target)
                copied[soname] = str(source)
                scan.append(target)
    # The wheel includes unrelated Qt components: keep only the ELF closure.
    for item in qtlib.iterdir():
        if item.is_file() and item not in seen: item.unlink()
    for path in seen:
        relative = os.path.relpath(central, path.parent)
        qt_relative = os.path.relpath(qtlib, path.parent)
        run("patchelf", "--set-rpath", f"$ORIGIN/{qt_relative}:$ORIGIN/{relative}", path)
    (APPDIR / "usr/share/glyph/native-libraries.json").write_text(json.dumps(copied, indent=2) + "\n")


def notices(site):
    target = APPDIR / "licenses/runtime"; target.mkdir(parents=True, exist_ok=True)
    preserved = BUILD / "upstream-notices"
    if preserved.exists(): shutil.copytree(preserved, target / "upstream", dirs_exist_ok=True)
    source_manifest = ROOT / "dist/Glyph-0.1.0-dependency-sources/SOURCE-MANIFEST.json"
    if source_manifest.exists(): copy(source_manifest, APPDIR / "usr/share/glyph/SOURCE-MANIFEST.json")
    # All Ubuntu copyright files are small and include transitive-library notices.
    # Save the associated package metadata for exact source reconstruction.
    for path in Path("/usr/share/doc").glob("*/copyright"):
        if path.is_file(): copy(path, target / "ubuntu" / (path.parent.name + ".txt"))
    if Path("/usr/share/common-licenses").exists():
        shutil.copytree("/usr/share/common-licenses", target / "common-licenses", dirs_exist_ok=True)
    records = []
    for wheel in sorted((BUILD / "downloads/wheels").glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            record = {"wheel": wheel.name, "sha256": sha(wheel)}
            for line in archive.read(metadata).decode().splitlines():
                if line.startswith(("Name: ", "Version: ")):
                    key, value = line.split(": ", 1); record[key.lower()] = value
            records.append(record)
            for name in archive.namelist():
                if ".dist-info/" in name and re.search(r"(?i)(license|copying|notice)", name) and not name.endswith("/"):
                    dest = target / "wheels" / wheel.stem / Path(name).name
                    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(archive.read(name))
    debs = []
    for package in sorted(Path("/var/cache/apt/archives").glob("*.deb")):
        fields = run("dpkg-deb", "-f", package, "Package", "Version", "Source", capture_output=True, text=True).stdout
        debs.append({"deb": package.name, "sha256": sha(package), "metadata": fields})
    manifest = {"build_base": "Ubuntu 24.04 amd64; glibc >= 2.39", "python": sys.version,
                "python_wheels": records, "ubuntu_packages": debs,
                "host_provided": "glibc, libstdc++/libgcc, GLib, font libraries, Wayland client libs, graphics dispatch/drivers, compositor/session, fonts",
                "runtime_sha256": sha(BUILD / "downloads/runtime-x86_64")}
    (APPDIR / "usr/share/glyph/bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def image():
    runtime = BUILD / "downloads/runtime-x86_64"
    expected = "156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074"
    if sha(runtime) != expected: raise RuntimeError("Unrecognized AppImage runtime")
    squash = BUILD / "glyph.squashfs"
    run("mksquashfs", APPDIR, squash, "-noappend", "-comp", "zstd", "-Xcompression-level", "15", "-b", "1M", "-all-root", "-no-xattrs", "-processors", "2")
    destination = ROOT / "dist" / f"Glyph-{VERSION}-x86_64.AppImage"
    destination.parent.mkdir(exist_ok=True)
    with destination.open("wb") as stream:
        for part in (runtime, squash):
            with part.open("rb") as source: shutil.copyfileobj(source, stream)
    destination.chmod(0o755)
    destination.with_suffix(".AppImage.sha256").write_text(f"{sha(destination)}  {destination.name}\n")
    print(f"{destination.name}: {destination.stat().st_size / 1024**2:.1f} MiB; SHA256 {sha(destination)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary-dir", type=Path)
    parser.add_argument("--image-only", action="store_true")
    args = parser.parse_args()
    if not args.image_only:
        if not args.dictionary_dir: parser.error("--dictionary-dir is required")
        stage(args.dictionary_dir)
    image()
