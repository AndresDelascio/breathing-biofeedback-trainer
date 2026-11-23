# ESP32 firmware

Target: **original ESP32 DevKit / ESP32-WROOM-32**, `esp32dev` in PlatformIO, `ESP32 Dev Module` in Arduino IDE. SDA=21, SCL=22 (MAX30102 and GY-6500 share them), optional stretch-cord ADC=34. See [wiring](../hardware/wiring.md) first.

## Arduino IDE

1. Install [Arduino IDE](https://www.arduino.cc/en/software).
2. In Preferences, add the ESP32 Boards Manager URL:

   ```text
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```

3. In Boards Manager, install **esp32 by Espressif Systems**, version **2.0.17** to match the tested build.
4. In Library Manager, install **SparkFun MAX3010x Pulse and Proximity Sensor Library**, version **1.1.2**.
5. Open `esp32_biofeedback/esp32_biofeedback.ino`, select **ESP32 Dev Module**, and choose the board's serial port.
6. Verify, then Upload. If the uploader stays at `Connecting…`, hold **BOOT** while upload begins and release once writing starts. Only do this if your board needs it.
7. Open Serial Monitor at **115200 baud** to inspect JSON. Close it before the Python app connects.

If no COM port appears, check the data cable and install the USB-UART driver appropriate to the actual board (commonly CP210x or CH340) from its manufacturer.

## PlatformIO

With PlatformIO Core installed, run from the project root:

```text
pio run -d firmware
pio run -d firmware -t upload --upload-port COM3
pio device monitor -b 115200 -p COM3
```

Replace `COM3` with your actual port. On Linux it may be `/dev/ttyUSB0` or `/dev/ttyACM0`. The build is pinned to Espressif32 6.9.0 / Arduino ESP32 2.0.17 and SparkFun library 1.1.2. Compilation may show the upstream library's `I2C_BUFFER_LENGTH` redefinition warning; the tested build completes successfully.

## Sampling and calculations

- MAX30102 acquisition: **100 Hz**, one-sample hardware averaging, red+IR mode, 411 µs pulse width, 4096 nA ADC range, initial LED current register `0x1F` (about 6.2 mA).
- Pulse detection: SparkFun `checkForBeat()` consumes every available 100 Hz IR sample. After two seconds of contact settling, accepted intervals are 300–2000 ms. The Python app waits for three intervals and averages up to eight.
- SpO₂: each four-sample group is averaged to **25 Hz**. Both channels are then scaled by four before calling the library's **Maxim reference oxygen algorithm** with exactly **100 samples** (four seconds). Updates occur once per second. First acquisition follows the two-second contact settling period.
- SpO₂ gates: contact, unsaturated red/IR, usable peak-to-peak amplitude in both channels, algorithm validity flags, a reference-algorithm pulse within 30–200 bpm, and a returned SpO₂ of 70–100%. A failed gate produces `null`; values are not clamped into a normal range. These gates are basic artifact rejection, not evidence of medical accuracy.
- Breathing movement: `BELT_SOURCE` near the top of the sketch picks the signal, sampled on its own fixed **25 Hz** tick. Every packet carries the latest value as `resp_raw`, and the Python app estimates rate from it.
  - `BELT_IMU` (default): a GY-6500 (MPU-6500) on the belly. Its registers are read directly, because MPU-6050 libraries reject the 6500's `WHO_AM_I` (0x70). The accelerometer runs at ±2 g with a ~5 Hz low-pass. Tilt is `atan2(ax, az)` in degrees. A 30 s moving baseline is subtracted, so sitting or lying back only shifts the baseline. The result is sent as `2048 + 200 × tilt_deg` counts. If a posture change pushes the value past 0–4095, the clamped value is sent once (the app resets on it) and the baseline snaps to the new angle. If the board is missing, an `info` line is printed once, `resp_raw` is `null`, and the firmware retries every second.
  - `BELT_ADC`: the stretch-cord divider; four ADC reads are averaged.
  - `BELT_NONE`: pulse only, `resp_raw: null`.
- `IMU_COUNTS_PER_DEG = 200` is an **estimate**, not a measurement. On synthetic signals with 0.055° rms noise (also an estimate), the app's 30-count minimum swing finds breaths down to about **0.2° peak to peak** of tilt (`tests/test_core.py`). Tune it on the first real recording. Raise it if quiet breaths are missed; lower it if normal breaths hit 0 or 4095.
- USB: approximately **25 packets/s**, plus an immediate packet for every accepted beat. This avoids losing a beat to display decimation. Missing optical hardware still allows belt samples to stream while the firmware retries the optical sensor.

Tune the IR contact threshold or divider only after inspecting real signals. LED current and optical geometry affect the uncalibrated SpO₂ estimate. The upstream calibration table is not a calibration for your particular generic breakout or user.

Sampling gaps clear optical history. The app clears stale values and handles board resets. Timestamps are firmware processing times from `millis()`, not precision ECG acquisition timestamps; do not use these intervals for validated HRV analysis. A FIFO overflow is not a fully characterized operating condition; include long-run sampling checks in hardware validation.

The SparkFun library contains the Maxim reference implementation and its original notices. It is installed by Arduino/PlatformIO and is not vendored or relicensed in this project.
