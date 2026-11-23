# Software verification

Last run November 20, 2026 on Windows 11, Python 3.13 with Tk, pyserial 3.5. No physical ESP32 or sensor was connected.

| Check | Result |
| --- | --- |
| Full test suite (`python -m unittest discover -s tests`) | **22 tests passed** (2026-11-23), none skipped |
| Protocol | Valid samples, ignored boot/info lines, rejection of every malformed field, readable firmware error messages |
| Device clock | Bursty USB arrival (4 lines per burst, 0–30 ms latency) maps back to even 40 ms device spacing; a device reset re-anchors |
| Serial transport | Real pyserial through a `loop://` port: fragmented lines, firmware error → pulse reset, invalid sample → no reset, oversized-line recovery, disconnect |
| Breath detector | Pure sines at 4–40 breaths/min, both polarities, with noise; flat, disconnected, stale and too-short data stay blank |
| Breath detector stress gate | 18 synthetic 10-minute sessions (6/12/18 breaths/min × 6 cases); table in the root README |
| Heart-rate swing | ±5 bpm synthetic RSA over 10 s breaths reads 10 ± 0.6 bpm; blank under 2 completed breaths |
| Desktop workflow | 60 s of demo data: readings, swing within 5–15 bpm, CSV fields, stale-data clearing, pause/resume/completion, source switching, footer visible at the 940×760 minimum window |
| Visual inspection | Demo interface checked at 1000×850 and 940×760; `demo_preview.png` uses simulated readings |
| ESP32 firmware compilation | Passed 2026-11-23 on Windows 11 with PlatformIO 6.2.0, including the GY-6500 belt code (23,616 B RAM, 295,017 B flash). No warnings from the sketch; one `I2C_BUFFER_LENGTH redefined` warning inside the SparkFun library. Not yet run on a board |

**Not tested:** ESP32 upload, real I²C/ADC acquisition, belt mechanics, beat-detection quality, pulse or SpO₂ accuracy, motion artifacts on a person, real USB-UART drivers. All breathing and heart-rate inputs above are synthetic. Complete the physical comparisons in `testing_plan.md` before relying on any measured trend.
