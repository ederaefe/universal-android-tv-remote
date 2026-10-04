import os
import sys
import urllib.request
import zipfile
import shutil

SCRCPY_URL = "https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-win64-v4.1.zip"
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(WORKSPACE_DIR, "bin", "scrcpy")
ZIP_PATH = os.path.join(WORKSPACE_DIR, "scrcpy-download.zip")

def main():
    print(f"[SCRCPY] Destination: {TARGET_DIR}")
    os.makedirs(TARGET_DIR, exist_ok=True)

    print(f"[SCRCPY] Downloading from {SCRCPY_URL}...")
    headers = {"User-Agent": "Universal-Remote-Installer"}
    req = urllib.request.Request(SCRCPY_URL, headers=headers)
    
    with urllib.request.urlopen(req) as resp, open(ZIP_PATH, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = (downloaded / total) * 100
                print(f"\r[SCRCPY] Progress: {downloaded / 1048576:.1f} MB / {total / 1048576:.1f} MB ({pct:.1f}%)", end="", flush=True)

    print("\n[SCRCPY] Download complete. Extracting...")
    temp_extract = os.path.join(WORKSPACE_DIR, "temp_scrcpy_extract")
    os.makedirs(temp_extract, exist_ok=True)

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(temp_extract)

    # Scrcpy zip usually contains a single top-level folder scrcpy-win64-vX.X
    subfolders = [os.path.join(temp_extract, d) for d in os.listdir(temp_extract) if os.path.isdir(os.path.join(temp_extract, d))]
    source_folder = subfolders[0] if subfolders else temp_extract

    for item in os.listdir(source_folder):
        s = os.path.join(source_folder, item)
        d = os.path.join(TARGET_DIR, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    # Cleanup temporary download files
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    shutil.rmtree(temp_extract, ignore_errors=True)

    print(f"[SCRCPY] Installation successful! Binaries in: {TARGET_DIR}")
    scrcpy_exe = os.path.join(TARGET_DIR, "scrcpy.exe")
    if os.path.exists(scrcpy_exe):
        print(f"[SCRCPY] Confirmed scrcpy.exe exists ({os.path.getsize(scrcpy_exe)} bytes).")
    else:
        print("[SCRCPY] Warning: scrcpy.exe not found at root of destination.")

if __name__ == "__main__":
    main()
