# Python application

Python 3.10+ with Tk is required. Only live USB mode needs `pyserial`; demo mode has no third-party dependencies. Run commands from the project root.

```text
python app/trainer.py
python app/trainer.py --list-ports
python app/trainer.py --port COM3
```

On Windows, use `py -3` or `.venv\Scripts\python.exe` in place of `python`. The root README gives a complete Windows setup. On Linux, use a desktop session and install your distribution's Python Tk package if needed (commonly `python3-tk`). On macOS, the python.org Python distribution includes Tk.

## Controls and readings

| Control or reading | Behavior |
| --- | --- |
| Start / Pause / Resume breathing | Runs or pauses the guide; paused time does not count toward the session |
| Reset session | Returns the guide to zero and unlocks timing controls; sensor streaming continues |
| Inhale / Exhale | 2–10 seconds each, with no breath holds |
| Session | 0.5–30 minutes; timing settings are locked during an unfinished session |
| Target breaths/min | `60 / (inhale + exhale)`; this is the guide's pace |
| Breathing rate · belly belt | Detected belly-movement cycles; independent of the guide |
| Pulse | Estimate from the latest 3–8 accepted pulse intervals |
| Experimental SpO₂ | Uncalibrated firmware estimate in small print; `—` means unavailable |
| 60 s chart | Heart rate of every beat (mint), belt signal (grey, auto-scaled) and the guide's inhale periods (bands) |
| Heart-rate swing per breath · RSA | Max − min beat heart rate inside each completed guided breath, median of the last 5; needs 2 breaths with at least 3 beats each, blank whenever the pulse is blank |
| Connect USB | Opens a COM/serial port at 115200 baud; opening may reset the ESP32 |
| Use demo | Releases the serial connection and resets measurement histories |
| Record CSV… | Starts optional recording to a location you choose |

The breathing guide can run without valid measurements. Sensor streaming also continues while the guide is idle or paused. Switching sources stops recording so one file cannot silently mix demo and live data. Completing a timed session stops recording; resetting or pausing does not. Close the window or select **Stop recording** to flush and close the file.

The belt shows no rate for its first 20 seconds, then needs three breath intervals. Each peak and trough is confirmed when the smoothed signal reverses by 30% of the median recent breath size (at least 30 ADC counts), so slow belt drift is ignored. The rate is 60 divided by the median of recent peak-to-peak and trough-to-trough intervals, over about **4–40 breaths/min** while stationary. Irregular breathing is flagged ("Variable breathing · showing the median") rather than hidden. It rejects near-rail ADC values and intervals outside 1.4–15.3 s. With no movement, the last rate clears after 1.6 breath periods (at most about 15 s); there is no apnea alarm. This is a prototype algorithm, tested on synthetic signals only (see the root README).

The heart-rate swing uses the guide's own breaths, so it only measures while the guide runs. Demo heart rate follows the demo's 12/min breathing, not the guide, so its swing is a display check, not a physiology result.

## Recording

CSV includes UTC host receipt time, device milliseconds (session time and the algorithms use this device clock, not bursty USB receipt time), source (`demo`/`live`), session elapsed time and state, guide phase/settings, raw red/IR, contact and beat flags, pulse intervals, pulse estimate, experimental SpO₂, raw belt ADC, and measured breathing rate. Missing values are empty fields, not zero or normal defaults. `bpm` in the breathing-rate column means **breaths per minute**; in `pulse_bpm` it means **beats per minute**.

Files stay on your computer; the app does not upload or transmit them. Writes flush about once a second, so a sudden crash or power loss may lose the newest buffered rows. Avoid leaving recording on longer than needed; raw samples accumulate continuously even while the guide is paused. Device timestamps wrap after roughly 49.7 days and restart after board reset. Host receipt timestamps include USB scheduling delay.

## Troubleshooting

| Problem | Check |
| --- | --- |
| No window | Run on a desktop, not a headless server; verify Tk with `python -m tkinter` |
| No ports | Install requirements, use a data cable, check the USB-UART driver, then Refresh |
| Access denied / port busy | Close Arduino Serial Monitor and other applications holding the same port |
| Linux permission error | Follow your distribution's serial-device access instructions; do not run the GUI as root |
| Optical readings stay blank | Confirm 0x57 wiring, finger placement, ambient-light shielding, contact threshold and signal amplitude |
| SpO₂ blank but pulse available | The oxygen algorithm needs usable red AND IR windows; allow settling and inspect raw data |
| Belt never finishes calibration | Check stable USB data and divider wiring; reconnect after adjusting the belt |
| Belt calibrates but no rate | Ensure breathing tilts the GY-6500 (flat on the belly, X arrow toward the head); inspect `resp_raw` for changing, non-saturated counts |
| Values disappear | Data over one second old is cleared; no pulse for three seconds clears pulse history |
| USB unplugged | Reconnect the cable, select the correct port and click Connect USB again; reconnect is explicit |

The app skips oversized/malformed packets, uses a bounded serial queue, and clears stale readings. CSV recording stops on a detected USB disconnect. A prolonged busy GUI can lose samples; the reader reports a backlog instead of replaying old measurements as current.
