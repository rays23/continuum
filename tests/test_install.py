import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.sh"
UNINSTALL = REPO / "uninstall.sh"


def _write_stub(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


class InstallScriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.home = root / "home dir"
        self.home.mkdir()
        self.stubs = root / "stubs"
        self.stubs.mkdir()
        self.launchctl_log = root / "launchctl.log"
        _write_stub(
            self.stubs / "launchctl", f'echo "$@" >> "{self.launchctl_log}"\nexit 0'
        )
        self.set_uname("Darwin")

        self.app = self.home / ".local" / "share" / "continuum"
        self.wrapper = self.home / ".local" / "bin" / "continuum"
        self.plist = self.home / "Library" / "LaunchAgents" / "dev.continuum.agent.plist"
        self.state = self.home / ".local" / "state" / "continuum"

    def set_uname(self, name):
        _write_stub(self.stubs / "uname", f'echo "{name}"')

    def run_script(self, script, env_extra=None, python="/usr/bin/true"):
        env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.stubs}{os.pathsep}{os.environ['PATH']}",
            "CONTINUUM_PYTHON": python,
        }
        env.pop("VIRTUAL_ENV", None)
        env.update(env_extra or {})
        if "CONTINUUM_PYTHON" in env and env["CONTINUUM_PYTHON"] is None:
            del env["CONTINUUM_PYTHON"]
        return subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True
        )

    def install(self, **kwargs):
        result = self.run_script(INSTALL, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_install_creates_wrapper_pointing_to_share_dir(self):
        self.install()
        self.assertTrue(self.wrapper.is_file())
        self.assertTrue(os.access(self.wrapper, os.X_OK))
        self.assertIn(str(self.app), self.wrapper.read_text())

    def test_plist_uses_share_dir_not_repo(self):
        self.install()
        text = self.plist.read_text()
        self.assertIn(str(self.app), text)
        self.assertNotIn(str(REPO), text)
        self.assertNotIn("__", text)

    def test_copies_only_py_files_without_subdirectories(self):
        self.install()
        pkg = self.app / "continuum"
        expected = {p.name for p in (REPO / "continuum").glob("*.py")}
        self.assertEqual({p.name for p in pkg.iterdir()}, expected)
        self.assertFalse(any(p.is_dir() for p in pkg.iterdir()))
        self.assertFalse((pkg / "__pycache__").exists())

    def test_second_run_is_idempotent(self):
        self.install()
        self.install()
        self.assertFalse((self.app / "continuum" / "continuum").exists())
        self.assertTrue((self.app / "continuum" / "cli.py").is_file())

    def test_no_temp_dir_left_over(self):
        self.install()
        leftovers = list((self.home / ".local" / "share").glob(".continuum.tmp.*"))
        self.assertEqual(leftovers, [])

    def test_launchctl_is_called(self):
        self.install()
        calls = self.launchctl_log.read_text()
        self.assertIn("bootout", calls)
        self.assertIn("bootstrap", calls)
        self.assertLess(calls.index("bootout"), calls.index("bootstrap"))

    def test_installed_wrapper_runs_from_any_cwd(self):
        self.install(python=sys.executable)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["HOME"] = str(self.home)
        result = subprocess.run(
            [str(self.wrapper), "--help"], env=env, cwd="/", capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_venv_interpreter_is_replaced_by_base(self):
        venv = Path(self._tmp.name) / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
        )
        self.install(
            env_extra={
                "CONTINUUM_PYTHON": None,
                "VIRTUAL_ENV": str(venv),
                "PATH": f"{venv / 'bin'}{os.pathsep}{self.stubs}{os.pathsep}{os.environ['PATH']}",
            }
        )
        self.assertNotIn(str(venv), self.plist.read_text())
        self.assertNotIn(str(venv), self.wrapper.read_text())

    def test_invalid_interpreter_aborts_without_plist(self):
        bad = Path(self._tmp.name) / "badpython"
        _write_stub(bad, "exit 1")
        result = self.run_script(INSTALL, python=str(bad))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(bad), result.stderr)
        self.assertFalse(self.plist.exists())

    def test_uninstall_removes_files_but_keeps_state(self):
        self.install()
        result = self.run_script(UNINSTALL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.wrapper.exists())
        self.assertFalse(self.app.exists())
        self.assertTrue(self.state.is_dir())
        self.assertIn(str(self.state), result.stdout)

    def test_non_darwin_aborts_without_creating_files(self):
        self.set_uname("Linux")
        result = self.run_script(INSTALL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("macOS", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])


class PackageLayoutTest(unittest.TestCase):
    def test_source_package_has_no_subpackages(self):
        # install.sh copies only continuum/*.py. A subpackage would be lost.
        subdirs = [
            p.name
            for p in (REPO / "continuum").iterdir()
            if p.is_dir() and p.name != "__pycache__"
        ]
        self.assertEqual(subdirs, [])

    def test_source_package_contains_only_py_files(self):
        names = [
            p.name
            for p in (REPO / "continuum").iterdir()
            if p.name != "__pycache__"
        ]
        self.assertTrue(names)
        self.assertTrue(all(n.endswith(".py") for n in names), names)


class ManifestTest(unittest.TestCase):
    def test_marketplace_version_matches_plugin_version(self):
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(market["plugins"][0]["version"], plugin["version"])


if __name__ == "__main__":
    unittest.main()
