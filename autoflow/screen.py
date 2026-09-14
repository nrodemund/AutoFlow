"""Windows desktop image matching and clipboard textures."""
import ctypes
import hashlib
import io
import math
import sys
from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@contextmanager
def physical_pixels():
    """Use physical pixels in the current capture thread, including mixed-DPI displays."""
    if sys.platform != "win32":
        raise RuntimeError("Live screen capture currently requires Windows")
    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        yield user32
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


@dataclass(frozen=True)
class PreparedTexture:
    rgb: object
    mask: object
    count: int
    channel: int
    plane: object
    variance: float

    @property
    def nbytes(self):
        return self.rgb.nbytes + self.plane.nbytes + (0 if self.mask is None else self.mask.nbytes)


def prepare_texture(texture):
    import numpy as np
    rgba = np.asarray(texture.convert('RGBA'))
    needle = np.ascontiguousarray(rgba[:, :, :3])
    mask = (rgba[:, :, 3] > 0).astype(np.uint8)
    count = int(mask.sum())
    if count == 0: raise ValueError('Texture is fully transparent')
    # The highest-variance channel is usually most selective for UI text/icons.
    variances = np.var(needle[mask != 0], axis=0)
    channel = int(np.argmax(variances))
    plane = np.ascontiguousarray(needle[:, :, channel])
    return PreparedTexture(needle, None if count == mask.size else mask, count, channel, plane, float(variances[channel]))


def validate_confidence(confidence):
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 < confidence <= 1:
        raise ValueError('Confidence must be greater than 0 and at most 1')


def _full_match(scene, texture):
    import cv2
    scores = cv2.matchTemplate(scene, texture.rgb, cv2.TM_SQDIFF, mask=texture.mask)
    minimum, _, point, _ = cv2.minMaxLoc(scores)
    return minimum, point


def _candidate_match(scene, texture, confidence):
    """Screen every position with an SSE lower bound, then refine in full RGB.

    A single channel's squared error cannot exceed the sum over RGB. Thus any
    RGB match passing the threshold must survive this filter, allowing for
    OpenCV floating-point roundoff. No image scaling or prior-frame reuse.
    """
    import cv2
    import numpy as np
    h, w = texture.rgb.shape[:2]
    if texture.variance == 0 or (scene.shape[0] - h + 1) * (scene.shape[1] - w + 1) < 100_000:
        return _full_match(scene, texture)
    plane = np.ascontiguousarray(scene[:, :, texture.channel])
    lower = cv2.matchTemplate(plane, texture.plane, cv2.TM_SQDIFF, mask=texture.mask)
    # Include the existing confidence epsilon and a conservative arithmetic margin.
    scale = texture.count * 3 * 255 ** 2
    roundoff = scale * 1e-5
    cutoff = scale * (1 - confidence + 1e-6) ** 2
    if not np.isfinite(lower).all(): return _full_match(scene, texture)
    candidates = lower <= cutoff + roundoff
    number = int(np.count_nonzero(candidates))
    if not number: return float('inf'), (0, 0)
    # Broad/flat matches are cheaper and more stable in the original matcher.
    if number > min(20_000, candidates.size // 8): return _full_match(scene, texture)
    ys, xs = np.nonzero(candidates)
    tiles_w = (candidates.shape[1] + 127) // 128
    tiles, groups = np.unique((ys // 128) * tiles_w + xs // 128, return_inverse=True)
    if len(tiles) > 64: return _full_match(scene, texture)
    left = np.full(len(tiles), scene.shape[1], dtype=int)
    top = np.full(len(tiles), scene.shape[0], dtype=int)
    right = np.zeros(len(tiles), dtype=int)
    bottom = np.zeros(len(tiles), dtype=int)
    np.minimum.at(left, groups, xs); np.minimum.at(top, groups, ys)
    np.maximum.at(right, groups, xs); np.maximum.at(bottom, groups, ys)
    if np.sum((right - left + w) * (bottom - top + h)) > scene.shape[0] * scene.shape[1] * .4:
        return _full_match(scene, texture)
    best, second, location = float('inf'), float('inf'), (0, 0)
    for x0, y0, x1, y1 in zip(left, top, right, bottom):
        region = scene[y0:y1 + h, x0:x1 + w]
        scores = cv2.matchTemplate(region, texture.rgb, cv2.TM_SQDIFF, mask=texture.mask)
        minimum, _, point, _ = cv2.minMaxLoc(scores)
        if not math.isfinite(minimum): return _full_match(scene, texture)
        local_second = float(np.partition(scores.ravel(), 1)[1]) if scores.size > 1 else float('inf')
        if minimum < best:
            second, best = min(best, local_second), minimum
            location = (int(point[0] + x0), int(point[1] + y0))
        else:
            second = min(second, minimum)
    # Preserve the original decision/order when roundoff could affect confidence
    # or which of two nearly tied positions is best (including duplicates).
    if abs(best - cutoff) <= roundoff or second - best <= roundoff:
        return _full_match(scene, texture)
    return best, location


def match_prepared(screen, texture, confidence=.97, *, accelerated=True):
    import numpy as np
    validate_confidence(confidence)
    scene = np.asarray(screen if screen.mode == 'RGB' else screen.convert('RGB'))
    if texture.rgb.shape[0] > scene.shape[0] or texture.rgb.shape[1] > scene.shape[1]: return None
    minimum, point = _candidate_match(scene, texture, confidence) if accelerated else _full_match(scene, texture)
    if not math.isfinite(minimum): return None
    similarity = 1 - math.sqrt(max(0, minimum) / (texture.count * 3)) / 255
    return point if math.isfinite(similarity) and similarity + 1e-6 >= confidence else None


def match_image(screen, texture, confidence=.97, *, accelerated=True):
    """Best top-left match using 1 - RGB RMS error / 255; alpha-zero is ignored.

    Set accelerated=False to use the original full-desktop RGB matcher.
    """
    validate_confidence(confidence)
    return match_prepared(screen, prepare_texture(texture), confidence, accelerated=accelerated)


class WindowsScreen:
    def __init__(self, base_dir=".", capture=None, *, accelerated=True):
        self.base_dir = Path(base_dir)
        self.capture = capture or self.capture_desktop
        self.cache = OrderedDict()
        self.accelerated = accelerated

    @staticmethod
    def capture_desktop():
        from PIL import ImageGrab
        with physical_pixels() as user32:
            # The virtual desktop may start to the left/above the primary monitor.
            origin = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))
            image = ImageGrab.grab(all_screens=True)
        if (image if image.mode == "RGB" else image.convert("RGB")).getbbox() is None:
            raise RuntimeError(
                "Screen capture returned an entirely black image; matching cannot run. "
                "Launch AutoFlow using start.cmd on your normal Windows desktop, outside "
                "an agent sandbox, and ensure the desktop is unlocked."
            )
        return image, origin

    def find(self, texture, confidence=.97):
        from PIL import Image
        if not isinstance(texture, str) or not texture.strip():
            raise ValueError("Choose a texture file or paste an image from the clipboard")
        path = (self.base_dir / texture).resolve()
        try:
            info = path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError as exc:
            raise ValueError(f"Texture file does not exist: {texture}") from exc
        key = (str(path), stamp)
        if key not in self.cache:
            with Image.open(path) as image:
                image.load()
                prepared = prepare_texture(image)
            # Evict stale versions and bound both entry count and total memory.
            for old in list(self.cache):
                if old[0] == str(path): del self.cache[old]
            self.cache[key] = prepared
            while len(self.cache) > 1 and (len(self.cache) > 32 or sum(t.nbytes for t in self.cache.values()) > 64 * 1024 * 1024):
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        scene, origin = self.capture()
        point = match_prepared(scene, self.cache[key], confidence, accelerated=self.accelerated)
        return (point[0] + origin[0], point[1] + origin[1]) if point is not None else None

    def click(self, x, y):
        self.input.click(x, y)
        return f"Clicked ({x}, {y})"

    def find_text(self, text, start, end, language="", cancel=None, case_sensitive=True):
        from autoflow.ocr import rectangle, normalized, recognize, exact_position
        if not isinstance(text, str) or not normalized(text):
            raise ValueError("OCR search text must be a nonempty string")
        left, top, right, bottom = rectangle(start, end)
        self.last_ocr_diagnostics = {"rectangle": (left, top, right, bottom), "passes": []}
        image, origin = self.capture()
        x, y = origin
        if left < x or top < y or right > x + image.width or bottom > y + image.height:
            raise ValueError("OCR rectangle must be inside the virtual desktop")
        crop = image.crop((left - x, top - y, right - x, bottom - y))
        def scan(pixels, label):
            lines = recognize(pixels, language, cancel)
            self.last_ocr_diagnostics["passes"].append({"mode": label, "lines": [line.text for line in lines]})
            return exact_position(lines, text, (left, top), case_sensitive)
        location = scan(crop, "original")
        if location is not None:
            return location
        # Windows OCR can omit tightly spaced time strings in antialiased UI
        # text. Retry the same crop in black and white, without relaxing the
        # comparison or substituting characters/numbers in recognized text.
        from PIL import ImageOps
        grayscale = ImageOps.grayscale(crop)
        # Small rendering differences change which antialiased edge pixels
        # belong to a glyph. Check two thresholds, retaining exact comparison.
        for threshold in (160, 180):
            binary = grayscale.point(lambda value: 255 if value > threshold else 0)
            location = scan(binary, f"threshold {threshold}")
            if location is not None:
                return location
        return None

    @property
    def input(self):
        from autoflow.input import WindowsInput
        if not hasattr(self, "_input"):
            self._input = WindowsInput()
        return self._input

    def move(self, p):
        self.input.move(p["x"], p["y"])

    def drag(self, start, end, duration, cancel):
        self.input.drag(start, end, duration, cancel)

    def key_press(self, keys):
        self.input.key_press(keys)

    def copy(self, cancel):
        from autoflow.input import clipboard_text
        sequence = self.input.user32.GetClipboardSequenceNumber()
        self.input.key_press("ctrl+c")
        for _ in range(100):
            if cancel.wait(.01):
                raise RuntimeError("Execution cancelled")
            if self.input.user32.GetClipboardSequenceNumber() != sequence:
                return clipboard_text()
        raise RuntimeError("Copy did not update the clipboard; select text in the target app first")

    def paste(self, text, use_clipboard):
        if use_clipboard:
            self.input.key_press("ctrl+v")
        else:
            # Ctrl+V is asynchronous: another copy (including a later graph
            # node) can replace clipboard contents before the target reads it.
            self.input.type_text(text)


def store_texture(raw, folder):
    """Decode and normalize uploads/clipboard images to a real PNG asset."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        converted = image.convert("RGBA")
        output = io.BytesIO()
        converted.save(output, format="PNG")
    content = output.getvalue()
    name = hashlib.sha256(content).hexdigest()[:20] + ".png"
    folder = Path(folder)
    folder.mkdir(exist_ok=True, parents=True)
    (folder / name).write_bytes(content)
    return "assets/" + name


def clipboard_texture(folder):
    from PIL import Image, ImageGrab
    if sys.platform != "win32":
        raise RuntimeError("Clipboard capture currently requires Windows")
    image = ImageGrab.grabclipboard()
    if not isinstance(image, Image.Image):
        raise ValueError("Clipboard has no image. Copy an image or use Win+Shift+S, then try again.")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return store_texture(output.getvalue(), folder)
