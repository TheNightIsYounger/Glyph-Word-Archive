#!/usr/bin/env python3
"""Collect corresponding upstream/distro sources separately from the user app.

Run in the documented Ubuntu build environment after staging the AppDir. The
result is a companion source download, not a runtime dependency of the app.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "dist/Glyph-0.1.0-dependency-sources"
NOTICE = ROOT / ".build/Glyph.AppDir/licenses/runtime/upstream"
CONTEXT = ssl.create_default_context(cafile="/opt/glyph-build/lib/python3.12/site-packages/pip/_vendor/certifi/cacert.pem")


def read(url):
    with urllib.request.urlopen(url, timeout=90, context=CONTEXT) as response: return response.read()


def digest(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def verified(path, expected):
    if not expected: return True
    algorithm, value = expected.split(":", 1) if ":" in expected else ("sha256", expected)
    algorithm = {"MD5Sum": "md5"}.get(algorithm, algorithm.lower())
    if algorithm not in {"sha256", "sha512", "md5"}: raise ValueError(algorithm)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest() == value


def download(item):
    url, name, expected = item
    target = TARGET / name
    if not target.exists() or not verified(target, expected) or (".tar." in name and not name.endswith(".asc") and not tarfile.is_tarfile(target)):
        partial = target.with_name(target.name + ".part")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=120, context=CONTEXT) as response, partial.open("wb") as stream:
                    while block := response.read(1024 * 1024): stream.write(block)
                if not verified(partial, expected): raise RuntimeError(f"Checksum mismatch: {name}")
                if ".tar." in name and not name.endswith(".asc") and not tarfile.is_tarfile(partial): raise RuntimeError(f"Not a source archive: {name}")
                partial.replace(target); break
            except Exception:
                if attempt == 3: raise
                time.sleep(2)
    print(f"SOURCE {name} ({target.stat().st_size // 1024**2} MiB)", flush=True)
    return {"file": name, "url": url, "sha256": digest(target)}


def qt_and_python():
    tasks = []
    base = "https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/"
    for module in ("qtbase", "qtdeclarative", "qtwebengine", "qtwebchannel", "qtwayland", "qtsvg", "qtpositioning", "qtshadertools"):
        name = module + "-everywhere-src-6.11.2.tar.xz"
        expected = read(base + name + ".sha256").decode().split()[0]
        tasks.append((base + name, name, expected))
    for package, version in (("PyQt6", "6.11.0"), ("PyQt6-WebEngine", "6.11.0"), ("PyQt6-sip", "13.13.0")):
        meta = json.loads(read(f"https://pypi.org/pypi/{package}/{version}/json"))
        source = next(item for item in meta["urls"] if item["packagetype"] == "sdist")
        tasks.append((source["url"], source["filename"], source["digests"]["sha256"]))
    commit = "8f39b89e2ac31e1640b3d3f7e9a5108e6ce805fa"
    tasks.append((f"https://codeload.github.com/AppImage/type2-runtime/tar.gz/{commit}", "AppImage-type2-runtime-" + commit + ".tar.gz", None))
    tasks.extend([
        ("https://github.com/libfuse/libfuse/releases/download/fuse-3.15.0/fuse-3.15.0.tar.xz", "fuse-3.15.0.tar.xz", "70589cfd5e1cff7ccd6ac91c86c01be340b227285c5e200baa284e401eea2ca0"),
        ("https://github.com/vasi/squashfuse/archive/0.5.2.tar.gz", "squashfuse-0.5.2.tar.gz", "db0238c5981dabbd80ee09ae15387f390091668ca060a7bc38047912491443d3"),
        ("https://musl.libc.org/releases/musl-1.2.5.tar.gz", "musl-1.2.5.tar.gz", None),
        ("https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-1.5.6.tar.gz", "zstd-1.5.6.tar.gz", None),
        ("https://github.com/madler/zlib/archive/refs/tags/v1.3.2.tar.gz", "zlib-1.3.2.tar.gz", None),
        ("https://github.com/microsoft/mimalloc/archive/refs/tags/v2.1.7.tar.gz", "mimalloc-2.1.7.tar.gz", None),
        ("https://github.com/unicode-org/icu/releases/download/release-73-2/icu4c-73_2-src.tgz", "icu4c-73_2-src.tgz", None),
    ])
    return tasks


def distro_sources():
    native = json.loads((ROOT / ".build/Glyph.AppDir/usr/share/glyph/native-libraries.json").read_text())
    needed = {str(Path(p).resolve()) for p in native.values()}
    needed.update(str(Path("/usr/bin" + "/" + name).resolve()) for name in ("python3.12", "grim", "slurp", "wl-paste", "tesseract", "notify-send"))
    needed.update(str(Path("/usr/lib/x86_64-linux-gnu") / name) for name in ("libnssckbi.so", "libsoftokn3.so", "libfreebl3.so", "libfreeblpriv3.so"))
    needed.update(("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata", "/usr/share/ca-certificates/mozilla/ISRG_Root_X1.crt"))
    packages = {}
    # Original base-image packages do not have a downloaded .deb. Their file
    # lists and control metadata remain in the sysroot's dpkg database.
    for info in Path("/var/lib/dpkg/info").glob("*.list"):
        paths = info.read_text(errors="replace").splitlines()
        if any(str(Path(p).resolve()) in needed for p in paths if p.startswith("/")):
            package = info.name.removesuffix(".list")
            result = subprocess.run(["dpkg-query", "-W", "-f=${source:Package} ${source:Version}", package], capture_output=True, text=True, check=True)
            source, version = result.stdout.split(); packages[source] = version
    for deb in Path("/var/cache/apt/archives").glob("*.deb"):
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(deb)], stdout=subprocess.PIPE)
        hit = False
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                path = "/" + member.name.removeprefix("./")
                if str(Path(path).resolve()) in needed or path.startswith("/usr/lib/python3.12/"): hit = True
        process.stdout.close()
        if process.wait(): raise RuntimeError(str(deb))
        if not hit: continue
        metadata = subprocess.check_output(["dpkg-deb", "-f", str(deb)], text=True)
        fields = dict(re.findall(r"^(Package|Source|Version): (.+)$", metadata, re.MULTILINE))
        source = fields.get("Source", fields["Package"])
        match = re.fullmatch(r"(\S+)(?: \((.+)\))?", source)
        name, version = match.groups(); packages[name] = version or fields["Version"]
    tasks = []
    query_directory = ROOT / ".build/source-query"
    query_directory.mkdir(parents=True, exist_ok=True)
    # APT verifies the signed Sources index; it then downloads .dsc, upstream
    # archives and Ubuntu patch/build files, rather than only upstream tarballs.
    for name, version in sorted(packages.items()):
        spec = f"{name}={version}"
        result = subprocess.run(["apt-get", "-o", "APT::Sandbox::User=root", "--print-uris", "--download-only", "source", spec], cwd=query_directory, capture_output=True, text=True)
        if result.returncode: raise RuntimeError(f"Source unavailable for {spec}: {result.stderr}")
        for url, filename, size, check in re.findall(r"^'([^']+)' (\S+) (\d+) (\S+)$", result.stdout, re.MULTILINE):
            # Packages can share an upstream orig archive.
            tasks.append((url.replace("http://", "https://", 1), filename, check))
    return list({name: (url, name, check) for url, name, check in tasks}.values())


def extract_notices(records):
    for record in records:
        path = TARGET / record["file"]
        if not path.name.startswith(("qt", "pyqt", "AppImage", "fuse", "squashfuse", "musl", "zstd", "zlib", "mimalloc", "icu4c")): continue
        if not tarfile.is_tarfile(path): continue
        marker = NOTICE / (".complete-" + path.name)
        if marker.exists() and marker.read_text().strip() == record["sha256"]: continue
        with tarfile.open(path, "r|*") as archive:
            for member in archive:
                parts = Path(member.name).parts
                if not member.isfile() or member.size > 8 * 1024**2: continue
                if "LICENSES" in parts or re.fullmatch(r"(?i)(LICENSE|LICENCE|COPYING|COPYRIGHT|NOTICE)(?:[._-].*)?", parts[-1]):
                    # Preserve component directories so identically named
                    # Chromium LICENSE files never overwrite one another.
                    target = NOTICE / path.name / Path(*parts[1:])
                    if ".." in target.parts: raise RuntimeError(member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(record["sha256"] + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-only", action="store_true", help="Stage upstream sources before collecting distro sources")
    options = parser.parse_args()
    TARGET.mkdir(parents=True, exist_ok=True)
    tasks = qt_and_python() + ([] if options.qt_only else distro_sources())
    (TARGET / "download-plan.json").write_text(json.dumps(tasks, indent=2) + "\n")
    with ThreadPoolExecutor(max_workers=4) as workers:
        records = list(workers.map(download, tasks))
    (TARGET / "SOURCE-MANIFEST.json").write_text(json.dumps(records, indent=2) + "\n")
    extract_notices(records)
    print("Source and component-notice collection complete.", flush=True)
