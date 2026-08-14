import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from wecker.sessions import Session, discover_profiles, list_all_sessions, list_sessions
from wecker.state import LogFingerprint, PokeMemory

AGENTS_OUTPUT = json.dumps(
    [
        {
            "pid": 29651,
            "cwd": "/Users/x/Code/Work",
            "kind": "interactive",
            "sessionId": "b9e4ab64",
            "name": "work-55",
            "status": "idle",
        },
        {"id": "7a598aa6", "kind": "background", "sessionId": "7a598aa6", "state": "blocked"},
    ]
)


def fake_runner(stdout=AGENTS_OUTPUT, returncode=0):
    def run(cmd, env=None, capture_output=None, text=None, timeout=None):
        run.calls.append((cmd, env))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    run.calls = []
    return run


class DiscoverProfilesTest(unittest.TestCase):
    def test_finds_every_claude_profile_with_projects(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            for name in (".claude", ".claude-work", ".claude-personal"):
                (home / name / "projects").mkdir(parents=True)
            (home / ".claude-peers.db").touch()
            (home / ".claude-empty").mkdir()

            profiles = [p.name for p in discover_profiles(home)]

        self.assertEqual(profiles, [".claude", ".claude-personal", ".claude-work"])


class ListSessionsTest(unittest.TestCase):
    def test_keeps_only_entries_with_pid_and_session_id(self):
        runner = fake_runner()
        sessions = list_sessions(Path("/home/.claude-work"), runner=runner)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].pid, 29651)
        self.assertEqual(sessions[0].name, "work-55")
        self.assertTrue(sessions[0].is_wakeable)

    def test_passes_profile_via_config_dir_env(self):
        runner = fake_runner()
        list_sessions(Path("/home/.claude-work"), runner=runner)
        _, env = runner.calls[0]
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/home/.claude-work")

    def test_survives_broken_output(self):
        self.assertEqual(list_sessions(Path("/p"), runner=fake_runner(stdout="nope")), [])
        self.assertEqual(list_sessions(Path("/p"), runner=fake_runner(returncode=1)), [])

    def test_busy_session_is_not_wakeable(self):
        session = Session(Path("/p"), "s", 1, "n", "busy", None)
        self.assertFalse(session.is_wakeable)

    def test_list_all_sessions_covers_every_profile(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            for name in (".claude-work", ".claude-personal"):
                (home / name / "projects").mkdir(parents=True)
            runner = fake_runner()
            sessions = list_all_sessions(home, runner=runner)

        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(runner.calls), 2)


class LogPathTest(unittest.TestCase):
    def test_resolves_log_below_profile(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory)
            project = profile / "projects" / "-Users-x-Code-Work"
            project.mkdir(parents=True)
            expected = project / "b9e4ab64.jsonl"
            expected.touch()

            session = Session(profile, "b9e4ab64", 1, "work-55", "idle", None)
            self.assertEqual(session.log_path, expected)

    def test_returns_none_when_log_is_missing(self):
        with TemporaryDirectory() as directory:
            session = Session(Path(directory), "unbekannt", 1, "n", "idle", None)
            self.assertIsNone(session.log_path)


class PokeMemoryTest(unittest.TestCase):
    def test_pokes_once_per_log_change(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "s.jsonl"
            log.write_text("a")
            memory = PokeMemory(Path(directory) / "state.json")

            first = LogFingerprint.of(log)
            self.assertTrue(memory.should_poke("s", first))
            memory.record("s", first)
            self.assertFalse(memory.should_poke("s", first))

            log.write_text("ab" * 100)
            self.assertTrue(memory.should_poke("s", LogFingerprint.of(log)))

    def test_forget_allows_poking_again(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "s.jsonl"
            log.write_text("a")
            memory = PokeMemory(Path(directory) / "state.json")
            fingerprint = LogFingerprint.of(log)
            memory.record("s", fingerprint)
            memory.forget("s")
            self.assertTrue(memory.should_poke("s", fingerprint))

    def test_survives_round_trip_and_broken_state_file(self):
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            log = Path(directory) / "s.jsonl"
            log.write_text("a")
            fingerprint = LogFingerprint.of(log)

            memory = PokeMemory(state_file)
            memory.record("s", fingerprint)
            memory.save()

            self.assertFalse(PokeMemory(state_file).should_poke("s", fingerprint))

            state_file.write_text("{kaputt")
            self.assertTrue(PokeMemory(state_file).should_poke("s", fingerprint))

    def test_missing_log_is_never_poked(self):
        with TemporaryDirectory() as directory:
            memory = PokeMemory(Path(directory) / "state.json")
            self.assertFalse(memory.should_poke("s", None))


if __name__ == "__main__":
    unittest.main()
