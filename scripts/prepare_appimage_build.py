#!/usr/bin/env python3
"""Prepare a disposable, signed-APT Ubuntu build root; no host package install."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
BASE_NAME = "ubuntu-base-24.04.4-base-amd64.tar.gz"
BASE_SHA = "c1e67ef7b17a6300e136118bd1dc04725009cb376c1aad10abcf8cd453628d58"
PACKAGES = "python3 python3-venv python3-pip ca-certificates grim slurp wl-clipboard tesseract-ocr tesseract-ocr-eng libnotify-bin libnss3 libnspr4 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-randr0 libxcb-render-util0 libasound2t64 libegl1 libopengl0 libgl1 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxshmfence1 libxi6 libdrm2 libgbm1 libfontconfig1 libdbus-1-3 libglib2.0-0t64 libxss1 libwayland-client0 libwayland-cursor0 libwayland-egl1 libpulse0 libgssapi-krb5-2 libx11-xcb1 libxfixes3 libxkbfile1 libxt6t64 libatk1.0-0t64 libatk-bridge2.0-0t64 squashfs-tools patchelf curl binutils fonts-dejavu-core".split()


def run(*command, **kwargs):
    subprocess.run([str(p) for p in command], check=True, **kwargs)


def inside(*command):
    run("sh", ROOT / "scripts/in_appimage_build_env.sh", *command)


def fetch(url, path, expected):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
        temporary.replace(path)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected: raise RuntimeError(f"Checksum mismatch: {path.name}")


def main():
    if not shutil.which("bwrap"): raise RuntimeError("Bubblewrap is required on the build host")
    # dpkg-deb/dpkg are available inside Ubuntu; allow their isolated use when
    # the host is Arch rather than Debian.
    downloads = BUILD / "downloads"; downloads.mkdir(parents=True, exist_ok=True)
    base = downloads / BASE_NAME
    fetch("https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/" + BASE_NAME, base, BASE_SHA)
    sysroot = BUILD / "rootfs"; sysroot.mkdir(exist_ok=True)
    if not (sysroot / "usr/bin/apt-get").exists(): run("tar", "--no-same-owner", "-xzf", base, "-C", sysroot)
    sources = sysroot / "etc/apt/sources.list.d/glyph-sources.sources"
    sources.write_text("Types: deb-src\nURIs: http://archive.ubuntu.com/ubuntu/\nSuites: noble noble-updates\nComponents: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\nTypes: deb-src\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: noble-security\nComponents: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n")
    inside("apt-get", "-o", "APT::Sandbox::User=root", "update")
    inside("apt-get", "-o", "APT::Sandbox::User=root", "--download-only", "install", "-y", "--no-install-recommends", *PACKAGES)
    inside("apt-get", "-o", "APT::Sandbox::User=root", "--download-only", "upgrade", "-y")
    # Run the deb selection/extraction helper inside its own sysroot.
    inside("/bin/sh", "-c", 'for package in /var/cache/apt/archives/*.deb; do case "$package" in */base-files_*) continue;; esac; dpkg-deb --fsys-tarfile "$package" | tar --no-same-owner -xf - -C /; done; python3 -m venv /opt/glyph-build')
    inside("python", "-c", "import sys;sys.path.insert(0,'/project/scripts');from prepare_appimage_build import extract_downloaded_debs_in_sysroot;extract_downloaded_debs_in_sysroot()")
    lock = json.loads((ROOT / "scripts/appimage-lock.json").read_text())
    for record in lock["wheels"]:
        fetch(record["url"], downloads / "wheels" / record["file"], record["sha256"])
    fetch(lock["runtime"]["url"], downloads / "runtime-x86_64", lock["runtime"]["sha256"])
    print("Build environment ready. Host packages/configuration were not changed.")


def extract_downloaded_debs_in_sysroot():
    archive = Path("/var/cache/apt/archives"); keep = {}
    superseded = Path("/project/.build/downloads/superseded-debs")
    for deb in sorted(archive.glob("*.deb")):
        output = subprocess.check_output(["dpkg-deb", "-f", str(deb), "Package", "Version"], text=True)
        fields = dict(line.split(": ", 1) for line in output.splitlines())
        name, version = fields["Package"], fields["Version"]
        if name in keep:
            prior, prior_version = keep[name]
            newer = subprocess.run(["dpkg", "--compare-versions", version, "gt", prior_version]).returncode == 0
            old = prior if newer else deb
            superseded.mkdir(parents=True, exist_ok=True); shutil.move(old, superseded / old.name)
            if not newer: continue
        keep[name] = (deb, version)
    run("/bin/sh", "-c", 'for package in /var/cache/apt/archives/*.deb; do case "$package" in */base-files_*) continue;; esac; dpkg-deb --fsys-tarfile "$package" | tar --no-same-owner -xf - -C /; done')


if __name__ == "__main__": main()
