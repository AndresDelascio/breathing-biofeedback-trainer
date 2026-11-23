# Development roadmap

| Stage | Deliverable | Completion criterion |
| --- | --- | --- |
| 1. Software prototype | Breathing guide, demo, live USB input, breathing rate, heart-rate chart and swing, CSV | Automated timing, signal, serial and GUI checks pass |
| 2. Bench assembly | ESP32 + optical breakout + GY-6500 on the shared I²C bus | Correct voltages, both I²C devices found, changing raw channels, successful USB reconnect |
| 3. Belt fit and rate validation | Comfortable belt and reliable counts at rest | Compare 60-second manual counts over several comfortable rates; record error and failures |
| 4. Optical validation | Stable pulse and experimental SpO₂ | Compare against a validated reference at normal rest; document contact, motion and invalid-reading behavior |
| 5. Repeatability | Saved sessions across different days and fits | Quantify warm-up, drift, missing-data rates and repeatability; update thresholds based on evidence |
| 6. Optional refinement | Better signal quality, enclosure, improved sensor mounting | Only add cost after measured benefit; retain raw data and visible uncertainty |

Stages 2–5 require physical hardware and are not completed by compilation or simulated tests. There is no hardware accuracy result included in this starter project.

Done in software: device-clock timing, a cycle-by-cycle breath detector with a synthetic stress gate, and the beat-to-beat heart-rate chart with the RSA swing.

Done in firmware, not yet on hardware: the GY-6500 belly-tilt belt (the default breathing signal) on a fixed 25 Hz belt tick.

Possible later work: beat-detection quality checks (missed/extra beats), a measured `IMU_COUNTS_PER_DEG`, sensor-specific calibration UI, better motion rejection, FIFO overflow detection, and independent evaluations across different users and placements. A calibrated or certified oxygen measurement is a separate engineering and validation project, not a software checkbox. Do not add clinical alarms or automatic treatment recommendations to this prototype.
