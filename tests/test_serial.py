"""Exercise the real pyserial reader thread through pyserial's loop:// port (any OS)."""

import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from sources import SerialSource


@unittest.skipUnless(importlib.util.find_spec("serial"), "Requires pyserial")
class SerialTests(unittest.TestCase):
    def setUp(self):
        # loop:// echoes every written byte back to the reader, like a device on a cable.
        self.source = SerialSource("loop://")
        self.port = self.source.connection

    def tearDown(self):
        self.source.close()

    def wait_events(self, predicate):
        events = []
        end = time.monotonic() + 2
        while time.monotonic() < end:
            events.extend(self.source.poll(time.monotonic()))
            if predicate(events):
                return events
            time.sleep(0.01)
        self.fail("Timed out waiting for serial events")

    def test_fragments_errors_oversize_recovery_and_unplug(self):
        data = dict(type="sample", v=1, t_ms=1000, ir=90000, red=72000,
                    finger=True, beat=True, ibi_ms=800, spo2=97, resp_raw=2048)
        line = (json.dumps(data) + "\n").encode()
        self.port.write(b"ESP32 boot\n" + line[:25])
        time.sleep(0.05)
        self.assertEqual(self.source.poll(time.monotonic()), [])
        self.port.write(line[25:])
        events = self.wait_events(lambda es: any(e.sample for e in es))
        self.assertEqual(next(e.sample for e in events if e.sample).spo2, 97)

        self.port.write(b'{"type":"error","v":1,"message":"Sampling gap; reacquiring pulse"}\n')
        events = self.wait_events(lambda es: any(e.message for e in es))
        self.assertEqual(events[0].message, "Sampling gap; reacquiring pulse")  # text, not raw JSON
        self.assertTrue(events[0].reset)

        self.port.write(b'{"type":"sample","v":2}\n')
        events = self.wait_events(lambda es: any(e.message for e in es))
        self.assertIn("Skipped invalid sample", events[0].message)
        self.assertFalse(events[0].reset)  # one bad line must not blank the pulse

        self.port.write(b"x" * 2200 + b"\n" + line)
        events = self.wait_events(lambda es: any(e.sample for e in es))
        self.assertTrue(any("oversized" in (e.message or "") for e in events))
        self.assertEqual(next(e.sample for e in events if e.sample).resp_raw, 2048)

        self.port.close()  # the port disappears under the reader thread, like an unplug
        events = self.wait_events(lambda es: any(e.fatal for e in es))
        self.assertTrue(any("disconnected" in (e.message or "") for e in events))


if __name__ == "__main__":
    unittest.main()
