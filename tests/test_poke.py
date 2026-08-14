import json
import os
import socket
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from continuum import poke as poke_module
from continuum.poke import build_message, poke, socket_dir, socket_path


class BuildMessageTest(unittest.TestCase):
    def test_shape_matches_claude_code_protocol(self):
        self.assertEqual(
            build_message("continue", session_id="abc"),
            {
                "type": "user",
                "priority": "now",
                "message": {"content": "continue"},
                "session_id": "abc",
            },
        )

    def test_session_id_is_omitted_when_unknown(self):
        self.assertNotIn("session_id", build_message("continue"))


class SocketPathTest(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.pop("XDG_RUNTIME_DIR", None)

    def tearDown(self):
        if self._previous is not None:
            os.environ["XDG_RUNTIME_DIR"] = self._previous
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)

    def test_falls_back_to_tmp(self):
        self.assertEqual(socket_dir(), Path("/tmp/cc-socks"))
        self.assertEqual(socket_path(4711), Path("/tmp/cc-socks/4711.sock"))

    def test_honours_xdg_runtime_dir(self):
        os.environ["XDG_RUNTIME_DIR"] = "/run/user/501"
        self.assertEqual(socket_path(12), Path("/run/user/501/cc-socks/12.sock"))


class PokeDeliveryTest(unittest.TestCase):
    """Zustellung gegen einen echten Unix-Domain-Socket."""

    def test_sends_newline_delimited_json(self):
        received = []
        with TemporaryDirectory() as directory:
            sock_dir = Path(directory) / "cc-socks"
            sock_dir.mkdir()
            path = sock_dir / "999.sock"

            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            server.listen(1)

            def serve():
                connection, _ = server.accept()
                with connection:
                    received.append(connection.recv(65536))

            thread = threading.Thread(target=serve)
            thread.start()

            original = poke_module.socket_dir
            poke_module.socket_dir = lambda: sock_dir
            try:
                poke(999, "continue", session_id="s-1")
            finally:
                poke_module.socket_dir = original
                thread.join(timeout=5)
                server.close()

        self.assertEqual(len(received), 1)
        raw = received[0]
        self.assertTrue(raw.endswith(b"\n"), "Protokoll ist zeilenweise")
        self.assertEqual(
            json.loads(raw),
            {
                "type": "user",
                "priority": "now",
                "message": {"content": "continue"},
                "session_id": "s-1",
            },
        )

    def test_missing_socket_raises_oserror(self):
        with self.assertRaises(OSError):
            poke(424242, "continue")


if __name__ == "__main__":
    unittest.main()
