"""One isolated OCR request. Input is a PNG crop; output is plain JSON."""
import io
import json
import sys
from dataclasses import asdict
from PIL import Image
from autoflow.ocr import _recognize_native


def main():
    try:
        with Image.open(io.BytesIO(sys.stdin.buffer.read())) as image:
            lines = _recognize_native(image, sys.argv[1] if len(sys.argv) > 1 else "")
        result = {"lines": [asdict(line) for line in lines]}
    except Exception as error:
        result = {"error": str(error)}
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
