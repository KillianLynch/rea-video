"""Privacy regressions; no application installation or model downloads."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("socket.socket.connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_telemetry_disabled_before_submodule_import_in_fresh_process(self):
        code = """
import os, sys
import rea_video
assert os.environ['ORT_DISABLE_TELEMETRY'] == '1'
assert 'onnxruntime' not in sys.modules
import rea_video.vlm
assert os.environ['ORT_DISABLE_TELEMETRY'] == '1'
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT,
            env={**os.environ, "ORT_DISABLE_TELEMETRY": "0"}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_credentials_do_not_enable_client(self):
        from rea_video.vlm import VLMClient, VLMConfig

        env = {f"{prefix}_{suffix}": value
               for prefix in ("REA_VLM", "VIDEO_ANALYSIS", "GEMINI3")
               for suffix, value in (("BASE_URL", "https://example.com/v1"),
                                     ("API_KEY", "test-key"), ("MODEL", "test"),
                                     ("MODEL_NAME", "test"))}
        with patch.dict(os.environ, env):
            self.assertIsNone(VLMConfig.from_env())
            with self.assertRaisesRegex(ValueError, "disabled"):
                VLMClient(VLMConfig("https://example.com/v1", "test-key", ["test"]))

    def test_cli_rejects_external_vlm_before_opening_media(self):
        from rea_video.cli import main

        for command in ("decompose", "survey"):
            err = io.StringIO()
            with self.subTest(command=command), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised:
                    main([command, "/nonexistent.mp4", "--vlm"])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("External VLM API calls are disabled", err.getvalue())

    def test_python_api_rejects_vlm_before_processing(self):
        from rea_video.pipeline import decompose

        with self.assertRaisesRegex(ValueError, "External VLM API calls are disabled"):
            decompose("/nonexistent.mp4", "/nonexistent-output", use_vlm=True)

    def test_saved_vlm_preference_cannot_enable_decompose(self):
        from rea_video.cli import cmd_decompose

        args = argparse.Namespace(
            out="unused", video="unused.mp4", meta=None, vlm=False, no_vlm=False,
            no_stems=True, lang="en", no_whole=False, no_ocr=True, workers=1,
            engine=None, no_packaging=True, no_asr=True, max_vlm_shots=1,
            no_speakers=True, no_survey=True, ocr_lang=None, asr_lang=None,
        )
        result = {"summary": {"verdict": "test", "shots": 0, "confidence": 0, "vlm": "off"}}
        with patch("rea_video.memory.pref", side_effect=lambda key, default=None: "on" if key == "vlm" else default), \
                patch("rea_video.pipeline.decompose", return_value=result) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            cmd_decompose(args)
        self.assertFalse(run.call_args.kwargs["use_vlm"])

    def test_agent_answers_still_apply_without_external_client(self):
        from rea_video.review import apply_answers

        breakdown = {"shots": [{"id": "shot_001", "base": {"label": "ai_video"}}]}
        answers = {"shots": [{"id": "shot_001", "label_probs": {"live_action": 1.0},
                               "evidence": ["agent inspected frame"], "description": "A person"}]}
        result = apply_answers(breakdown, answers, by="Codex")
        self.assertEqual(result["applied"], ["shot_001"])
        review = breakdown["shots"][0]["review"]
        self.assertEqual(review["_by"], "Codex")
        self.assertGreater(review["label_probs"]["live_action"], 0.8)
        self.assertIn("agent inspected frame", review["evidence"])

    def test_installer_changes_only_checkout_environment_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/install_skill.sh", root / "scripts/install_skill.sh")
            fake = root / "fake-python"
            log = root / "commands"
            fake.write_text('''#!/usr/bin/env bash
printf '%s|%s\\n' "$ORT_DISABLE_TELEMETRY" "$*" >> "$INSTALL_TEST_LOG"
if [ "$1" = "--version" ]; then echo 'Python 3.12.0'; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ] && [ "$3" = "show" ]; then exit 1; fi
''')
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(root / "scripts/install_skill.sh")],
                env={**os.environ, "PYTHON_BIN": str(fake), "INSTALL_TEST_LOG": str(log),
                     "ORT_DISABLE_TELEMETRY": "0"}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text().splitlines()
            self.assertTrue(all(line.startswith("1|") for line in commands))
            self.assertIn(f"1|-m venv {root}/.venv", commands)
            self.assertIn(f"1|-m pip install -e {root}[ocr]", commands)
            self.assertNotIn("Linked", result.stdout)
            self.assertNotIn(".local/bin", result.stdout)

    def test_installer_rejects_invalid_agent_before_installing(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/install_skill.sh"), "--agent", "unknown"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown agent", result.stderr)

    def test_registration_selects_one_agent_and_preserves_existing_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            source = (ROOT / "scripts/install_skill.sh").read_text()
            # Relocate only this disposable copy's home-directory lookup.
            # Leave HOME and the user's actual agent registrations untouched.
            lookup = 'dir="$HOME/.$agent/skills"'
            self.assertEqual(source.count(lookup), 1)
            installer = root / "scripts/install_skill.sh"
            installer.write_text(source.replace(lookup, 'dir="$ROOT/agent-homes/.$agent/skills"'))
            fake = root / "fake-python"
            fake.write_text('''#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo 'Python 3.12.0'; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ] && [ "$3" = "show" ]; then exit 1; fi
''')
            fake.chmod(0o755)
            (root / "existing-skill").mkdir()
            for agent in ("codex", "claude", "agents"):
                (root / f"agent-homes/.{agent}/skills").mkdir(parents=True)
            for agent in ("codex", "claude", "agents"):
                target = root / f"agent-homes/.{agent}/skills/rea-video"
                for kind in ("file", "directory", "other-link", "broken-link", "absent", "same-link"):
                    with self.subTest(agent=agent, kind=kind):
                        if kind == "file":
                            target.write_text("keep me")
                        elif kind == "directory":
                            target.mkdir()
                            (target / "keep").write_text("keep me")
                        elif kind in ("other-link", "broken-link"):
                            other_target = root / ("existing-skill" if kind == "other-link" else "nonexistent-other-skill")
                            target.symlink_to(other_target)
                        result = subprocess.run(
                            ["bash", str(installer), "--agent", agent],
                            env={**os.environ, "PYTHON_BIN": str(fake)},
                            capture_output=True, text=True,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        if kind == "file":
                            self.assertEqual(target.read_text(), "keep me")
                            target.unlink()
                        elif kind == "directory":
                            self.assertEqual((target / "keep").read_text(), "keep me")
                            shutil.rmtree(target)
                        elif kind in ("other-link", "broken-link"):
                            self.assertEqual(target.readlink(), other_target)
                            target.unlink()
                        else:
                            self.assertEqual(target.readlink(), root / "skills/rea-video")
                        for other in {"codex", "claude", "agents"} - {agent}:
                            self.assertEqual(list((root / f"agent-homes/.{other}/skills").iterdir()), [])
                target.unlink()

    def test_skill_has_no_sponsored_installer_or_api_configuration(self):
        text = "\n".join(p.read_text() for p in (ROOT / "skills").rglob("*.md"))
        for removed in ("chatcut.io", "ChatCut", "REA_VLM_API_KEY", "GEMINI3_API_KEY"):
            self.assertFalse(removed in text, f"Unexpected instruction: {removed}")
        self.assertIn("rea-video review", text)
        self.assertIn("rea-video apply-review", text)


if __name__ == "__main__":
    unittest.main()
