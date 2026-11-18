"""English CLI defaults and explicit report-language overrides."""
import contextlib
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from rea_video.cli import main
from rea_video.i18n import DEFAULT_LANG, T, lang, set_lang


class EnglishCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"REA_VIDEO_HOME": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        set_lang(None)
        self.addCleanup(set_lang, DEFAULT_LANG)

    def help_text(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            main([*argv, "--help"])
        self.assertEqual(raised.exception.code, 0)
        return out.getvalue()

    def test_root_and_every_subcommand_help_are_english(self):
        root = self.help_text([])
        self.assertIn("Reverse-engineer videos", root)
        commands = re.search(r"\{([^}]+)\}", root).group(1).split(",")
        for command in [None, *commands]:
            with self.subTest(command=command):
                text = root if command is None else self.help_text([command])
                self.assertNotRegex(text, r"[\u3400-\u9fff]")

    def test_default_language_and_chinese_override(self):
        self.assertEqual(lang(), "en")
        self.assertEqual(T("中文", "English"), "English")
        set_lang("zh")
        self.assertEqual(T("中文", "English"), "中文")
        self.assertEqual(set_lang(None), "en")

    def test_report_default_saved_preference_and_explicit_override(self):
        from rea_video.memory import set_pref

        result = {"summary": {"verdict": "test", "shots": 0, "confidence": 0, "vlm": "off"}}
        for saved, override, expected in [
            (None, None, "en"), ("zh", None, "zh"),
            ("zh", "en", "en"), ("en", "zh", "zh"),
        ]:
            with self.subTest(saved=saved, override=override):
                set_pref("lang", saved)
                args = ["decompose", "unused.mp4"]
                if override:
                    args.extend(["--lang", override])
                with patch("rea_video.pipeline.decompose", return_value=result) as run, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(args), 0)
                self.assertEqual(run.call_args.kwargs["lang"], expected)
                self.assertFalse(run.call_args.kwargs["use_vlm"])

    def test_preferences_memory_and_errors_are_english(self):
        for argv, expected in [
            (["prefs"], "Report language: en (default) or zh"),
            (["memory"], "Preferences:"),
            (["prefs", "unknown-key"], "Unknown preference"),
            (["summary", "/nonexistent-rea-video-analysis.json"], "file not found:"),
        ]:
            with self.subTest(argv=argv):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    main(argv)
                self.assertIn(expected, out.getvalue())
                self.assertNotRegex(out.getvalue(), r"[\u3400-\u9fff]")

    def test_report_default_does_not_change_ocr_language(self):
        from rea_video.overlay import ocr_lang
        from rea_video.pipeline import decompose
        import inspect

        self.assertEqual(inspect.signature(decompose).parameters["lang"].default, "en")
        with patch.dict(os.environ, {"REA_OCR_LANG": "zh"}):
            self.assertEqual(ocr_lang(), "zh")  # bundled recognizer reads Chinese and English

    def test_review_priority_reasons_are_english(self):
        from rea_video.review import _priority

        record = {"deterministic": {"probs": {"ai_video": 0.55, "live_action": 0.45},
                                    "facts": {"pulldown": "24→30", "transcode_degraded": True}}}
        priority, reasons = _priority(record, {})
        self.assertEqual(priority, "high")
        self.assertIn("low confidence", "; ".join(reasons))
        self.assertNotRegex("; ".join(reasons), r"[\u3400-\u9fff]")

    def test_skill_frontmatter_loads_with_english_description(self):
        import yaml

        skill = Path(__file__).resolve().parents[1] / "skills/rea-video/SKILL.md"
        metadata = yaml.safe_load(skill.read_text().split("---", 2)[1])
        self.assertEqual(metadata["name"], "rea-video")
        self.assertTrue(metadata["description"].startswith("Analyse"))
        self.assertNotRegex(metadata["description"], r"[\u3400-\u9fff]")


if __name__ == "__main__":
    unittest.main()
