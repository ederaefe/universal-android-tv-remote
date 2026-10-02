#!/usr/bin/env python3
"""Release Packaging Script for Universal Android TV & Projector Remote
Creates a clean, reproducible distribution zip containing all necessary
standalone files with SHA-256 checksum, excluding development artifacts.
"""

import hashlib
import os
import shutil
import zipfile

VERSION = "1.0.0"
DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RELEASE_FILES = [
    "index.html",
    "projector.py",
    "remote.sh",
    "remote.bat",
    "README.md",
    "LICENSE",
    "documentation.md",
    "assets/preview.png",
]


def create_release_bundle():
    os.makedirs(DIST_DIR, exist_ok=True)
    archive_name = f"universal-android-tv-remote-v{VERSION}.zip"
    archive_path = os.path.join(DIST_DIR, archive_name)

    print(f"[BUNDLE] Creating release bundle: {archive_name}")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for filename in RELEASE_FILES:
            src = os.path.join(ROOT_DIR, filename)
            if os.path.exists(src):
                zipf.write(src, arcname=filename)
                print(f"  + Added: {filename} ({os.path.getsize(src)} bytes)")
            else:
                print(f"  ! Missing warning: {filename}")

    # Calculate SHA-256 checksum
    hasher = hashlib.sha256()
    with open(archive_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()

    checksum_path = f"{archive_path}.sha256"
    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(f"{sha256}  {archive_name}\n")

    print("\n[SUCCESS] Release bundle created successfully!")
    print(f"  Archive  : {archive_path}")
    print(f"  Size     : {os.path.getsize(archive_path)} bytes")
    print(f"  SHA-256  : {sha256}")
    print(f"  Checksum : {checksum_path}")


if __name__ == "__main__":
    create_release_bundle()
