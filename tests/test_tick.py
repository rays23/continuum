"""End-to-End: limitierte Session erkennen und ueber einen echten Socket wecken."""

import json
import socket
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wecker import cli, poke as poke_module
from wecker.sessions import Session
from wecker.state import PokeMemory

LIMIT_LINE = json.dumps(
    {
        "type": "assistant",
        "timestamp": "2026-08-14T17:00:00.000Z",
        "isApiErrorMessage": True,
        "message": {
            "content": [
                {"type": "text", "text": "You've hit your session limit · resets 7pm (Europe/Berlin)"}
            ]
        },
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

    def tearDown(self):
        poke_module.socket_dir = self._original_socket_dir
        self._directory.cleanup()

    def _serve(self, pid):
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

    def test_limited_and_idle_session_gets_poked(self):
        self.log.write_text(LIMIT_LINE + "\n")
        server, thread = self._serve(999)
        try:
            poked = cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        finally:
            thread.join(timeout=5)
            server.close()

        self.assertEqual(poked, 1)
        self.assertEqual(len(self.received), 1)
        payload = json.loads(self.received[0])
        self.assertEqual(payload["message"]["content"], "continue")
        self.assertEqual(payload["session_id"], "sess-1")

    def test_busy_session_is_left_alone(self):
        self.log.write_text(LIMIT_LINE + "\n")
        poked = cli.run_tick("continue", False, self.memory, sessions=[self._session(status="busy")])
        self.assertEqual(poked, 0)
        self.assertEqual(self.received, [])

    def test_recovered_session_is_left_alone(self):
        self.log.write_text(LIMIT_LINE + "\n" + WORKING_LINE + "\n")
        poked = cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        self.assertEqual(poked, 0)
        self.assertEqual(self.received, [])

    def test_second_tick_does_not_poke_again_without_log_change(self):
        self.log.write_text(LIMIT_LINE + "\n")
        server, thread = self._serve(999)
        try:
            cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        finally:
            thread.join(timeout=5)
            server.close()

        second = cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        self.assertEqual(second, 0, "ohne Log-Aenderung darf nicht erneut gestupst werden")

    def test_poke_resumes_after_log_changed(self):
        self.log.write_text(LIMIT_LINE + "\n")
        server, thread = self._serve(999)
        try:
            cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        finally:
            thread.join(timeout=5)
            server.close()

        # Der Weckversuch selbst erzeugt real einen neuen Limit-Eintrag.
        self.log.write_text(LIMIT_LINE + "\n" + LIMIT_LINE + "\n")
        server, thread = self._serve(999)
        try:
            again = cli.run_tick("continue", False, self.memory, sessions=[self._session()])
        finally:
            thread.join(timeout=5)
            server.close()

        self.assertEqual(again, 1)
        self.assertEqual(len(self.received), 2)

    def test_missing_socket_is_not_counted_as_poke(self):
        self.log.write_text(LIMIT_LINE + "\n")
        poked = cli.run_tick("continue", False, self.memory, sessions=[self._session(pid=4242)])
        self.assertEqual(poked, 0)

    def test_dry_run_sends_nothing(self):
        self.log.write_text(LIMIT_LINE + "\n")
        (self.sock_dir / "999.sock").touch()  # Socket vorhanden, aber niemand hoert zu
        poked = cli.run_tick("continue", True, self.memory, sessions=[self._session()])

        self.assertEqual(poked, 1)
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main()
