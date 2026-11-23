"""Desktop checks; skipped when there is no configured display."""

import csv
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import tkinter as tk
from sources import DemoSource
from trainer import Trainer


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "Requires a desktop display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = Trainer(self.root)
        self.root.after_cancel(self.app.after_id)
        self.root.update_idletasks()
        self.base = time.monotonic()
        self.app.source = DemoSource(self.base)

    def tearDown(self):
        self.app.close()

    def tick_at(self, now):
        with patch("trainer.time.monotonic", return_value=now):
            self.app.tick()
        self.root.after_cancel(self.app.after_id)

    def test_demo_values_csv_and_stale_display(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.csv"
            with patch("trainer.filedialog.asksaveasfilename", return_value=str(path)):
                self.app.toggle_recording()
            with patch("trainer.time.monotonic", return_value=self.base):
                self.app.toggle_session()
            for i in range(1501):
                self.tick_at(self.base + i / 25)
            self.assertIn("12.0", self.app.breath_label.cget("text"))
            self.assertIn("%", self.app.oxygen_label.cget("text"))
            self.assertNotEqual(self.app.oxygen_label.cget("text"), "— %")
            self.assertNotEqual(self.app.pulse_label.cget("text"), "—")
            # Demo HR follows its own breathing between ~65 and ~75 bpm.
            self.assertTrue(5 <= float(self.app.swing_label.cget("text").split()[0]) <= 15)
            self.app.stop_recording()
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertGreater(len(rows), 1400)
            self.assertEqual({row["source"] for row in rows}, {"demo"})
            self.assertAlmostEqual(float(rows[-1]["breathing_rate_bpm"]), 12, delta=0.2)
            self.assertTrue(rows[-1]["spo2_pct_experimental"])
            self.assertEqual(rows[-1]["session_state"], "running")
            with patch.object(self.app.source, "poll", return_value=[]):
                self.tick_at(self.base + 62)
            self.assertEqual(self.app.pulse_label.cget("text"), "—")
            self.assertEqual(self.app.oxygen_label.cget("text"), "— %")
            self.assertEqual(self.app.breath_label.cget("text"), "— breaths/min")
            self.assertEqual(self.app.swing_label.cget("text"), "— bpm")

    def test_pause_resume_completion_and_source_switch(self):
        self.app.setting_vars[2].set("0.5")
        with patch("trainer.time.monotonic", return_value=self.base):
            self.app.toggle_session()
        with patch("trainer.time.monotonic", return_value=self.base + 5):
            self.app.toggle_session()
        self.assertFalse(self.app.session.running)
        self.assertEqual(self.app.session.elapsed(self.base + 100), 5)
        with patch("trainer.time.monotonic", return_value=self.base + 10):
            self.app.toggle_session()
        self.tick_at(self.base + 35)
        self.assertFalse(self.app.session.running)
        self.assertEqual(self.app.start_button.cget("text"), "Start again")
        self.assertEqual(float(self.app.progress["value"]), 100)
        self.app.use_demo()
        self.assertIsNone(self.app.last_sample)
        self.app.reset_session()
        self.assertEqual(str(self.app.setting_inputs[0].cget("state")), "normal")

    def test_footer_and_controls_fit_minimum_window(self):
        self.root.geometry("940x760")
        for _ in range(5):
            self.root.update()
            time.sleep(0.02)
        pending = list(self.root.winfo_children())
        footer = None
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, tk.Label) and str(widget.cget("text")).startswith("Breathe comfortably"):
                footer = widget
        self.assertIsNotNone(footer)
        self.assertTrue(footer.winfo_ismapped())
        self.assertGreaterEqual(footer.winfo_height(), footer.winfo_reqheight())
        self.assertLessEqual(footer.winfo_rooty() + footer.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())
        self.assertTrue(self.app.record_button.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
