# USB serial protocol, version 1

115200 baud, 8 data bits, no parity, 1 stop bit. UTF-8 JSON, one object per newline. Approximately 25 sample packets/s plus accepted beat events. Boot messages and non-sample JSON may appear; clients must tolerate them.

```json
{"type":"sample","v":1,"t_ms":12000,"ir":90000,"red":72000,"finger":true,"beat":true,"ibi_ms":860,"spo2":97,"resp_raw":2048}
```

| Field | Meaning |
| --- | --- |
| `type` | `sample`, `info`, or `error` |
| `v` | Integer protocol version, currently 1 |
| `t_ms` | Unsigned 32-bit firmware `millis()` at processing/output time |
| `ir`, `red` | Raw 18-bit optical counts, 0–262143; zero if optical hardware is unavailable |
| `finger` | Boolean contact heuristic from IR threshold/saturation; not a quality certification |
| `beat` | Boolean; true only for a newly accepted pulse interval |
| `ibi_ms` | 300–2000 ms on an accepted beat; otherwise `null` |
| `spo2` | Experimental integer oxygen estimate 70–100%, or `null`; updated about once/second and repeated in packets |
| `resp_raw` | Breathing movement, 0–4095, or `null` when the belt is off or missing. GY-6500 mode: `2048 + 200 × (belly tilt − 30 s baseline)` in degrees, clamped. Stretch-cord mode: averaged 12-bit ADC reading |

SpO₂ must be `null` when `finger` is false. Values outside the implemented 70–100% range are unavailable, not clipped. `resp_raw` remains meaningful when optical contact is absent. The Python parser also accepts omitted `spo2` and `resp_raw` as unavailable for compatibility with pulse-only clients.

```json
{"type":"info","v":1,"message":"MAX30102 ready; acquisition 100 Hz, USB about 25 Hz"}
{"type":"error","v":1,"message":"MAX30102 not found at 0x57; check 3V3, GND, SDA and SCL"}
{"type":"info","v":1,"message":"GY-6500 not found at 0x68/0x69; check 3V3, GND, SDA and SCL"}
```

A missing GY-6500 is reported as `info`, not `error`, because the desktop resets pulse history on every `error` packet. The `null` `resp_raw` already blanks the breathing rate.

Packets contain measurements and status only; the firmware accepts no serial commands. The breathing target stays in the desktop app. Breathing rate is calculated from `resp_raw`, never from guide timing, LED timing, or a presumed coupling between pulse and breathing.

The desktop treats more than one second without samples as stale, requires three accepted intervals before showing pulse, and clears pulse history after three seconds without a beat or on any `error` packet. Its message is shown as plain text. The desktop runs its algorithms on `t_ms`, mapped onto host time, because USB delivers lines in bursts. Board resets clear desktop measurement history; natural unsigned timestamp wrap is tolerated. Data is not an ECG stream and is not suitable for validated HRV analysis.
