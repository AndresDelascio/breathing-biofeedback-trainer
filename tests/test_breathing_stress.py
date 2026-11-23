"""Acceptance gate for BreathTracker on human-like breathing. All signals are SYNTHETIC.

Pure sines (test_core.py) hide real failure modes, so these 10-minute runs add per-breath
period jitter (CV), ±25% breath-size variation, a 40:60 inhale:exhale ratio, slow
baseline drift (as from belt creep) and sighs. "Shown" is the % of time after a 40 s
warm-up that a rate is displayed; MAE is the mean error in breaths/min against the true
median of the last 5 breaths.

Run directly to print the evidence table:  python tests/test_breathing_stress.py
"""

import math
from pathlib import Path
import random
import statistics
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core import BreathTracker

FS_HZ = 25  # firmware USB sample rate
CASES = {  # name: generator settings
    "near-sine (CV 5%)": dict(cv=0.05),
    "typical (CV 15%)": dict(cv=0.15),
    "variable (CV 25%)": dict(cv=0.25),
    "CV 15% + drift 0.3x": dict(cv=0.15, drift=0.3),
    "CV 15% + drift 1x": dict(cv=0.15, drift=1.0),
    "CV 15% + sighs": dict(cv=0.15, sighs=True),
}


def breath_signal(rate_bpm, cv, seconds, drift=0.0, sighs=False, seed=1):
    """Return [(t_s, adc_counts, true_rate_bpm)]. Breath size 250 counts around 2000."""
    rng = random.Random(seed)
    t, samples, recent = 0.0, [], []
    while t < seconds:
        period = max(1.6, rng.gauss(60 / rate_bpm, cv * 60 / rate_bpm))
        amp = 250 * max(0.4, rng.gauss(1, 0.25))
        if sighs and rng.random() < period / 60:  # about one sigh per minute
            amp *= 2.5
        recent = (recent + [period])[-5:]
        inhale = 0.4 * period
        n = int(period * FS_HZ)
        for i in range(n):
            u = i / FS_HZ
            # Raised-cosine inhale, then a slower raised-cosine exhale.
            x = ((1 - math.cos(math.pi * u / inhale)) / 2 if u < inhale else
                 (1 + math.cos(math.pi * (u - inhale) / (period - inhale))) / 2)
            base = 2000 + drift * 250 * math.sin(2 * math.pi * (t + u) / 45)  # 45 s drift cycle
            samples.append((t + u, round(base + amp * x + rng.uniform(-12, 12)),
                            60 / statistics.median(recent)))
        t += n / FS_HZ
    return samples


def score(rate_bpm, seconds=600, **case):
    """Return (shown %, MAE breaths/min) for one simulated session."""
    tracker = BreathTracker()
    shown, errors, total = 0, [], 0
    for t, adc, truth in breath_signal(rate_bpm, seconds=seconds, **case):
        tracker.update(adc, t)
        if t < 40:
            continue
        total += 1
        rate = tracker.rate(t)
        if rate is not None:
            shown += 1
            errors.append(abs(rate - truth))
    return 100 * shown / total, statistics.mean(errors) if errors else math.inf


class BreathingStressTests(unittest.TestCase):
    def test_acceptance_gates(self):
        for rate in (6, 12, 18):
            for name, case in CASES.items():
                with self.subTest(rate=rate, case=name):
                    shown, mae = score(rate, **case)
                    if name == "CV 15% + drift 1x" and rate == 6:
                        # Known limit: drift as large as the breath, over a 10 s breath,
                        # cancels the exhale. Floor only, so it cannot silently get worse.
                        self.assertGreaterEqual(shown, 50)
                    else:
                        self.assertGreaterEqual(shown, 95)
                    # Error allowance grows with rate for the most irregular breathing.
                    limit = 0.1 * rate if name == "variable (CV 25%)" else 1.0
                    self.assertLessEqual(mae, limit)


if __name__ == "__main__":
    print(f"{'case':24s}" + "".join(f"{f'{r}/min shown / MAE':>22s}" for r in (6, 12, 18)))
    for name, case in CASES.items():
        cells = [score(rate, **case) for rate in (6, 12, 18)]
        print(f"{name:24s}" + "".join(f"{f'{s:.0f}% / {m:.2f}':>22s}" for s, m in cells))
