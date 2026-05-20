import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import openclaw_full_uninstall as uninstall


class UninstallTests(unittest.TestCase):
    def test_parse_env_file_and_discover_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env_file = root / "gateway.env"
            env_file.write_text(
                "\n".join(
                    [
                        "OPENCLAW_STATE_DIR=.openclaw-state",
                        "WORKSPACE_DIR=workspace",
                        "EXTRA_SKILL_DIR=skills",
                        "PLAIN_VALUE=not-a-path",
                    ]
                ),
                encoding="utf-8",
            )

            workspaces, managed, extra = uninstall.find_paths_in_env_config(env_file)

            self.assertIn(uninstall.norm_path(root / "workspace"), workspaces)
            self.assertIn(uninstall.norm_path(root / ".openclaw-state"), managed)
            self.assertIn(uninstall.norm_path(root / "skills"), extra)

    def test_remove_path_dry_run_does_not_delete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "openclaw-state"
            path.mkdir()
            args = argparse.Namespace(yes=False, quarantine=False, backup_root="")
            runner = uninstall.Runner(args)

            with redirect_stdout(io.StringIO()):
                runner.remove_path(path, "test")

            self.assertTrue(path.exists())
            self.assertFalse(runner.errors)

    def test_remove_path_refuses_home_root(self) -> None:
        args = argparse.Namespace(yes=False, quarantine=False, backup_root="")
        runner = uninstall.Runner(args)

        with redirect_stdout(io.StringIO()):
            runner.remove_path(uninstall.HOME, "test", allow_without_keyword=True)

        self.assertTrue(runner.warned)
        self.assertIn("dangerous path", runner.warned[0])

    def test_source_checkout_confirmed_by_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({"name": "@tools/openclaw"}), encoding="utf-8")

            self.assertTrue(uninstall.source_checkout_confirmed(root))

    def test_config_path_expansion_ignores_urls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self.assertIsNone(uninstall.expand_config_path("https://example.com/openclaw", root))
            self.assertEqual(uninstall.norm_path(root / "state"), uninstall.expand_config_path("state", root))

    def test_language_normalization(self) -> None:
        self.assertEqual("zh", uninstall.normalize_lang("2"))
        self.assertEqual("zh", uninstall.normalize_lang("zh-CN"))
        self.assertEqual("en", uninstall.normalize_lang("1"))
        self.assertEqual("en", uninstall.normalize_lang("english"))

    def test_process_env_does_not_trust_unrelated_openclaw_value(self) -> None:
        self.assertFalse(uninstall.process_env_value_path_like("PWD", r"E:\uninstall_openclaw"))
        self.assertTrue(uninstall.process_env_value_path_like("OPENCLAW_STATE_DIR", r"E:\state"))

    def test_parse_args_accepts_lang_without_prompt(self) -> None:
        with patch("sys.argv", ["openclaw_full_uninstall.py", "--lang", "zh", "--no-color", "--no-npx", "--no-kill"]):
            args = uninstall.parse_args()

        self.assertEqual("zh", args.lang)
        self.assertTrue(args.no_color)

    def test_parse_args_non_interactive_defaults_to_english(self) -> None:
        class NonInteractiveInput(io.StringIO):
            def isatty(self) -> bool:
                return False

        with patch("sys.argv", ["openclaw_full_uninstall.py"]), patch("sys.stdin", NonInteractiveInput()):
            args = uninstall.parse_args()

        self.assertEqual("en", args.lang)

    def test_runner_uses_chinese_dry_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "openclaw-state"
            path.mkdir()
            args = argparse.Namespace(yes=False, quarantine=False, backup_root="", lang="zh")
            runner = uninstall.Runner(args)
            out = io.StringIO()

            with redirect_stdout(out):
                runner.remove_path(path, "test")

            self.assertIn("[演练] 删除", out.getvalue())

    def test_run_read_plain_normalizes_empty_outputs(self) -> None:
        completed = uninstall.subprocess.CompletedProcess(["tool"], 0, None, None)
        with patch("openclaw_full_uninstall.subprocess.run", return_value=completed):
            cp = uninstall.run_read_plain(["tool"])

        self.assertEqual("", cp.stdout)
        self.assertEqual("", cp.stderr)

    def test_terminal_rendering_helpers(self) -> None:
        menu = uninstall.render_language_menu("zh")
        self.assertIn("语言", uninstall.strip_ansi(menu))
        self.assertIn("English", uninstall.strip_ansi(menu))
        section = uninstall.render_section("Summary")
        self.assertIn("Summary", uninstall.strip_ansi(section))


if __name__ == "__main__":
    unittest.main()
