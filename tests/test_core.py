import json
import math
from pathlib import Path
import random
import statistics
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core import (BreathTracker, DeviceClock, PulseTracker, Sample, Session, Settings,
                  hr_swing, parse_error, parse_sample)
from sources import DemoSource


def packet(**changes):
    data = dict(type="sample", v=1, t_ms=1000, ir=90000, red=72000,
                finger=True, beat=False, ibi_ms=None, spo2=97, resp_raw=2048)
    data.update(changes)
    return json.dumps(data)


class ProtocolTests(unittest.TestCase):
    def test_sample_and_beat(self):
        self.assertEqual(parse_sample(packet()).spo2, 97)
        self.assertEqual(parse_sample(packet(beat=True, ibi_ms=800)).ibi_ms, 800)

    def test_boot_and_info_are_ignored(self):
        for line in ("ets Jul 29 2019", "", "[]", '{"type":"info"}', "{broken"):
            self.assertIsNone(parse_sample(line))

    def test_bad_readings_rejected(self):
        for bad in (dict(v=2), dict(t_ms=-1), dict(ir=262144), dict(red=True),
                    dict(finger=1), dict(beat=True), dict(ibi_ms=800),
                    dict(beat=True, ibi_ms=250), dict(beat=True, ibi_ms=2100),
                    dict(finger=False, spo2=97), dict(spo2=101), dict(spo2=69),
                    dict(spo2=float("nan")), dict(resp_raw=4096), dict(resp_raw=False)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_sample(packet(**bad))

    def test_missing_contact_never_yields_oxygen(self):
        sample = parse_sample(packet(finger=False, spo2=None, resp_raw=1300))
        self.assertIsNone(sample.spo2)
        self.assertEqual(sample.resp_raw, 1300)


class DeviceClockTests(unittest.TestCase):
    def test_bursty_usb_arrival_keeps_device_spacing(self):
        clock = DeviceClock()
        rng = random.Random(3)
        mapped, received_times = [], []
        for i in range(400):
            t_ms = 5000 + 40 * i
            # Lines arrive in bursts of 4 at one host time, plus 0-30 ms USB latency.
            received = 100 + (t_ms - t_ms % 160 + 160) / 1000 + rng.uniform(0, 0.03)
            received_times.append(received)
            mapped.append(clock.to_host(t_ms, received))
            self.assertLessEqual(mapped[-1], received)
        raw_steps = [b - a for a, b in zip(received_times, received_times[1:])]
        self.assertLess(min(raw_steps), 0.03)  # receipt time alone has near-zero dt inside bursts
        # The first burst teaches the clock its anchor; afterwards re-anchoring on a
        # faster packet can only nudge a step by the latency spread (30 ms).
        steps = [b - a for a, b in zip(mapped[4:], mapped[5:])]
        self.assertGreaterEqual(min(steps), 0.04 - 0.031)
        self.assertLessEqual(max(steps), 0.04 + 1e-9)
        self.assertAlmostEqual(statistics.median(steps), 0.04, places=6)

    def test_device_reset_reanchors(self):
        clock = DeviceClock()
        clock.to_host(90_000, 10.0)
        self.assertAlmostEqual(clock.to_host(40, 10.1), 10.1)  # t_ms restarted near zero

    def test_firmware_error_message_is_readable(self):
        self.assertEqual(parse_error('{"type":"error","v":1,"message":"MAX30102 not found"}'),
                         "MAX30102 not found")
        for line in (packet(), '{"type":"info"}', "boot", "[]"):
            self.assertIsNone(parse_error(line))


class TimingTests(unittest.TestCase):
    def test_inhale_exhale_boundaries(self):
        settings = Settings()
        self.assertEqual(settings.phase(0), ("Inhale", 0, 4))
        self.assertEqual(settings.phase(4), ("Exhale", 1, 6))
        self.assertEqual(settings.phase(10), ("Inhale", 0, 4))
        self.assertAlmostEqual(settings.breaths_per_minute, 6)

    def test_pause_resume_and_completion(self):
        session = Session(Settings(minutes=0.5))
        session.start(100)
        session.pause(110)
        self.assertEqual(session.elapsed(200), 10)
        session.start(200)
        self.assertEqual(session.elapsed(205), 15)
        self.assertEqual(session.elapsed(999), 30)
        self.assertTrue(session.complete(999))
        session.pause(999)
        session.start(1000)
        self.assertFalse(session.running)

    def test_invalid_timing(self):
        for bad in (dict(inhale=0), dict(exhale=float("nan")), dict(minutes=float("inf")), dict(minutes=31)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Settings(**bad)


class PulseTests(unittest.TestCase):
    def test_warmup_contact_loss_and_staleness(self):
        tracker = PulseTracker()
        for now in (1, 2):
            tracker.update(Sample(0, 90000, 70000, True, True, 1000), now)
        self.assertIsNone(tracker.bpm(2))
        tracker.update(Sample(0, 90000, 70000, True, True, 1000), 3)
        self.assertEqual(tracker.bpm(3), 60)
        self.assertIsNone(tracker.bpm(6.1))
        self.assertEqual(len(tracker.intervals), 0)
        for now in (7, 8, 9):
            tracker.update(Sample(0, 90000, 70000, True, True, 1000), now)
        tracker.update(Sample(0, 100, 100, False, False, None), 9.1)
        self.assertIsNone(tracker.bpm(9.1))


class HeartRateSwingTests(unittest.TestCase):
    def test_swing_per_guided_breath(self):
        # HR = 70 ± 5 bpm over each 10 s guide breath, a beat every 0.85 s.
        beats = [(e, 70 + 5 * math.sin(2 * math.pi * e / 10)) for e in (i * 0.85 for i in range(71))]
        self.assertAlmostEqual(hr_swing(beats, 10), 10, delta=0.6)
        self.assertIsNone(hr_swing(beats[:20], 10))  # under 2 completed breaths
        self.assertIsNone(hr_swing([], 10))


class BreathingTests(unittest.TestCase):
    def drive(self, rate, seconds=120, invert=False, noisy=False):
        tracker = BreathTracker()
        rng = random.Random(6)
        for i in range(int(seconds * 25) + 1):
            now = i / 25
            signal = 250 * math.sin(2 * math.pi * now * rate / 60)
            if invert:
                signal = -signal
            noise = rng.uniform(-12, 12) if noisy else 0
            tracker.update(round(2000 + signal + noise), now)
        return tracker, seconds

    def test_known_breathing_rates_both_polarities(self):
        for rate in (4, 6, 12, 20, 30, 36, 40):
            for invert in (False, True):
                with self.subTest(rate=rate, invert=invert):
                    tracker, now = self.drive(rate, invert=invert, noisy=True)
                    self.assertIsNotNone(tracker.rate(now))
                    self.assertAlmostEqual(tracker.rate(now), rate, delta=0.7)

    def test_no_rate_for_flat_disconnected_or_insufficient_data(self):
        for raw in (None, 0, 4095, 2000):
            tracker = BreathTracker()
            for i in range(1500):
                tracker.update(raw, i / 25)
            self.assertIsNone(tracker.rate(59.96))
        tracker, now = self.drive(12, seconds=19)
        self.assertIsNone(tracker.rate(now))

    def test_stopped_movement_and_data_gap_clear_reading(self):
        tracker, now = self.drive(12)
        self.assertIsNotNone(tracker.rate(now))
        self.assertIsNone(tracker.rate(now + 1.1))
        tracker, now = self.drive(12)
        for i in range(1, 251):
            tracker.update(2000, now + i / 25)
        self.assertIsNone(tracker.rate(now + 10))

    def test_shallow_gy6500_tilt_is_detected(self):
        # Firmware sends 2048 + 200 counts/deg of belly tilt. ESTIMATES: a shallow
        # breath tilts ~0.2 deg peak to peak; MPU-6500 noise ~0.055 deg rms at 5 Hz.
        for rate in (6, 12, 20):
            with self.subTest(rate=rate):
                tracker = BreathTracker()
                rng = random.Random(rate)
                for i in range(120 * 25 + 1):
                    tilt_deg = 0.1 * math.sin(2 * math.pi * (i / 25) * rate / 60) + rng.gauss(0, 0.055)
                    tracker.update(round(2048 + 200 * tilt_deg), i / 25)
                self.assertAlmostEqual(tracker.rate(120), rate, delta=0.7)

    def test_demo_measured_rate_is_independent_of_guide(self):
        demo = DemoSource(0)
        tracker = BreathTracker()
        pulse = PulseTracker()
        for i in range(1501):
            now = i / 25
            for event in demo.poll(now):
                tracker.update(event.sample.resp_raw, now)
                pulse.update(event.sample, now)
                self.assertIn(event.sample.spo2, (96, 97, 98))
        self.assertAlmostEqual(tracker.rate(60), 12, delta=0.2)
        self.assertAlmostEqual(Settings().breaths_per_minute, 6)
        self.assertGreater(pulse.bpm(60), 60)


if __name__ == "__main__":
    unittest.main()
