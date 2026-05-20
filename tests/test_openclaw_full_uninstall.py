import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
