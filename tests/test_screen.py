import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from contextlib import nullcontext

import numpy as np
from PIL import Image

from autoflow.engine import Engine, GraphError, load_project
from autoflow.registry import discover
from autoflow.screen import WindowsScreen, clipboard_texture, match_image, store_texture

ROOT = Path(__file__).resolve().parents[1]


class ScreenMatchingTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2026)
        self.scene = Image.fromarray(rng.integers(0, 256, (110, 180, 3), dtype=np.uint8))
        self.texture = self.scene.crop((45, 31, 70, 49))

    def test_exact_match(self):
        self.assertEqual(match_image(self.scene, self.texture, .999), (45, 31))

    def test_absent_match(self):
        self.assertIsNone(match_image(Image.new("RGB", (180, 110), "white"), self.texture))

    def test_constant_black_template_is_not_a_false_positive(self):
        self.assertIsNone(match_image(Image.new("RGB", (80, 80), "white"), Image.new("RGB", (10, 10), "black")))
        scene = Image.new("RGB", (80, 80), "white")
        scene.paste(Image.new("RGB", (10, 10), "black"), (25, 30))
        self.assertEqual(match_image(scene, Image.new("RGB", (10, 10), "black")), (25, 30))

    def test_transparent_texture_and_oversized_texture(self):
        texture = self.texture.convert("RGBA")
        texture.putpixel((0, 0), (255, 255, 255, 0))
        self.assertEqual(match_image(self.scene, texture, .999), (45, 31))
        with self.assertRaisesRegex(ValueError, "transparent"):
            match_image(self.scene, Image.new("RGBA", (10, 10)))
        self.assertIsNone(match_image(self.scene, Image.new("RGB", (500, 500))))

    def test_confidence_threshold(self):
        texture = Image.new("RGB", (10, 10), (90, 90, 90))
        scene = Image.new("RGB", (30, 30), (100, 100, 100))
        self.assertIsNone(match_image(scene, texture, .99))
        self.assertIsNotNone(match_image(scene, texture, .95))
        for invalid in (0, 1.1, True, float("nan")):
            with self.assertRaises(ValueError):
                match_image(scene, texture, invalid)

    def test_virtual_desktop_origin_and_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            self.texture.save(Path(directory) / "texture.png")
            screen = WindowsScreen(directory, capture=lambda: (self.scene, (-1920, -200)))
            self.assertEqual(screen.find("texture.png"), (-1875, -169))
            with self.assertRaisesRegex(ValueError, "does not exist"):
                screen.find("missing.png")

    def test_black_capture_reports_desktop_access_failure(self):
        user32 = Mock()
        user32.GetSystemMetrics.return_value = 0
        with patch("autoflow.screen.physical_pixels", return_value=nullcontext(user32)), \
             patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (80, 80), "black")):
            with self.assertRaisesRegex(RuntimeError, "entirely black.*sandbox"):
                WindowsScreen.capture_desktop()

    def test_valid_capture_preserves_virtual_origin(self):
        user32 = Mock()
        user32.GetSystemMetrics.side_effect = [-1920, -200]
        with patch("autoflow.screen.physical_pixels", return_value=nullcontext(user32)), \
             patch("PIL.ImageGrab.grab", return_value=self.scene):
            image, origin = WindowsScreen.capture_desktop()
            self.assertIs(image, self.scene)
            self.assertEqual(origin, (-1920, -200))

    def test_capture_with_only_one_nonzero_color_channel_is_valid(self):
        user32 = Mock();user32.GetSystemMetrics.return_value = 0
        image = Image.new('RGB', (80, 80));image.putpixel((5, 6), (0, 0, 1))
        with patch('autoflow.screen.physical_pixels', return_value=nullcontext(user32)), \
             patch('PIL.ImageGrab.grab', return_value=image):
            self.assertIs(WindowsScreen.capture_desktop()[0], image)

    def test_clipboard_image_is_saved_and_empty_clipboard_has_helpful_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("PIL.ImageGrab.grabclipboard", return_value=self.texture):
                relative = clipboard_texture(Path(directory) / "assets")
            with Image.open(Path(directory) / relative) as saved:
                self.assertEqual(saved.size, self.texture.size)
            for empty in (None, ["copied-file.png"]):
                with patch("PIL.ImageGrab.grabclipboard", return_value=empty):
                    with self.assertRaisesRegex(ValueError, "no image"):
                        clipboard_texture(Path(directory) / "assets")

    def test_invalid_uploaded_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                store_texture(b"not an image", directory)

    def test_accelerated_matches_reference_across_cases(self):
        rng = np.random.default_rng(314)
        for masked in (False, True):
            for confidence in (.8, .9, .97, .99, 1):
                pixels = rng.integers(0, 256, (380, 520, 3), dtype=np.uint8)
                scene = Image.fromarray(pixels)
                for xy in ((0, 0), (127, 128), (489, 357)):
                    x, y = xy
                    texture = scene.crop((x, y, x + 31, y + 23)).convert('RGBA')
                    if masked: texture.putpixel((3, 4), (0, 0, 0, 0))
                    self.assertEqual(match_image(scene, texture, confidence),
                                     match_image(scene, texture, confidence, accelerated=False))
                missing = Image.fromarray(rng.integers(0, 256, (23, 31, 3), dtype=np.uint8))
                self.assertEqual(match_image(scene, missing, confidence),
                                 match_image(scene, missing, confidence, accelerated=False))

    def test_duplicate_flat_and_channel_ambiguous_matches(self):
        rng = np.random.default_rng(12)
        scene = Image.fromarray(rng.integers(0, 256, (380, 520, 3), dtype=np.uint8))
        texture = scene.crop((12, 20, 42, 50))
        scene.paste(texture, (430, 300))
        cases = [(scene, texture, .97),
                 (Image.new('RGB', (520, 380), (100, 100, 100)), Image.new('RGB', (30, 30), (90, 90, 90)), .95)]
        # Similar grayscale intensity must not hide a match with different colors.
        colors = Image.new('RGB', (520, 380), (100, 200, 0))
        needle = Image.new('RGB', (30, 30), (100, 0, 200));colors.paste(needle, (490, 350))
        cases.append((colors, needle, .97))
        for scene, texture, confidence in cases:
            self.assertEqual(match_image(scene, texture, confidence),
                             match_image(scene, texture, confidence, accelerated=False))

    def test_near_confidence_boundary_matches_reference(self):
        rng = np.random.default_rng(7)
        scene = Image.fromarray(rng.integers(30, 200, (380, 520, 3), dtype=np.uint8))
        texture = Image.fromarray(np.asarray(scene.crop((200, 200, 235, 225))) + 8)
        boundary = 1 - 8 / 255
        for confidence in (boundary - 1e-5, boundary, boundary + 1e-5):
            self.assertEqual(match_image(scene, texture, confidence),
                             match_image(scene, texture, confidence, accelerated=False))

    def test_template_cache_reuses_alternating_files_and_invalidates_changes(self):
        from autoflow.screen import prepare_texture
        import os
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'a.png', Path(directory) / 'b.png'
            self.texture.save(first);self.texture.save(second)
            capture = Mock(return_value=(self.scene, (0, 0)))
            screen = WindowsScreen(directory, capture=capture)
            with patch('autoflow.screen.prepare_texture', wraps=prepare_texture) as prepare:
                for name in ('a.png', 'b.png', 'a.png'): self.assertEqual(screen.find(name), (45, 31))
                self.assertEqual(prepare.call_count, 2)
                stamp = first.stat().st_mtime_ns
                Image.new('RGB', self.texture.size, 'black').save(first)
                os.utime(first, ns=(stamp + 1_000_000, stamp + 1_000_000))
                self.assertIsNone(screen.find('a.png'))
                self.assertEqual(prepare.call_count, 3)
                self.assertEqual(len(screen.cache), 2)
            self.assertEqual(capture.call_count, 4)

    def test_fresh_frame_when_template_moves(self):
        with tempfile.TemporaryDirectory() as directory:
            self.texture.save(Path(directory) / 'a.png')
            moved = Image.new('RGB', self.scene.size, 'white');moved.paste(self.texture, (100, 60))
            capture = Mock(side_effect=[(self.scene, (-100, 0)), (moved, (-100, 0))])
            screen = WindowsScreen(directory, capture=capture)
            self.assertEqual(screen.find('a.png'), (-55, 31))
            self.assertEqual(screen.find('a.png'), (0, 60))

    def test_texture_cache_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = WindowsScreen(directory, capture=lambda: (self.scene, (0, 0)))
            for index in range(34):
                name = f'{index}.png';self.texture.save(Path(directory) / name);screen.find(name)
            self.assertEqual(len(screen.cache), 32)
            self.assertFalse(any(Path(key[0]).name == '0.png' for key in screen.cache))


class WaitUntilTests(unittest.TestCase):
    def setUp(self):
        self.project = load_project(ROOT / "examples/wait-for-screen.json")
        self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"]["interval_ms"] = 0
        self.logs = []

    def engine(self, outcomes):
        class Screen:
            def __init__(self):
                self.calls = 0
            def find(self, texture, confidence=.97):
                self.calls += 1
                return (10, 20) if outcomes[self.calls - 1] else None
        self.screen = Screen()
        return Engine(self.project, discover(), screen=self.screen, log=self.logs.append)

    def test_rechecks_pure_condition_and_stops_on_third_success(self):
        self.engine([False, False, True]).run()
        self.assertEqual(self.screen.calls, 3)
        self.assertEqual(self.logs, ["1", "2", "3", "Success message found on screen."])

    def test_false_output_after_exactly_five_attempts(self):
        self.engine([False] * 5).run()
        self.assertEqual(self.screen.calls, 5)
        self.assertEqual(self.logs[:5], ["1", "2", "3", "4", "5"])
        self.assertIn("Timed out", self.logs[-1])

    def test_immediate_true_has_no_delay(self):
        self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"]["interval_ms"] = 500
        engine = self.engine([True])
        with patch.object(engine.cancel, "wait", wraps=engine.cancel.wait) as wait:
            engine.run()
            wait.assert_not_called()

    def test_500ms_between_attempts(self):
        self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"]["interval_ms"] = 500
        engine = self.engine([False] * 5)
        with patch.object(engine.cancel, "wait", return_value=False) as wait, patch("autoflow.nodes.wait_until.time.monotonic", return_value=0):
            engine.run()
            self.assertEqual(wait.call_count, 4)
            self.assertTrue(all(call.args == (.5,) for call in wait.call_args_list))

    def test_condition_can_be_literal_bool(self):
        self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"]["condition"] = True
        self.engine([]).run()
        self.assertEqual(self.screen.calls, 0)
        self.assertIn("Success", self.logs[-1])

    def test_condition_can_be_produced_in_loop_body(self):
        nodes = self.project["graphs"]["Main"]["nodes"]
        nodes["visible"]["type"] = "IfOnScreen"
        nodes["wait"]["next"]["loop"] = "visible"
        self.engine([False, True]).run()
        self.assertEqual(self.screen.calls, 2)
        self.assertIn("Success", self.logs[-1])

    def test_invalid_interval_attempts_and_condition(self):
        for key, value in (("interval_ms", -1), ("max_attempts", 0), ("max_attempts", 2.2), ("condition", "true")):
            original = self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"][key]
            self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"][key] = value
            with self.assertRaises(GraphError):
                self.engine([False] * 5).run()
            self.project["graphs"]["Main"]["nodes"]["wait"]["inputs"][key] = original

    def test_cancel_during_interval(self):
        engine = self.engine([False] * 5)
        with patch.object(engine.cancel, "wait", side_effect=lambda seconds: engine.cancel.set()):
            with self.assertRaisesRegex(GraphError, "cancelled"):
                engine.run()
        self.assertEqual(self.screen.calls, 1)


if __name__ == "__main__":
    unittest.main()
