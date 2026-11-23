# Low-cost budget

Planning ranges in **US dollars**, prepared November 20, 2026 and reorganized into build stages on November 21, 2026. These are approximate component targets, **not live supplier quotes**. Shipping, tax, local currency conversion, 3D printing and tools are excluded. Confirm 3.3 V compatibility and included headers before ordering. The same list with store links and checkboxes is in [`wiring_bom.html`](wiring_bom.html).

Buy one stage at a time. Each stage ends with evidence (photo, trace or comparison) before money goes into the next.

| Stage | Item | Quantity | Target cost | Cost-saving choice |
| --- | --- | ---: | ---: | --- |
| 1 Bench build | ESP32-WROOM-32 DevKit with USB and headers | 1 | $5–9 | Generic original ESP32 board; no display |
| 1 Bench build | MAX30102 breakout with compatible 3.3 V logic | 1 | $3–6 | Preassembled board with documented voltage levels |
| 1 Bench build | Jumper wires, mixed pack | 1 | $1–2 | Reuse existing wires |
| 1 Bench build | USB data cable | 1 | $0–3 | Reuse a known data cable |
| 2 Steady finger | Hook-and-loop strap roll (finger strap, later the belt closure) | 1 | $1–2 | Reuse Velcro you have |
| 2–3 | 3D-printed finger cradle and belt clip | 2 parts | not estimated | Library or makerspace printer |
| 3 Motion belt | GY-6500 board (MPU-6500), I²C 0x68 | 1 | $2–4 | Included in the ELEGOO ESP32 starter kit. A GY-521 (MPU-6050) needs different register code |
| 3 Motion belt | Stranded 4-wire cable, about 1 m | 1 | $1–3 | Twist four long jumper wires |
| 3 Motion belt | Breadboard | 1 | $1–2 | Reuse one |
| 3 Motion belt | Elastic band | 1 | $1–2 | Reuse suitable elastic |
| **Stages 1–3** | | | **$15–33** | |
| 4 Reference | Chest-strap heart-rate monitor with beat-to-beat (RR) output, e.g. Polar H10 | 1 | about $90 | Borrow one |
| Optional | Resistive stretch cord, 1 segment | 1 | $3–7 | Short segment, not a wearable kit |
| Optional | Divider resistor and 100 nF capacitor | 1 set | $1–2 | Reuse parts |

Stage 1 works with `BELT_SOURCE = BELT_NONE` in the firmware. Stage 3 uses the default `BELT_IMU`; its firmware is written but not yet tested on hardware. The optional stretch cord is the original belt design. It is kept as a trade study against the motion sensor, because rubber cord drifts (see F4 in [`engineering_review.md`](engineering_review.md)).

Try the demo for **$0** first. Buy from one supplier when that reduces shipping, and prefer soldered headers if you do not own soldering equipment. A borrowed multimeter is enough for the short-circuit check.

Do not add a battery, charger, OLED, Wi-Fi service or cloud database for the first prototype. None is required for the requested measurements. A validated commercial pulse oximeter for SpO₂ comparison is a separate testing resource, not included in any total; borrow one if available. The prototype does not replace it.
