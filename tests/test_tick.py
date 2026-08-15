"""End-to-End: limitierte Session erkennen und ueber einen echten Socket anstossen."""

import json
import socket
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from continuum import cli, poke as poke_module
from continuum.sessions import Session
from continuum.state import PokeMemory

BERLIN = ZoneInfo("Europe/Berlin")


def limit_line(reset="7pm (Europe/Berlin)"):
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": "2026-08-14T16:15:00.000Z",
            "isApiErrorMessage": True,
            "message": {"content": [{"type": "text", "text": f"You've hit your session limit · resets {reset}"}]},
        }
    )


WORKING_LINE = json.dumps(
    {
        "type": "assistant",
        "timestamp": "2026-08-14T17:00:30.000Z",
        "message": {"content": [{"type": "text", "text": "bin wieder da"}]},
    }
)


class TickIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._directory = TemporaryDirectory()
        root = Path(self._directory.name)

        self.profile = root / ".claude-fake"
        project = self.profile / "projects" / "-project"
        project.mkdir(parents=True)
        self.log = project / "sess-1.jsonl"

        self.sock_dir = root / "cc-socks"
        self.sock_dir.mkdir()
        self.received = []
        self._original_socket_dir = poke_module.socket_dir
        poke_module.socket_dir = lambda: self.sock_dir

        self.memory = PokeMemory(root / "state.json")
        # Nach dem Reset von 7pm, also ist ein Anstoss faellig.
        self.after_reset = datetime(2026, 8, 14, 19, 30, tzinfo=BERLIN)

    def tearDown(self):
        poke_module.socket_dir = self._original_socket_dir
        self._directory.cleanup()

    def _serve(self, pid=999):
        path = self.sock_dir / f"{pid}.sock"
        path.unlink(missing_ok=True)  # close() entfernt die Socket-Datei nicht
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(1)

        def serve():
            try:
                connection, _ = server.accept()
                with connection:
                    self.received.append(connection.recv(65536))
            except OSError:
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        return server, thread

    def _session(self, status="idle", pid=999):
        return Session(self.profile, "sess-1", pid, "fake-55", status, None)

    def _tick(self, now=None, dry_run=False, session=None):
        return cli.run_tick(
            "continue",
            dry_run,
            self.memory,
            sessions=[session or self._session()],
            now=now or self.after_reset,
        )

    def test_limited_and_idle_session_gets_poked_after_the_reset(self):
        self.log.write_text(limit_line() + "\n")
        server, thread = self._serve()
        try:
            poked = self._tick()
        finally:
            thread.join(timeout=5)
            server.close()

        self.assertEqual(poked, 1)
        payload = json.loads(self.received[0])
        self.assertEqual(payload["message"]["content"], "continue")
        self.assertEqual(payload["session_id"], "sess-1")

    def test_nothing_is_sent_before_the_reset(self):
        """Der Fall aus dem Betrieb: 19 aufgestaute Nachrichten waehrend eines Limits."""
        self.log.write_text(limit_line("11:50pm (Europe/Berlin)") + "\n")
        before = datetime(2026, 8, 14, 20, 42, tzinfo=BERLIN)

        for minute in range(0, 180, 10):  # drei Stunden Ticks im Zehnminutentakt
            self.assertEqual(self._tick(now=before + timedelta(minutes=minute)), 0)

        self.assertEqual(self.received, [], "vor dem Reset darf nichts zugestellt werden")

    def test_poking_resumes_once_the_window_opened(self):
        self.log.write_text(limit_line("11:50pm (Europe/Berlin)") + "\n")
        self._tick(now=datetime(2026, 8, 14, 20, 42, tzinfo=BERLIN))

        server, thread = self._serve()
        try:
            poked = self._tick(now=datetime(2026, 8, 14, 23, 52, tzinfo=BERLIN))
        finally:
            thread.join(timeout=5)
            server.close()

        self.assertEqual(poked, 1)
        self.assertEqual(len(self.received), 1)

    def test_backoff_grows_when_the_reset_time_is_unreadable(self):
        self.log.write_text(limit_line("Monday") + "\n")
        start = datetime(2026, 8, 14, 20, 0, tzinfo=BERLIN)

        sent_at = []
        for minute in range(0, 180, 10):
            moment = start + timedelta(minutes=minute)
            server, thread = self._serve()
            try:
                if self._tick(now=moment):
                    sent_at.append(minute)
            finally:
                thread.join(timeout=1)
                server.close()

        # Ohne Bremse waeren es 18 Versuche. Mit Backoff: 10, 20, 40, 80 Minuten Abstand.
        self.assertEqual(sent_at, [0, 10, 30, 70, 150])

    def test_busy_session_is_left_alone(self):
        self.log.write_text(limit_line() + "\n")
        self.assertEqual(self._tick(session=self._session(status="busy")), 0)
        self.assertEqual(self.received, [])

    def test_recovered_session_is_left_alone(self):
        self.log.write_text(limit_line() + "\n" + WORKING_LINE + "\n")
        self.assertEqual(self._tick(), 0)
        self.assertEqual(self.received, [])

    def test_recovery_clears_the_backoff(self):
        self.log.write_text(limit_line("Monday") + "\n")
        server, thread = self._serve()
        try:
            self._tick(now=self.after_reset)
        finally:
            thread.join(timeout=5)
            server.close()

        self.log.write_text(limit_line("Monday") + "\n" + WORKING_LINE + "\n")
        self._tick(now=self.after_reset + timedelta(minutes=1))

        self.assertEqual(self.memory.plan_for("sess-1").attempts, 0)

    def test_missing_socket_is_not_counted_as_poke(self):
        self.log.write_text(limit_line() + "\n")
        self.assertEqual(self._tick(session=self._session(pid=4242)), 0)

    def test_dry_run_sends_nothing(self):
        self.log.write_text(limit_line() + "\n")
        (self.sock_dir / "999.sock").touch()
        self.assertEqual(self._tick(dry_run=True), 1)
        self.assertEqual(self.received, [])

    def test_wait_is_capped_even_if_the_reset_time_parses_oddly(self):
        """Grenzfall: Meldung genau zur Reset-Zeit. Ohne Deckel waeren das 24 Stunden."""
        line = json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-14T17:00:00.000Z",  # 19:00 Berlin
                "isApiErrorMessage": True,
                "message": {"content": "You've hit your session limit \u00b7 resets 7pm (Europe/Berlin)"},
            }
        )
        self.log.write_text(line + "\n")
        now = datetime(2026, 8, 14, 19, 0, tzinfo=BERLIN)

        self.assertEqual(self._tick(now=now), 0)
        planned = self.memory.plan_for("sess-1").next_attempt
        self.assertLessEqual(planned - now, timedelta(hours=2))

    def test_dry_run_does_not_change_the_schedule(self):
        self.log.write_text(limit_line("11:50pm (Europe/Berlin)") + "\n")
        self._tick(now=datetime(2026, 8, 14, 20, 42, tzinfo=BERLIN), dry_run=True)
        self.assertIsNone(self.memory.plan_for("sess-1").next_attempt)


if __name__ == "__main__":
    unittest.main()
