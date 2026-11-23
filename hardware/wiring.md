# Hardware and wiring

Visual version with the wiring diagram, desk setup and a tick-off shopping list: open [`docs/wiring_bom.html`](../docs/wiring_bom.html) in a browser.

## Choose compatible parts first

- **Original ESP32 DevKit / ESP32-WROOM-32 development board** with USB, regulator and soldered headers. This pin map is not for ESP32-C3/S3 boards.
- **MAX30102 breakout**, not the bare chip, with documented **3.3 V input supply and ESP32-compatible 3.3 V I²C logic**. Buy a preassembled board with a schematic or clear vendor documentation. Generic modules differ.
- **GY-6500 board (MPU-6500 accelerometer/gyro)** for the breathing belt, plus an elastic strap and about 1 m of 4-wire cable. A GY-521 (MPU-6050) is **not** a drop-in: it reports a different `WHO_AM_I` and the firmware will not find it.
- Optional trade study instead of the GY-6500: a **resistive stretch sensor** (conductive rubber cord), a fixed resistor close to its relaxed resistance (initially **10 kΩ**) and one **100 nF capacitor**.

The bare MAX30102 has a 1.8 V core supply and a separate LED supply. A breakout's `VIN` label alone does **not** establish its logic levels. Some boards pull SDA/SCL to 1.8 V; others can pull them to 5 V. For this design, choose a breakout that explicitly supports 3.3 V I²C. If you already own a different breakout, follow its schematic and add the required level shifter instead of connecting it blindly. ESP32 GPIO pins are not 5 V tolerant.

## MAX30102 connections

Disconnect USB while wiring. The ESP32 is powered from its USB cable.

| ESP32 DevKit label | MAX30102 breakout label | Purpose |
| --- | --- | --- |
| `3V3` | documented 3.3 V supply input, commonly `VIN` or `VCC` | Power |
| `GND` | `GND` | Common ground |
| `GPIO21` / `21` | `SDA` | I²C data |
| `GPIO22` / `22` | `SCL` | I²C clock |
| No connection | `INT` | Not used by this firmware |

The expected I²C address is **0x57**. Keep wires short, about 10–20 cm where practical. Use the breakout's installed I²C pull-ups if they are appropriate for 3.3 V. Do not add parallel pull-ups without checking the board.

## GY-6500 breathing belt (default)

The GY-6500 shares the four I²C lines with the MAX30102. Its address, 0x68, does not clash with the MAX30102's 0x57.

| ESP32 DevKit label | GY-6500 label | Purpose |
| --- | --- | --- |
| `3V3` | `VCC` | Power, 3.3 V only |
| `GND` | `GND` | Common ground |
| `GPIO21` | `SDA` | I²C data, shared |
| `GPIO22` | `SCL` | I²C clock, shared |
| No connection | `AD0`/`SDO`, `NCS`, `INT`, `FSYNC`, `EDA`, `ECL` | Not used. The firmware also tries 0x69 in case `AD0` is pulled high |

ASSUMPTION, not yet checked on this board: `NCS` is pulled high on the board so the chip stays in I²C mode. If the Serial Monitor shows `GY-6500 not found`, check the wiring first, then try tying `NCS` to 3V3.

**Wearing it:**

1. Lay the board flat on the belly, just above the navel, over a thin shirt. Chip side facing out, the board's **X axis (printed arrow) pointing toward the head**. Hold it there with the elastic strap, snug but not tight.
2. Breathing tilts the board forward and back about its left-right (Y) axis. The firmware sends that tilt angle, so sitting upright and lying back both work.
3. After changing position, the firmware re-centres within one sample. The app then calibrates again for 20 s.
4. Run the 1 m cable with strain relief to the desk. Long I²C wires at the library's 400 kHz clock can fail. ASSUMPTION: 1 m works with the boards' own pull-ups; if readings drop out, shorten the cable.

Set `BELT_SOURCE` near the top of the sketch: `BELT_IMU` (default), `BELT_ADC` for the stretch cord below, or `BELT_NONE` for pulse only.

## Stretch-cord divider (optional trade study, `BELT_ADC`)

```text
ESP32 3V3 ─── resistive stretch sensor ───┬──── GPIO34 (ADC1)
                                         │
                                         ├──── 10 kΩ fixed resistor ─── GND
                                         │
                                         └──── 100 nF capacitor ─────── GND

ESP32 USB ─── computer
```

GPIO34 is an input-only ADC pin and has no internal pull-up/pull-down. **Keep the fixed resistor installed**, including when the stretch sensor is disconnected. It prevents the ADC input from floating. The capacitor reduces electrical noise; it is not a substitute for the resistor. All sensor supply connections are to **3V3**, never to USB 5 V or `VIN` on the ESP32.

For this divider, `V_ADC = 3.3 × R_fixed / (R_stretch + R_fixed)`. Choose `R_fixed` near the relaxed sensor resistance, ideally putting the resting voltage around 1–2 V. If your cord is 30 kΩ at rest, a 33 kΩ fixed resistor is a better starting point than 10 kΩ. An inexpensive multimeter is useful; borrow one if possible. ESP32 ADC counts are not an accurate voltage or respiratory-volume measurement.

The app rejects raw counts below 100 or above 4000, and requires at least 30 counts of movement across its adaptive range. Inspect `resp_raw` in a CSV if readings remain blank. A disconnected stretch sensor should pull the input toward zero through the fixed resistor; a shorted sensor drives it high. Neither should display a breathing rate.

## Make and fit the stretch-cord belt

1. Put a short stretch-sensor segment in series mechanically with an elastic strap, so chest expansion gently stretches the sensor. Follow the sensor's maximum elongation specification.
2. Make secure mechanical/electrical connections using the vendor's recommended crimps or clips. Conductive rubber generally cannot be soldered directly. Insulate metal joints and add strain relief to the leads.
3. Wear the strap **over clothing**, around the lower chest or upper abdomen. It should follow movement without restricting breathing and be easy to remove. No conductive contact with skin is needed.
4. Leave enough cable slack for normal movement. Support the ESP32 and breadboard on the desk rather than hanging them from the belt.
5. Sit comfortably and let the software collect 20 seconds of movement, then three complete cycles. Either signal polarity is supported. Reconnect the USB source to restart calibration after changing the fit.

The prototype counts cyclic chest expansion; it cannot verify airflow or detect obstructed breathing. Motion and shifting posture can resemble breaths. Test while sitting still, then document how movement affects it.

## Optical sensor placement

Rest the fleshy fingertip lightly over the LEDs and photodiode. Support the hand to reduce motion and shield the sensor from strong ambient light with a loose opaque cover. Do not clamp tightly enough to alter circulation. The red LED should be visible; the infrared LED is not visible to the eye.

Firmware defaults use 100 samples/s and an initial contact threshold of 50,000 IR counts. The threshold is a starting value, not a universal calibration. Compare `ir` readings with and without a finger. If needed, tune `CONTACT_MIN_IR` and LED current after checking wiring and placement. Avoid near-saturated values around 250,000 counts. Contact detection does not prove signal quality.

## First power-on

1. Check polarity and ensure there is no short between 3V3 and GND.
2. Connect USB and upload the firmware.
3. Open Serial Monitor at 115200 baud. Look for the ready message and JSON samples. An optical sensor error does not stop the belt channel from streaming.
4. Check that `finger` changes with contact; `spo2` is initially `null` and only becomes numeric after a usable window; `resp_raw` sits near 2048 when still (GY-6500) and moves smoothly as you breathe or stretch the belt. Look for the `GY-6500 ready at 0x68` line at boot.
5. Close Serial Monitor before connecting the Python app.

## References

- [Analog Devices MAX30102 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX30102.pdf)
- [SparkFun MAX3010x library and examples](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library)
- [Espressif ESP32 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf)

Use the actual breakout supplier's schematic in addition to the chip datasheet.
