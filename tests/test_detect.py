import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from continuum.detect import LimitState, read_limit_state

LIMIT_TEXT = "You've hit your session limit · resets 7pm (Europe/Berlin)"


def entry(**kw):
    return json.dumps(kw)


def assistant(text, api_error=False, ts="2026-08-14T17:00:00.000Z"):
    return entry(
        type="assistant",
        timestamp=ts,
        isApiErrorMessage=api_error,
        message={"content": [{"type": "text", "text": text}]},
    )


def write_log(lines):
    tmp = TemporaryDirectory()
    path = Path(tmp.name) / "session.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp, path


class ReadLimitStateTest(unittest.TestCase):
    def test_detects_limit_when_last_assistant_entry_is_limit_error(self):
        tmp, path = write_log([assistant("arbeite"), assistant(LIMIT_TEXT, api_error=True)])
        with tmp:
            state = read_limit_state(path)
        self.assertTrue(state.is_limited)
        self.assertEqual(state.reset_hint, "7pm (Europe/Berlin)")

    def test_ignores_trailing_non_assistant_entries(self):
        # Nach dem Limit-Eintrag folgen real system-/queue-operation-Zeilen.
        tmp, path = write_log(
            [
                assistant(LIMIT_TEXT, api_error=True),
                entry(type="system", timestamp="2026-08-14T17:00:01.000Z"),
                entry(type="queue-operation", timestamp="2026-08-14T17:00:02.000Z"),
                entry(type="user", message={"content": "continue"}),
            ]
        )
        with tmp:
            state = read_limit_state(path)
        self.assertTrue(state.is_limited)

    def test_recovered_when_newer_assistant_entry_has_no_error(self):
        tmp, path = write_log(
            [
                assistant(LIMIT_TEXT, api_error=True),
                assistant("bin wieder da", ts="2026-08-14T17:00:30.000Z"),
            ]
        )
        with tmp:
            state = read_limit_state(path)
        self.assertFalse(state.is_limited)

    def test_other_api_errors_are_not_treated_as_rate_limit(self):
        tmp, path = write_log([assistant("API Error: Connection reset", api_error=True)])
        with tmp:
            state = read_limit_state(path)
        self.assertFalse(state.is_limited)

    def test_usage_limit_wording_also_counts(self):
        tmp, path = write_log([assistant("Claude usage limit reached", api_error=True)])
        with tmp:
            state = read_limit_state(path)
        self.assertTrue(state.is_limited)

    def test_string_content_is_supported(self):
        line = entry(
            type="assistant",
            timestamp="2026-08-14T17:00:00.000Z",
            isApiErrorMessage=True,
            message={"content": LIMIT_TEXT},
        )
        tmp, path = write_log([line])
        with tmp:
            state = read_limit_state(path)
        self.assertTrue(state.is_limited)

    def test_malformed_lines_are_skipped(self):
        tmp, path = write_log(["{kaputt", assistant(LIMIT_TEXT, api_error=True), "   "])
        with tmp:
            state = read_limit_state(path)
        self.assertTrue(state.is_limited)

    def test_empty_log_is_not_limited(self):
        tmp, path = write_log([""])
        with tmp:
            state = read_limit_state(path)
        self.assertFalse(state.is_limited)

    def test_missing_file_is_not_limited(self):
        state = read_limit_state(Path("/nonexistent/session.jsonl"))
        self.assertEqual(state, LimitState(is_limited=False))


if __name__ == "__main__":
    unittest.main()
