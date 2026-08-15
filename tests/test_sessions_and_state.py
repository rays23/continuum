import json
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from continuum.sessions import Session, discover_profiles, list_all_sessions, list_sessions
from continuum.state import Plan, PokeMemory

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
    def setUp(self):
        self._directory = TemporaryDirectory()
        self.state_file = Path(self._directory.name) / "state.json"
        self.now = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self._directory.cleanup()

    def test_unknown_session_is_due_at_once(self):
        self.assertTrue(PokeMemory(self.state_file).plan_for("s").is_due(self.now))

    def test_a_scheduled_session_is_not_due_before_its_time(self):
        memory = PokeMemory(self.state_file)
        memory.schedule("s", attempts=1, next_attempt=self.now + timedelta(minutes=10))

        plan = memory.plan_for("s")
        self.assertFalse(plan.is_due(self.now))
        self.assertTrue(plan.is_due(self.now + timedelta(minutes=10)))
        self.assertEqual(plan.attempts, 1)

    def test_schedule_survives_a_round_trip(self):
        memory = PokeMemory(self.state_file)
        memory.schedule("s", attempts=2, next_attempt=self.now + timedelta(minutes=20))
        memory.save()

        plan = PokeMemory(self.state_file).plan_for("s")
        self.assertEqual(plan.attempts, 2)
        self.assertEqual(plan.next_attempt, self.now + timedelta(minutes=20))

    def test_forget_makes_the_session_due_again(self):
        memory = PokeMemory(self.state_file)
        memory.schedule("s", attempts=3, next_attempt=self.now + timedelta(hours=1))
        memory.forget("s")

        plan = memory.plan_for("s")
        self.assertTrue(plan.is_due(self.now))
        self.assertEqual(plan.attempts, 0)

    def test_broken_state_file_is_ignored(self):
        self.state_file.write_text("{kaputt")
        self.assertTrue(PokeMemory(self.state_file).plan_for("s").is_due(self.now))

    def test_broken_entry_is_ignored(self):
        self.state_file.write_text('{"s": {"attempts": "viele", "next_attempt_ts": "bald"}}')
        plan = PokeMemory(self.state_file).plan_for("s")
        self.assertEqual(plan, Plan())

    def test_temp_file_is_process_specific_and_removed(self):
        memory = PokeMemory(self.state_file)
        memory.schedule("s", attempts=1, next_attempt=self.now)
        memory.save()

        self.assertTrue(self.state_file.exists())
        self.assertEqual(list(self.state_file.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
