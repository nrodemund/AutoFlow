"""Windows input injection and Unicode clipboard text, without extra packages."""
import ctypes
from ctypes import wintypes as w
import time
from autoflow.screen import physical_pixels


class Mouse(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]


class Keyboard(ctypes.Structure):
    _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("extra", ctypes.c_size_t)]


class Payload(ctypes.Union):
    _fields_ = [("mouse", Mouse), ("keyboard", Keyboard)]


class Input(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("payload", Payload)]


KEYS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
        "enter": 0x0D, "return": 0x0D, "tab": 9, "escape": 0x1B, "esc": 0x1B,
        "space": 0x20, "backspace": 8, "delete": 0x2E, "insert": 0x2D,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
KEYS.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def key_codes(chord):
    result = []
    for token in chord.lower().split("+"):
        token = token.strip()
        if token in KEYS:
            result.append(KEYS[token])
        elif len(token) == 1 and token.isascii() and token.isalnum():
            result.append(ord(token.upper()))
        else:
            raise ValueError(f"Unknown key: {token}. Use e.g. enter, ctrl+c, shift+tab, F5.")
    if not result:
        raise ValueError("Specify a key or key combination")
    return result


class WindowsInput:
    def __init__(self, user32=None):
        self.user32 = user32 or ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user32.SendInput.restype = w.UINT

    def send(self, event):
        if self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise RuntimeError("Windows rejected input. The target may be elevated or on a locked desktop.")

    def move(self, x, y):
        with physical_pixels():
            if not self.user32.SetCursorPos(x, y):
                raise RuntimeError("Windows could not move the cursor")

    def cursor_position(self):
        position = w.POINT()
        with physical_pixels():
            if not self.user32.GetCursorPos(ctypes.byref(position)):
                raise RuntimeError('Windows could not read the cursor position')
        return {'x': position.x, 'y': position.y}

    def mouse(self, button, down):
        flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
        if button not in flags:
            raise ValueError("Button must be left, right or middle")
        self.send(Input(0, Payload(mouse=Mouse(0, 0, 0, flags[button][0 if down else 1], 0, 0))))

    def click(self, x, y, button="left"):
        if button not in ("left", "right", "middle"):
            raise ValueError("Button must be left, right or middle")
        self.move(x, y)
        try:
            self.mouse(button, True)
        finally:
            self.mouse(button, False)

    def key_press(self, chord):
        keys = key_codes(chord)
        held = []
        try:
            for key in keys:
                self.send(Input(1, Payload(keyboard=Keyboard(key, 0, 0, 0, 0))))
                held.append(key)
        finally:
            failures = []
            for key in reversed(held):
                try:
                    self.send(Input(1, Payload(keyboard=Keyboard(key, 0, 2, 0, 0))))
                except RuntimeError as error:
                    failures.append(error)
            if failures:
                raise failures[0]

    def type_text(self, text):
        """Inject literal Unicode text without reading or changing the clipboard."""
        if not isinstance(text, str):
            raise ValueError("Text must be a string")
        # KEYEVENTF_UNICODE carries UTF-16 code units, including surrogate pairs.
        raw = text.encode("utf-16-le")
        for offset in range(0, len(raw), 2):
            unit = int.from_bytes(raw[offset:offset + 2], "little")
            self.send(Input(1, Payload(keyboard=Keyboard(0, unit, 4, 0, 0))))
            self.send(Input(1, Payload(keyboard=Keyboard(0, unit, 6, 0, 0))))

    def drag(self, start, end, milliseconds, cancel):
        if type(milliseconds) is not int or milliseconds < 0:
            raise ValueError("Drag duration must be a nonnegative integer")
        self.move(start["x"], start["y"])
        try:
            self.mouse("left", True)
            steps = max(1, min(1000, milliseconds // 16))
            began = time.monotonic()
            for i in range(1, steps + 1):
                if cancel.wait(max(0, began + milliseconds / 1000 * i / steps - time.monotonic())):
                    raise RuntimeError("Execution cancelled")
                self.move(round(start["x"] + (end["x"] - start["x"]) * i / steps),
                          round(start["y"] + (end["y"] - start["y"]) * i / steps))
        finally:
            self.mouse("left", False)


def clipboard_text(text=None):
    """Read Unicode text, or replace clipboard text when an argument is supplied."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetClipboardData.restype = ctypes.c_void_p
    user.OpenClipboard.argtypes = [w.HWND]
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    user.DestroyWindow.argtypes = [w.HWND]
    user.SetClipboardData.argtypes = [w.UINT, ctypes.c_void_p]
    user.SetClipboardData.restype = ctypes.c_void_p
    kernel.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = ctypes.c_void_p
    kernel.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel.GlobalFree.argtypes = [ctypes.c_void_p]
    # Writes need an owner HWND: EmptyClipboard with a NULL owner can prevent
    # SetClipboardData from succeeding. This window is never shown.
    owner = user.CreateWindowExW(0, "STATIC", "AutoFlow clipboard", 0, 0, 0, 0, 0,
                                 None, None, None, None) if text is not None else None
    if text is not None and not owner:
        raise RuntimeError("Could not create clipboard owner")
    for _ in range(30):
        if user.OpenClipboard(owner):
            break
        time.sleep(.01)
    else:
        if owner:
            user.DestroyWindow(owner)
        raise RuntimeError("Windows clipboard is busy")
    try:
        if text is None:
            handle = user.GetClipboardData(13)
            if not handle:
                raise ValueError("Clipboard contains no Unicode text")
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise RuntimeError("Cannot read clipboard")
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel.GlobalUnlock(handle)
        if not isinstance(text, str):
            raise ValueError("Clipboard text must be a string")
        raw = (text + "\0").encode("utf-16-le")
        handle = kernel.GlobalAlloc(0x0002, len(raw))
        if not handle:
            raise MemoryError("Could not allocate clipboard text")
        try:
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise RuntimeError("Cannot write clipboard")
            try:
                ctypes.memmove(pointer, raw, len(raw))
            finally:
                kernel.GlobalUnlock(handle)
            if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
                raise RuntimeError("Could not set clipboard text")
            handle = None  # Windows owns the allocation now.
        finally:
            if handle:
                kernel.GlobalFree(handle)
    finally:
        user.CloseClipboard()
        if owner:
            user.DestroyWindow(owner)
