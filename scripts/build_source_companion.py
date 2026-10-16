#!/usr/bin/env python3
"""Create a source companion containing only verified manifest-listed files."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def build():
    source = ROOT / "dist/Glyph-0.1.0-dependency-sources"
    records = json.loads((source / "SOURCE-MANIFEST.json").read_text())
    if len(records) < 100: raise RuntimeError("Incomplete source manifest; include distro sources")
    for record in records:
        name = record["file"]
        if Path(name).name != name or sha(source / name) != record["sha256"]:
            raise RuntimeError(f"Unverified source file: {name}")
    from build_release import archive
    application = archive()
    destination = ROOT / "dist/Glyph-0.1.0-corresponding-sources.tar"
    def public_metadata(member):
        member.uid = member.gid = 0; member.uname = member.gname = "root"
        return member
    with tarfile.open(destination, "w") as output:
        output.add(application, arcname=application.name, filter=public_metadata)
        output.add(ROOT / "APPIMAGE.md", arcname="BUILD-AND-USAGE.md", filter=public_metadata)
        output.add(ROOT / "THIRD_PARTY_NOTICES.md", arcname="THIRD_PARTY_NOTICES.md", filter=public_metadata)
        output.add(source / "SOURCE-MANIFEST.json", arcname="dependencies/SOURCE-MANIFEST.json", filter=public_metadata)
        for record in records:
            output.add(source / record["file"], arcname="dependencies/" + record["file"], filter=public_metadata)
    destination.with_suffix(".tar.sha256").write_text(f"{sha(destination)}  {destination.name}\n")
    print(f"{destination.name}: {destination.stat().st_size / 1024**2:.1f} MiB, {len(records)} verified source files")


if __name__ == "__main__": build()
