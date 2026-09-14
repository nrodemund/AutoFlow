"""Local Windows OCR and exact whole-line matching in a physical screen region."""
import asyncio
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class TextLine:
    text: str
    box: tuple  # left, top, right, bottom in image pixels


def normalized(text):
    # OCR inserts layout whitespace. Never fold case, punctuation or digits.
    return " ".join(text.split())


def rectangle(start, end):
    for point in (start, end):
        if not isinstance(point, dict) or set(point) != {"x", "y"} or any(type(v) is not int for v in point.values()):
            raise ValueError("OCR rectangle requires two integer Points")
    left, right = sorted((start["x"], end["x"]))
    top, bottom = sorted((start["y"], end["y"]))
    if left == right or top == bottom:
        raise ValueError("OCR rectangle must have nonzero width and height")
    return left, top, right, bottom


def exact_position(lines, text, origin, case_sensitive=True):
    def key(value):
        value = normalized(value)
        return value if case_sensitive else value.casefold()
    matches = sorted((line for line in lines if key(line.text) == key(text)),
                     key=lambda line: (line.box[1], line.box[0]))
    if not matches:
        return None
    left, top, right, bottom = matches[0].box
    return origin[0] + int((left + right) / 2), origin[1] + int((top + bottom) / 2)


def recognize(image, language="", cancel=None):
    """Keep native OCR faults and COM state outside the editor process."""
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Execution cancelled")
    data = io.BytesIO()
    image.save(data, format="PNG")
    process = subprocess.Popen([sys.executable, "-m", "autoflow.ocr_worker", language],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[1],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        began = time.monotonic()
        payload = data.getvalue()
        while True:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Execution cancelled")
            if time.monotonic() - began > 35:
                raise RuntimeError("OCR worker timed out after 35 seconds")
            try:
                output, errors = process.communicate(payload, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                payload = None
        if process.returncode:
            raise RuntimeError(f"OCR worker failed (exit {process.returncode}). "
                               "AutoFlow is still running; retry the node. " + errors.decode("utf-8", errors="replace")[-1000:])
        result = json.loads(output)
        if "error" in result:
            raise RuntimeError(result["error"])
        return [TextLine(line["text"], tuple(line["box"])) for line in result["lines"]]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def _recognize_native(image, language="", cancel=None):
    """Recognize only the supplied crop; no network or screenshot files."""
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Execution cancelled")
    from winrt.runtime import init_apartment, ApartmentType
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.storage.streams import DataWriter
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat

    init_apartment(ApartmentType.MULTI_THREADED)
    # Worker owns this apartment for its entire process lifetime.
    return _scan_native(image, language, cancel, OcrEngine, Language, DataWriter, SoftwareBitmap, BitmapPixelFormat)


def _scan_native(image, language, cancel, OcrEngine, Language, DataWriter, SoftwareBitmap, BitmapPixelFormat):
    engine = (OcrEngine.try_create_from_language(Language(language)) if language
              else OcrEngine.try_create_from_user_profile_languages())
    if engine is None:
        available = ", ".join(l.language_tag for l in OcrEngine.available_recognizer_languages)
        raise ValueError(f"OCR language unavailable: {language or 'Windows profile'}. Installed: {available or 'none'}. Install an OCR language in Windows language settings.")
    # Upscale UI glyphs for recognition; coordinates are mapped back below.
    scale = min(3.5, OcrEngine.max_image_dimension / max(image.size))
    if scale < 1:
        raise ValueError("OCR rectangle exceeds the Windows OCR image size limit")
    width, height = (round(v * scale) for v in image.size)
    from PIL import Image
    pixels = image.resize((width, height), Image.Resampling.BICUBIC).convert("RGBA")
    with DataWriter() as writer:
        writer.write_bytes(pixels.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8, width, height)
    async def scan():
        operation = engine.recognize_async(bitmap)
        task = asyncio.ensure_future(operation)
        try:
            for _ in range(300):
                if cancel is not None and cancel.is_set():
                    raise RuntimeError("Execution cancelled")
                done, _ = await asyncio.wait([task], timeout=.1)
                if done:
                    return task.result()
            raise RuntimeError("OCR timed out after 30 seconds")
        finally:
            if not task.done():
                operation.cancel()
                task.cancel()
    try:
        result = asyncio.run(scan())
        lines = []
        for line in result.lines:
            boxes = [word.bounding_rect for word in line.words]
            if boxes:
                sx, sy = width / image.width, height / image.height
                lines.append(TextLine(line.text, (min(b.x for b in boxes) / sx,
                    min(b.y for b in boxes) / sy, max(b.x + b.width for b in boxes) / sx,
                    max(b.y + b.height for b in boxes) / sy)))
        return lines
    finally:
        bitmap.close()
