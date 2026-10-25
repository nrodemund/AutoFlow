import ctypes
import threading
import unittest
from unittest.mock import Mock, patch
from autoflow.input import Input, WindowsInput, key_codes
from autoflow.engine import Engine
from autoflow.registry import discover
from autoflow.screen import WindowsScreen


class InputTests(unittest.TestCase):
    def backend(self):
        user = Mock()
        user.SendInput.return_value = 1
        return WindowsInput(user)

    def test_windows_x64_input_abi(self):
        self.assertEqual(ctypes.sizeof(Input), 40)

    def test_cursor_position_uses_physical_pixels_and_reports_failure(self):
        from ctypes import wintypes
        backend = self.backend()
        def read_cursor(pointer):
            position = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            position.x, position.y = -240, 810
            return 1
        backend.user32.GetCursorPos.side_effect = read_cursor
        screen = WindowsScreen(); screen._input = backend
        with patch('autoflow.input.physical_pixels') as pixels:
            self.assertEqual(screen.cursor_position(), {'x': -240, 'y': 810})
            pixels.assert_called_once()
        backend.user32.GetCursorPos.side_effect = None
        backend.user32.GetCursorPos.return_value = 0
        with patch('autoflow.input.physical_pixels'), self.assertRaisesRegex(RuntimeError, 'cursor position'):
            backend.cursor_position()

    def test_chords(self):
        self.assertEqual(key_codes("ctrl+shift+c"), [0x11, 0x10, ord("C")])
        self.assertEqual(key_codes("F12"), [0x7B])
        with self.assertRaises(ValueError): key_codes("unsupported_key")

    def test_keyboard_releases_reverse_order(self):
        backend = self.backend()
        events = []
        backend.send = lambda event: events.append((event.payload.keyboard.vk, event.payload.keyboard.flags))
        backend.key_press("ctrl+c")
        self.assertEqual(events, [(17, 0), (67, 0), (67, 2), (17, 2)])

    def test_failed_key_down_releases_modifier(self):
        backend = self.backend()
        events = []
        def send(event):
            pair = (event.payload.keyboard.vk, event.payload.keyboard.flags)
            events.append(pair)
            if pair == (67, 0): raise RuntimeError("failure")
        backend.send = send
        with self.assertRaises(RuntimeError): backend.key_press("ctrl+c")
        self.assertEqual(events[-1], (17, 2))

    def test_literal_unicode_text_events(self):
        backend = self.backend()
        events = []
        backend.send = lambda event: events.append((event.payload.keyboard.vk,
            event.payload.keyboard.scan, event.payload.keyboard.flags))
        backend.type_text("A\u00e4\U0001f600\t\r\n")
        units = [65, 228, 0xD83D, 0xDE00, 9, 13, 10]
        self.assertEqual(events, [(0, unit, flag) for unit in units for flag in (4, 6)])

    def test_empty_text_does_not_inject_input(self):
        backend = self.backend()
        backend.type_text("")
        backend.user32.SendInput.assert_not_called()
        with self.assertRaisesRegex(ValueError, "string"):
            backend.type_text({"x": 1, "y": 2})
        backend.user32.SendInput.assert_not_called()

    def test_literal_paste_never_uses_shared_clipboard(self):
        screen = WindowsScreen()
        screen._input = Mock()
        with patch("autoflow.input.clipboard_text") as clipboard:
            for text in ("expected text", "", "\u00e4\U0001f600\nnext"):
                screen.paste(text, False)
                screen._input.type_text.assert_called_with(text)
            clipboard.assert_not_called()
        screen._input.key_press.assert_not_called()

    def test_clipboard_paste_keeps_ctrl_v(self):
        screen = WindowsScreen()
        screen._input = Mock()
        screen.paste("ignored text", True)
        screen._input.key_press.assert_called_once_with("ctrl+v")
        screen._input.type_text.assert_not_called()

    def test_click_moves_and_releases(self):
        backend = self.backend()
        backend.move = Mock()
        backend.mouse = Mock()
        backend.click(-20, 50)
        backend.move.assert_called_once_with(-20, 50)
        self.assertEqual([c.args for c in backend.mouse.call_args_list], [("left", True), ("left", False)])

    def test_drag_cancel_releases_mouse(self):
        backend = self.backend()
        backend.move = Mock()
        backend.mouse = Mock()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            backend.drag({"x": 0, "y": 0}, {"x": 40, "y": 50}, 100, cancel)
        self.assertEqual(backend.mouse.call_args_list[-1].args, ("left", False))

    def test_drag_reaches_destination(self):
        backend = self.backend()
        backend.move = Mock()
        backend.mouse = Mock()
        backend.drag({"x": -30, "y": 10}, {"x": 40, "y": 50}, 0, threading.Event())
        self.assertEqual(backend.move.call_args_list[-1].args, (40, 50))

    def test_input_rejection_is_an_error(self):
        backend = self.backend()
        backend.user32.SendInput.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "Windows rejected"):
            backend.mouse("left", True)

    def test_find_point_offset_and_missing_branch(self):
        for location, expected in [((100, 200), {"x": 125, "y": 210}), (None, None)]:
            screen = Mock()
            screen.find.return_value = location
            p = {"version": 1, "schema_revision": 2, "main": "Main", "graphs": {"Main": {
                "entry": "find", "parameters": {}, "outputs": {"point": {"ref": ["find", "point"]}},
                "nodes": {"find": {"type": "FindPointOnScreen", "inputs": {"texture": "test.png", "offset_x": 25, "offset_y": 10}}}}}}
            self.assertEqual(Engine(p, discover(), screen=screen).run(), {"point": expected})

    def test_action_nodes_dispatch_and_copy_paste(self):
        screen = Mock()
        screen.copy.return_value = "Copied text"
        kinds = [("MouseMove", {"point": {"x": 1, "y": 2}}),
                 ("Drag", {"start": {"x": 1, "y": 2}, "end": {"x": 3, "y": 4}}),
                 ("KeyPress", {"keys": "tab"}), ("Copy", {}),
                 ("Paste", {"text": {"ref": ["n3", "text"]}, "use_clipboard": False})]
        nodes = {f"n{i}": {"type": kind, "inputs": inputs, "next": {"then": f"n{i+1}"} if i+1 < len(kinds) else {}}
                 for i, (kind, inputs) in enumerate(kinds)}
        p = {"version": 1, "schema_revision": 2, "main": "Main", "graphs": {"Main": {"entry": "n0", "nodes": nodes}}}
        Engine(p, discover(), screen=screen).run()
        screen.move.assert_called_once_with({"x": 1, "y": 2})
        screen.key_press.assert_called_once_with("tab")
        screen.paste.assert_called_once_with("Copied text", False)
