# Engineering review — Breathing Biofeedback Trainer

Reviewed 2026-11-20 on Windows 11, Python 3.13.17, Tk scaling 1.33, no pyserial installed. Every file was read. The findings below describe the code as it was before the fixes.

## Status after the fixes (2026-11-20)

| Finding | Status |
| --- | --- |
| F2 SpO₂ headline | **Done.** 60 s beat-to-beat heart-rate chart over the guide's inhale bands, plus a heart-rate swing per breath tile. SpO₂ moved to a small "experimental" line |
| F3 breath detector | **Done.** Cycle-by-cycle peak/trough detection. The stress table is now `tests/test_breathing_stress.py` and gates ≥95% shown. New results are in the root README (26–82% shown before, 97–100% now; 62% at 6/min with 1× drift, a known limit) |
| F5 device clock | **Done.** `core.DeviceClock` maps `t_ms` onto host time |
| F6 Windows tests | **Done.** Footer packed first; serial test uses `loop://`; 21 tests pass on Windows, none skipped |
| F8 UX messages | **Done.** Readable error text; only firmware errors reset pulse history |
| F9 getters | Partly. `BreathTracker.rate()` has no side effects now; `PulseTracker.bpm()` still clears on staleness (a test relies on it) |
| F10 hygiene | Done: leftover text removed, git initialised, README rewritten. LICENSE and CI wait on Q2 |
| F1, F4, F7 | Open. Hardware build and validation, belt sensor choice, firmware belt timing |

## Workflow as built

```text
MAX30102 (100 Hz red/IR) ─┐
                          ├─ ESP32 loop ─ JSON lines, ~25 Hz + 1 per beat, 115200 baud ─┐
Belt divider → GPIO34 ADC ┘   (beat detect, SpO2 every 1 s, belt read inside sendSample)  │
                                                                                          ▼
 sources.SerialSource: reader thread → parse_sample() → Queue(512), timestamped with time.monotonic()
                                                                                          ▼
 trainer.tick() every 40 ms: drain queue → PulseTracker / BreathTracker → labels, canvases, CSV
 core.Settings/Session: pacer timing, kept fully separate from the measurements
```

## What is good

- `core` (pure logic), `sources` (I/O) and `trainer` (GUI) are cleanly separated, and the pure core is unit-testable.
- The protocol is strict and versioned, malformed lines are rejected, the queue is bounded, and oversized lines are recovered from.
- Stale or missing data shows `—`, never a plausible default. That is the right medical-device instinct.
- Demo mode carries a persistent badge, and the CSV has a `source` column so demo and live data can't be mixed silently.
- Firmware dependencies are pinned, and the measurement limits are documented honestly.

## Findings (ranked)

**F1 — Critical, portfolio: there is no physical evidence.** No hardware has been built or recorded, and nothing has been compared against a reference. All "verification" is synthetic. To a hiring manager this reads as a spec plus a simulator. One photo and one agreement plot (belt vs manual count, pulse vs a reference oximeter) would be worth more than everything else on this list.

**F2 — Critical, product: SpO₂ is the wrong headline metric.** A healthy person at rest reads 95–99%, and the Maxim algorithm on a generic MAX30102 board is off by several percent, so the number gives the user no breathing feedback. The physiological signal that paced breathing at about 6/min actually changes is *respiratory sinus arrhythmia*: heart rate rises on the inhale and falls on the exhale. The firmware already sends every beat interval (`ibi_ms`), so this is a display-only change. Plot beat-to-beat heart rate over the last 60 s with the pacer phase shaded behind it. That is what makes it a *biofeedback* trainer rather than a monitor. Keep SpO₂ as a secondary tile.

**F3 — High, algorithm, measured on synthetic data:** `BreathTracker` drops out on realistic breathing. A stress script (now `tests/test_breathing_stress.py`) runs 10-minute simulations with per-breath period jitter (CV), ±25% amplitude variation, a 40:60 inhale:exhale ratio, baseline drift and sighs. In the results below, "shown" is the % of time a rate is displayed after warm-up, and MAE is in breaths/min:

| Case | 6/min shown / MAE | 12/min | 18/min |
| --- | --- | --- | --- |
| Near-sine (CV 5%) | 82% / 0.23 | 71% / 0.40 | 78% / 0.48 |
| Typical human (CV 15%) | 62% / 0.28 | 53% / 0.59 | 56% / 1.04 |
| Variable (CV 25%) | 38% / 0.61 | 32% / 1.02 | 29% / 1.77 |
| CV 15% + drift 0.3× amplitude | 36% / 0.56 | 26% / 0.64 | 26% / 1.15 |
| CV 15% + drift 1× amplitude | **0%** | **0%** | **0%** |
| CV 15% + one sigh/min | 33% / 0.40 | 30% / 0.80 | 69% / 1.33 |

*Root cause:* the hysteresis thresholds are fixed at 35%/65% of a 20-s p10–p90 band. A weak breath never crosses 65%, so a breath is missed, the interval doubles, the "irregular" gate fires and the display blanks. Baseline drift moves the whole band. The irregularity gate (max−min > 45% of the median over 5 intervals) also blanks on normal variability. The existing tests only use pure sines, so none of this shows up.

I tried a quick 8-s baseline removal. It recovered roughly 20 points at moderate drift but did nothing at 1× drift, so a high-pass filter alone won't fix it. *Direction:* detect breaths cycle by cycle, using local peaks and troughs with prominence measured against recent breath amplitude. Display the median together with a variability indicator instead of blanking. Turn the table above into tests with acceptance targets, for example ≥90% shown and MAE ≤ 1/min at CV 15%. These are tuned values, so this needs your OK.

**F4 — High, hardware: conductive-rubber cord is the worst-case sensor for F3.** It has large hysteresis, its resistance creeps for minutes after it is stretched (stress relaxation), it is nonlinear and it ages. That produces exactly the drift that scores 0% above. *Option O1:* a $2–4 I²C IMU (e.g. MPU-6050) strapped to the abdomen, on the same I²C bus as the MAX30102. Abdominal tilt is a standard, robust respiration signal, and it needs no divider and no ADC tuning.

**F5 — Medium, timing: the algorithms run on host receipt time, not the device clock.** Each sample is timestamped with `time.monotonic()` when the reader thread parses it (`sources.py:108`). When lines arrive in a burst, from the USB-UART latency timer or GIL contention with Tk redraws, consecutive samples get dt≈0. The EMA weight in `core.py:171` (α = 1−e^(−dt/0.25)) then goes to ≈0, so those samples are effectively dropped. Every packet already carries `t_ms`, so drive `BreathTracker` with the unwrapped device time and use host time only for staleness. ASSUMPTION: how large this effect is on Windows has not been measured.

**F6 — Medium, tests on the target platform.** On this PC: 16 tests ran, **1 failed** and 1 was skipped.
- `test_footer_and_controls_fit_minimum_window` fails because the footer gets 20 px against a requested 21. Tk's `pack` squeezes the *last-packed* widget first, so the footer loses height before the stretchy middle does. Fix: pack the footer with `side="bottom"` before the content. (Screenshots show the window otherwise renders correctly at 1000×850 and 940×760.)
- The serial test is POSIX-only, so **the live data path has zero test coverage on Windows**, the platform the README targets. `docs/verification.md` says "16 passed", but that result is from Linux. Fix: open ports with `serial.serial_for_url()` (it accepts `COM3` just as well) so a `loop://` test runs everywhere.

**F7 — Medium, firmware.**
- The belt ADC is read only inside `sendSample()`, so it is sampled at ~25 Hz plus an extra read on every beat. That is non-uniform and tied to the optical loop. It is harmless once F5 is fixed, but it should be a fixed 25 Hz tick.
- `checkForBeat()` is SparkFun's simple threshold peak detector, which was written for MAX30105 signal levels. If F2 is built, IBI quality becomes the key metric, so check missed and extra beats on hardware first.
- `usableOpticalWindow()` requires `high - low >= 50` on data scaled down by 16, which is ≥800 raw counts peak-to-peak, or about 0.9% perfusion at IR ≈ 90k. This may reject cold or low-perfusion fingers. It is a tuned value, so it is flagged here and not changed.

**F8 — Low, UX.**
- Firmware error packets appear in the note bar as raw JSON, because `sources.py:109-110` passes `line[:200]`. Show the `message` field instead.
- *Any* event message, even "Skipped invalid sample" or a backlog notice, clears pulse history (`trainer.py:358-360`). One corrupt line blanks the pulse for three or more beats.

**F9 — Low, code quality.**
- `PulseTracker.bpm()` and `BreathTracker.rate()` are getters that also clear state and change the status text, so behavior depends on how often they are called. `_record()` calls them once per sample.
- While idle, `tick()` rebuilds `Session` from the spinboxes 25 times per second.

**F10 — Portfolio hygiene.**
- `README.md:39` says "This cloud workspace cannot write directly to your Windows Desktop", and `docs/verification.md` mentions a "Linux cloud workspace". Both are leftovers from AI generation, and a reader will spot them immediately.
- The project is not a git repo, and it has no LICENSE and no CI.
- The medical disclaimer appears in about six places. Keep one strong "Measurement limits" section and link to it everywhere else.
- The README opens with a feature list. Lead with the problem, then the design decisions, then the results.

## Proposed plan (waiting for OK)

1. **Quick fixes:** F10 leftover text, F6 footer, F8 messages, `git init` and `.gitignore` check.
2. **Data path:** F5 device clock and F6 Windows-runnable serial test.
3. **Algorithm:** F3 cycle-by-cycle breath detector, with the stress cases as the acceptance gate.
4. **Feature:** F2 beat-to-beat heart-rate (RSA) trace synced to the pacer; demote SpO₂.
5. **README rewrite** around problem → design → evidence.

Not software: F1 (build it, record it, compare it) and F4 (choosing the belt sensor).

**Open questions:** Q1 Is any hardware bought or built yet? Q2 Will this go on GitHub under your name? (If so, add a LICENSE and CI.) Q3 OK to replace the tuned breath-detection thresholds (F3)?
