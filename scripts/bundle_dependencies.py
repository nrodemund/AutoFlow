"""Fetch pinned official PyPI Windows wheels, verify hashes and extract locally."""
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    ("openpyxl", "3.1.5", "py2.py3-none-any.whl"),
    ("et-xmlfile", "2.0.0", "py3-none-any.whl"),
    ("numpy", "2.2.6", "cp313-cp313-win_amd64.whl"),
    ("pillow", "12.1.0", "cp313-cp313-win_amd64.whl"),
    ("opencv-python-headless", "4.12.0.88", "cp37-abi3-win_amd64.whl"),
    ("typing-extensions", "4.15.0", "py3-none-any.whl"),
    *[(name, "3.2.1", "cp313-cp313-win_amd64.whl") for name in (
        "winrt-runtime", "winrt-Windows.Foundation", "winrt-Windows.Foundation.Collections",
        "winrt-Windows.Globalization", "winrt-Windows.Graphics.Imaging",
        "winrt-Windows.Storage.Streams", "winrt-Windows.Media.Ocr")],
]


def main():
    wheels = ROOT / "runtime/wheels"
    vendor = ROOT / "runtime/packages"
    wheels.mkdir(exist_ok=True)
    vendor.mkdir(exist_ok=True)
    manifest = []
    for name, version, tag in PACKAGES:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            release = json.load(response)
        item = next(f for f in release["urls"] if f["filename"].endswith(tag))
        target = wheels / item["filename"]
        if not target.exists():
            print("Downloading", item["filename"], flush=True)
            with urllib.request.urlopen(item["url"], timeout=120) as response:
                target.write_bytes(response.read())
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != item["digests"]["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {target.name}")
        with zipfile.ZipFile(target) as archive:
            for member in archive.infolist():
                destination = (vendor / member.filename).resolve()
                if not destination.is_relative_to(vendor.resolve()):
                    raise RuntimeError("Unsafe archive path")
                if not member.is_dir() and (not destination.exists() or destination.read_bytes() != archive.read(member)):
                    archive.extract(member, vendor)
        manifest.append(dict(package=name, version=version, file=item["filename"],
                             url=item["url"], sha256=digest))
        print("Verified and extracted", target.name, flush=True)
    (ROOT / "runtime/dependencies.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
