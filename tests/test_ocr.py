import unittest
from unittest.mock import Mock, patch
from PIL import Image
from autoflow.ocr import TextLine, rectangle, exact_position, recognize
from autoflow.screen import WindowsScreen
from autoflow.engine import Engine, SimulationScreen
from autoflow.registry import discover


class OCRTests(unittest.TestCase):
    def test_second_threshold_recovers_digits_without_relaxing_match(self):
        target = "Aciclovir 10 mg / kgKg / 100 ml 08:00/16:00/00:00"
        screen = WindowsScreen(capture=lambda: (Image.new("RGB", (200, 100), (170, 170, 170)), (0, 0)))
        with patch("autoflow.ocr.recognize", side_effect=[
            [TextLine("Aciclovir 10 mg / kgKg / 100 ml", (0, 0, 100, 20))],
            [TextLine("Aciclovir mg / kgKg / 100 ml", (0, 0, 100, 20))],
            [TextLine(target, (0, 0, 180, 20))]]) as ocr:
            self.assertEqual(screen.find_text(target, {"x": 0, "y": 0}, {"x": 200, "y": 100}), (90, 10))
            self.assertEqual(ocr.call_count, 3)
            self.assertEqual(ocr.call_args_list[1].args[0].getpixel((0, 0)), 255)
            self.assertEqual(ocr.call_args_list[2].args[0].getpixel((0, 0)), 0)

    def test_missing_time_suffix_retries_preprocessing_with_exact_match(self):
        target = "Aciclovir 10 mg / kgKg / 100 ml 08:00/16:00/00:00"
        screen = WindowsScreen(capture=lambda: (Image.new("RGB", (200, 100), (180, 180, 180)), (0, 0)))
        with patch("autoflow.ocr.recognize", side_effect=[
            [TextLine("Aciclovir 10 mg / kgKg / 100 ml", (0, 0, 100, 20))],
            [TextLine(target, (0, 0, 180, 20))]]) as ocr:
            self.assertEqual(screen.find_text(target, {"x": 10, "y": 10}, {"x": 200, "y": 100}), (100, 20))
            self.assertEqual(ocr.call_count, 2)
            self.assertEqual(ocr.call_args.args[0].getpixel((0, 0)), 255)

    def test_fallback_does_not_accept_wrong_time(self):
        screen = WindowsScreen(capture=lambda: (Image.new("RGB", (200, 100)), (0, 0)))
        with patch("autoflow.ocr.recognize", return_value=[TextLine("Drug 10 mg 16:00", (0, 0, 100, 20))]):
            self.assertIsNone(screen.find_text("Drug 10 mg 08:00", {"x": 0, "y": 0}, {"x": 200, "y": 100}))

    def test_optional_case_insensitive_match_preserves_numbers_and_punctuation(self):
        lines = [TextLine("Acetylsalizyls\u00e4ure 500 mg i.V. einmalig", (0, 0, 300, 20))]
        target = "Acetylsalizyls\u00e4ure 500 mg i.v. einmalig"
        self.assertIsNone(exact_position(lines, target, (0, 0)))
        self.assertEqual(exact_position(lines, target, (0, 0), False), (150, 10))
        for wrong in (target.replace("500", "250"), target.replace("i.v.", "i.v,"), "500 mg"):
            self.assertIsNone(exact_position(lines, wrong, (0, 0), False))

    def test_worker_native_crash_is_node_error_and_next_call_recovers(self):
        crashed = Mock(returncode=-1073741819)
        crashed.communicate.return_value = (b"", b"")
        crashed.poll.return_value = -1073741819
        healthy = Mock(returncode=0)
        healthy.communicate.return_value = (b'{"lines":[{"text":"Target","box":[0,0,20,10]}]}', b"")
        healthy.poll.return_value = 0
        with patch("autoflow.ocr.subprocess.Popen", side_effect=[crashed, healthy]):
            with self.assertRaisesRegex(RuntimeError, "OCR worker failed"):
                recognize(Image.new("RGB", (30, 20)))
            self.assertEqual(recognize(Image.new("RGB", (30, 20)))[0].text, "Target")

    def test_cancellation_terminates_worker(self):
        cancel = Mock()
        cancel.is_set.side_effect = [False, True]
        worker = Mock()
        worker.poll.return_value = None
        with patch("autoflow.ocr.subprocess.Popen", return_value=worker):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                recognize(Image.new("RGB", (30, 20)), cancel=cancel)
        worker.kill.assert_called_once()
        worker.communicate.assert_called_once()

    def test_exact_whole_line_not_similar_dose_time_or_prefix(self):
        lines = [TextLine("Enoxaparin 40 mg s.c. 21:00", (10, 20, 210, 40))]
        for text in ("Enoxaparin 20 mg s.c. 21:00", "Enoxaparin 40 mg s.c. 09:00",
                     "Enoxaparin 40 mg", "enoxaparin 40 mg s.c. 21:00",
                     "Enoxaparin 40 mg sc 21:00"):
            self.assertIsNone(exact_position(lines, text, (0, 0)))
        self.assertEqual(exact_position(lines, " Enoxaparin  40 mg s.c. 21:00 ", (-500, 100)), (-390, 130))

    def test_duplicates_use_topmost_then_leftmost(self):
        lines = [TextLine("Target", (0, 30, 20, 50)), TextLine("Target", (30, 0, 50, 20)),
                 TextLine("Target", (0, 0, 20, 20))]
        self.assertEqual(exact_position(lines, "Target", (0, 0)), (10, 10))

    def test_reversed_rectangle_and_invalid_points(self):
        self.assertEqual(rectangle({"x": 20, "y": 30}, {"x": -10, "y": -20}), (-10, -20, 20, 30))
        for end in ({"x": 0, "y": 20}, {"x": True, "y": 20}, {"x": 1.5, "y": 20}):
            with self.assertRaises(ValueError): rectangle({"x": 0, "y": 0}, end)

    def test_only_crop_reaches_ocr_and_coordinates_return_to_desktop(self):
        image = Image.new("RGB", (200, 100), "white")
        image.putpixel((20, 10), (255, 0, 0))
        capture = Mock(return_value=(image, (-200, -100)))
        screen = WindowsScreen(capture=capture)
        with patch("autoflow.ocr.recognize", return_value=[TextLine("Target", (2, 4, 22, 14))]) as ocr:
            for _ in range(2):
                result = screen.find_text("Target", {"x": -180, "y": -90}, {"x": -100, "y": -50}, "de-DE")
                crop, language, _ = ocr.call_args.args
                self.assertEqual(crop.size, (80, 40))
                self.assertEqual(crop.getpixel((0, 0)), (255, 0, 0))
                self.assertEqual(language, "de-DE")
                self.assertEqual(result, (-168, -81))
            self.assertEqual(capture.call_count, 2)

    def test_invalid_region_and_empty_text_never_run_ocr(self):
        screen = WindowsScreen(capture=lambda: (Image.new("RGB", (100, 100)), (0, 0)))
        with patch("autoflow.ocr.recognize") as ocr:
            with self.assertRaisesRegex(ValueError, "inside"):
                screen.find_text("Target", {"x": -1, "y": 0}, {"x": 50, "y": 50})
            with self.assertRaisesRegex(ValueError, "nonempty"):
                screen.find_text("  ", {"x": 0, "y": 0}, {"x": 50, "y": 50})
            ocr.assert_not_called()

    def test_node_found_and_not_found(self):
        for location in ((30, 40), None):
            screen = Mock()
            screen.find_text.return_value = location
            project = {"version": 1, "main": "Main", "graphs": {"Main": {
                "entry": "ocr", "nodes": {"ocr": {"type": "FindTextOnScreen", "inputs": {"text": "Target"}}},
                "outputs": {"found": {"ref": ["ocr", "found"]}, "point": {"ref": ["ocr", "point"]}}}}}
            result = Engine(project, discover(), screen=screen).run()
            self.assertEqual(result, {"found": location is not None, "point": {"x": 30, "y": 40} if location else None})

    def test_simulation_does_not_capture(self):
        self.assertIsNone(SimulationScreen().find_text("Target", {}, {}))
