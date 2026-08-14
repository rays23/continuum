"""Regressionstests zu den Punkten aus dem Kimi-K3-Review."""

import json
import os
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wecker import detect, poke as poke_module
from wecker.detect import read_limit_state
from wecker.poke import is_own_socket, poke
from wecker.sessions import list_sessions
from wecker.state import LogFingerprint, PokeMemory
from tests.test_sessions_and_state import fake_runner

LIMIT_LINE = json.dumps(
    {
        "type": "assistant",
        "isApiErrorMessage": True,
        "message": {"content": "You've hit your session limit · resets 7pm (Europe/Berlin)"},
    }
)
NOISE_LINE = json.dumps({"type": "system", "payload": "x" * 900})


class TailWindowTest(unittest.TestCase):
    def test_finds_limit_entry_beyond_the_tail_window(self):
        """Nach dem Limit koennen sehr viele system-Zeilen folgen."""
        with TemporaryDirectory() as directory:
            log = Path(directory) / "s.jsonl"
            noise = "\n".join([NOISE_LINE] * 600)  # deutlich mehr als TAIL_BYTES
            log.write_text(LIMIT_LINE + "\n" + noise + "\n")

            original = detect.TAIL_BYTES
            detect.TAIL_BYTES = 4096
            try:
                self.assertGreater(log.stat().st_size, 4096)
                state = read_limit_state(log)
            finally:
                detect.TAIL_BYTES = original

        self.assertTrue(state.is_limited, "Limit-Eintrag ausserhalb des Fensters wurde uebersehen")

    def test_gives_up_below_the_scan_ceiling(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "s.jsonl"
            log.write_text("\n".join([NOISE_LINE] * 50) + "\n")

            original_tail, original_max = detect.TAIL_BYTES, detect.MAX_SCAN_BYTES
            detect.TAIL_BYTES, detect.MAX_SCAN_BYTES = 512, 2048
            try:
                state = read_limit_state(log)
            finally:
                detect.TAIL_BYTES, detect.MAX_SCAN_BYTES = original_tail, original_max

        self.assertFalse(state.is_limited)


class BackgroundAgentTest(unittest.TestCase):
    def test_background_entries_with_pid_are_ignored(self):
        stdout = json.dumps(
            [
                {"pid": 111, "kind": "background", "sessionId": "bg", "name": "hintergrund"},
                {"pid": 222, "kind": "interactive", "sessionId": "ia", "name": "vorne"},
            ]
        )
        sessions = list_sessions(Path("/p"), runner=fake_runner(stdout=stdout))

        self.assertEqual([s.pid for s in sessions], [222])


class SocketOwnershipTest(unittest.TestCase):
    def test_regular_file_is_not_accepted_as_socket(self):
        with TemporaryDirectory() as directory:
            impostor = Path(directory) / "999.sock"
            impostor.touch()
            self.assertFalse(is_own_socket(impostor))

    def test_own_socket_is_accepted(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "999.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            try:
                self.assertTrue(is_own_socket(path))
            finally:
                server.close()

    def test_poke_refuses_a_non_socket_path(self):
        with TemporaryDirectory() as directory:
            sock_dir = Path(directory)
            (sock_dir / "999.sock").touch()
            original = poke_module.socket_dir
            poke_module.socket_dir = lambda: sock_dir
            try:
                with self.assertRaises(PermissionError):
                    poke(999, "continue")
            finally:
                poke_module.socket_dir = original


class StateFileTest(unittest.TestCase):
    def test_temp_file_is_process_specific(self):
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "poked.json"
            memory = PokeMemory(state_file)
            memory.record("s", LogFingerprint(size=1, mtime_ns=2))
            memory.save()

            self.assertTrue(state_file.exists())
            leftovers = list(Path(directory).glob("*.tmp"))
            self.assertEqual(leftovers, [], "Temp-Datei muss weggeraeumt sein")
            self.assertIn(str(os.getpid()), str(state_file.with_suffix(f".{os.getpid()}.tmp")))


if __name__ == "__main__":
    unittest.main()
