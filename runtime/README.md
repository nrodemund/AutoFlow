# Bundled Python runtime

This directory intentionally includes CPython 3.13.12 for Windows x64, both
the original archive and the extracted executable/DLL/standard-library files.
It requires no installer, administrator access, pip, or PATH changes.

Source: https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip

Release and published SHA-256: https://www.python.org/downloads/release/python-31312/

Archive SHA-256:
`76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0`

The archive digest matches the official release page; the extracted python.exe
has a valid Python Software Foundation Authenticode signature. Python's license
is included in `python/LICENSE.txt`. This is a pinned runtime, not an automatic
update mechanism. Review and update the pin deliberately for later releases.

The runtime configuration adds `..\..\` and `..\packages\` in
`python/python313._pth`, making the project and bundled dependencies importable.
Site initialization stays disabled. To restore, extract the archive into
`python/` and re-add those two path lines.

## Screen matching dependencies

`packages/` contains the extracted Windows x64 wheels for NumPy 2.2.6,
Pillow 12.1.0 and OpenCV headless 4.12.0.88. `wheels/` retains their original
archives. SHA-256 hashes, exact filenames and official PyPI download URLs are
recorded in `dependencies.json`. Downloads were checked against PyPI's published
SHA-256 values before extraction. Package licenses and third-party notices are
retained in their `.dist-info/` directories and OpenCV's package directory.

To rebuild these dependencies with network access:
`runtime\python\python.exe scripts\bundle_dependencies.py`.
Ordinary app startup requires no network or package installation.

Do not remove this directory when distributing the standalone Windows app.

Local OCR additionally bundles PyWinRT 3.2.1 (runtime, Foundation, Collections,
Globalization, Graphics.Imaging, Storage.Streams, Media.Ocr) and typing-extensions
4.15.0, with the same verified-wheel manifest. Recognition uses the Windows OCR
language packs already installed on the device; no cloud service is involved.

Excel interchange additionally bundles openpyxl 3.1.5 and et-xmlfile 2.0.0.
Their original wheels, licenses and verified PyPI SHA-256 hashes are included
in runtime/wheels, runtime/packages and dependencies.json.
