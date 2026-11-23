# Testing plan

## Automated checks

Run from the project root:

```text
python -m unittest discover -s tests -v
pio run -d firmware
```

The tests cover protocol rejection and missing values, pacing boundaries, pause/resume/completion, stale/contact-loss behavior, the device clock under bursty USB arrival, noisy synthetic breathing at 4–40 breaths/min with both sensor polarities, the breathing stress gate (jitter, uneven breath size, drift, sighs), the heart-rate swing, demo independence from target pace, CSV recording, and clearing all readings on stale data. The serial test uses a real pyserial `loop://` connection on any OS, including fragmented lines, firmware errors, oversized input recovery and unplug behavior. The GUI tests require a display. Skips do not establish success for the skipped feature.

Passing these tests verifies software behavior on synthetic inputs. It does **not** establish that a physical belt counts breaths accurately or that the SpO₂ estimate is clinically accurate. The firmware build verifies compilation, not sensor operation.

## Hardware acceptance checklist

| Test | Method | Expected result / record |
| --- | --- | --- |
| Electrical check | Inspect board documentation; check rails and divider before attaching sensors | 3.3 V-compatible wiring; no 5 V on GPIO; ADC divider present |
| Optical discovery | Boot with correctly wired MAX30102 | Ready message at address 0x57; red/IR samples update |
| Belt alone | Disconnect optical board while power is off, then restart | Optical errors reported; belt raw data continues; no pulse/SpO₂ fabricated |
| Finger removal | Remove finger after readings settle | Contact false; pulse/SpO₂ clear; belt continues |
| Optical disturbances | Move finger, change pressure, introduce ordinary ambient light | Record artifacts and invalid windows; note any plausible but wrong readings |
| Belt disconnect / short | Disconnect sensor with fixed resistor retained; test divider rails safely | No breathing rate for near-zero or near-full-scale ADC input |
| Flat belt | Leave the belt stationary | No continuing rate after the recent-cycle timeout; no apnea diagnosis |
| Belt fit | Compare a few comfortable fits over clothing | Smooth changing ADC; no pressure restriction or intermittent connections |
| USB unplug | Unplug during recording | Live readings clear, recording closes, explicit reconnect works |
| Reset | Press ESP32 reset while connected | Old metric histories clear; reacquisition required |
| 30-minute run | Record at rest with occasional normal repositioning | No crash/unbounded memory; inspect timing gaps, lost data and drift |

## Breathing-rate comparison

Use comfortable normal or paced breathing, without forced deep breathing or breath holds. Count complete chest expansion/relaxation cycles for **60 seconds** independently of the guide. Wait for the belt calibration and three cycles before evaluating its displayed value. Repeat at several comfortable rates and after re-fitting the belt.

For each trial record: duration, manual count, guide target (if used), displayed rate and its averaging delay, raw ADC range, fit, posture, movement and missing-reading periods. As a **proposed development target**, aim for agreement within **2 breaths/min at rest** after settling. This is an acceptance goal, not demonstrated accuracy. The display averages recent cycles; do not compare it with a single instantaneous breath immediately after changing pace. Investigate harmonics, missed cycles and motion-induced false breaths.

## Beat detection and heart-rate swing

The swing is only as good as each beat interval. Record the CSV while a validated reference that reports beat-to-beat intervals (a chest-strap heart-rate monitor or ECG) runs at the same time. Count missed and extra beats from `ibi_ms` against the reference over several 5-minute paced sessions at rest. Then compare the swing per breath from both sources. A single missed beat creates a false 20–40 bpm spike, so log the missed/extra beat rate before tuning anything.

## Pulse and oxygen comparison

Use a validated commercial pulse oximeter as a **reference**, following its instructions, under ordinary resting conditions. Use another finger/hand as appropriate, allow both to stabilize, and log paired timestamps, pulse, SpO₂, reference values and signal conditions over repeated trials. The devices may average different time windows.

Report differences, spread, unavailable-reading fraction, and repeatability. Normal resting comparisons only assess agreement in that narrow range; they **cannot calibrate or validate low-oxygen performance**. Formal SpO₂ accuracy validation needs specialized equipment and a controlled validation process. Do not try to lower oxygen saturation through breath holding or oxygen restriction to test this prototype.

The firmware's validity flag, 70–100% output bounds, and amplitude gates cannot guarantee that a plausible result is correct. If oxygen readings are inconsistent, keep them experimental and improve or replace the measurement system rather than adjusting a constant merely to match one reference reading.

## Results log

Keep local CSV recordings in `sessions/` and add a dated note for each physical test: board/sensor model, firmware version, settings, reference device, procedure, observed failures and next action. No physical validation has been performed yet. See `verification.md` for the software checks actually performed for this delivery.
