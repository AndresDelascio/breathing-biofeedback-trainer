/*
 * ESP32 DevKit + MAX30102 breakout, USB serial protocol v1.
 * SparkFun's MAX30105 class also supports the MAX30102 (red + IR only).
 * Pulse + experimental SpO2 + breathing movement (GY-6500 belly tilt or analog belt).
 * Educational prototype: SpO2 is uncalibrated; no medical accuracy claims.
 */
#include <Arduino.h>
#include <Wire.h>
#include <MAX30105.h>
#include <heartRate.h>
#include <spo2_algorithm.h>

constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t CONTACT_MIN_IR = 50000;  // Tune for the actual breakout.
constexpr uint32_t SATURATED_IR = 250000;  // 18-bit ADC approaches 262143.
constexpr uint32_t CONTACT_SETTLE_MS = 2000;
constexpr uint32_t OUTPUT_PERIOD_MS = 40;  // ~25 Hz, plus every accepted beat.
constexpr int OXYGEN_WINDOW = 100;  // Maxim algorithm requires 100 samples at 25 Hz.

// Breathing signal, sent as resp_raw. IMU: GY-6500 (MPU-6500) strapped flat on the belly,
// X axis toward the head. ADC: stretch-cord divider on GPIO34 (trade study). NONE: pulse only.
enum BeltSource { BELT_NONE, BELT_ADC, BELT_IMU };
constexpr BeltSource BELT_SOURCE = BELT_IMU;
constexpr uint32_t BELT_PERIOD_MS = 40;       // Fixed 25 Hz belt sampling, independent of beats.
constexpr int RESP_PIN = 34;                  // ADC mode: original ESP32 ADC1; see hardware/wiring.md.
constexpr float IMU_COUNTS_PER_DEG = 200.0f;  // resp_raw counts per degree of tilt. ESTIMATE: tune on the first recording.
constexpr float IMU_BASELINE_TAU_S = 30.0f;   // Slow posture baseline removed from tilt; >99% gain at 4–40 breaths/min.
constexpr int RESP_CENTRE = 2048;             // resp_raw when tilt equals its baseline.

uint32_t oxygenIR[OXYGEN_WINDOW];
uint32_t oxygenRed[OXYGEN_WINDOW];
int oxygenCount = 0;
uint32_t irSum = 0;
uint32_t redSum = 0;
int averageCount = 0;
int32_t oxygenPercent = -1;
uint32_t oxygenUpdated = 0;

MAX30105 sensor;
bool sensorReady = false;
bool contact = false;
bool haveBeat = false;
uint32_t contactSince = 0;
uint32_t lastBeat = 0;
uint32_t lastOutput = 0;
uint32_t lastSample = 0;
uint32_t lastAttempt = 0;

uint8_t imuAddress = 0;       // 0 = GY-6500 not found
bool imuMissingReported = false;
float tiltBaselineDeg = NAN;
int32_t beltValue = -1;       // Latest resp_raw; -1 sends null.
uint32_t lastBelt = 0;
uint32_t lastImuAttempt = 0;

void clearPulse() {
  haveBeat = false;
  lastBeat = 0;
}

void clearOxygen() {
  oxygenCount = 0;
  averageCount = 0;
  irSum = redSum = 0;
  oxygenPercent = -1;
}

bool usableOpticalWindow(uint32_t *values) {
  uint32_t low = values[0], high = values[0], total = 0;
  for (int i = 0; i < OXYGEN_WINDOW; ++i) {
    low = min(low, values[i]);
    high = max(high, values[i]);
    total += values[i];
  }
  const float mean = total / static_cast<float>(OXYGEN_WINDOW);
  // Basic weak-signal / large-motion rejection, not a validated quality score.
  return mean > 1000 && high - low >= 50 && high - low <= mean * 0.10f;
}

void updateOxygen(uint32_t now, uint32_t ir, uint32_t red) {
  if (!contact || red < 1000 || red >= SATURATED_IR ||
      static_cast<uint32_t>(now - contactSince) < CONTACT_SETTLE_MS) {
    clearOxygen();
    return;
  }
  irSum += ir;
  redSum += red;
  if (++averageCount < 4) return;
  // Average 100 Hz -> 25 Hz, then scale BOTH channels equally by four to
  // keep the upstream algorithm's signed 32-bit intermediate products bounded.
  oxygenIR[oxygenCount] = irSum / 16;
  oxygenRed[oxygenCount] = redSum / 16;
  averageCount = 0;
  irSum = redSum = 0;
  if (++oxygenCount < OXYGEN_WINDOW) return;

  int32_t candidate = -999, heartRate = -999;
  int8_t validOxygen = 0, validHeartRate = 0;
  if (usableOpticalWindow(oxygenIR) && usableOpticalWindow(oxygenRed)) {
    maxim_heart_rate_and_oxygen_saturation(oxygenIR, OXYGEN_WINDOW, oxygenRed,
        &candidate, &validOxygen, &heartRate, &validHeartRate);
  }
  oxygenPercent = (validOxygen && validHeartRate && heartRate >= 30 && heartRate <= 200 &&
                   candidate >= 70 && candidate <= 100) ? candidate : -1;
  oxygenUpdated = now;
  // Sliding four-second window: update once per second.
  memmove(oxygenIR, oxygenIR + 25, 75 * sizeof(uint32_t));
  memmove(oxygenRed, oxygenRed + 25, 75 * sizeof(uint32_t));
  oxygenCount = 75;
}

bool beginSensor() {
  if (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("{\"type\":\"error\",\"v\":1,\"message\":\"MAX30102 not found at 0x57; check 3V3, GND, SDA and SCL\"}");
    return false;
  }
  // LED current, averaging, red+IR, ADC samples/s, pulse width us, ADC range nA.
  // Average=1 and rate=100 deliver 100 samples/s to the pulse detector.
  sensor.setup(0x1F, 1, 2, 100, 411, 4096);
  sensor.setPulseAmplitudeGreen(0);  // MAX30102 has no green LED.
  sensor.clearFIFO();
  contact = false;
  clearPulse();
  clearOxygen();
  lastSample = millis();
  Serial.println("{\"type\":\"info\",\"v\":1,\"message\":\"MAX30102 ready; acquisition 100 Hz, USB about 25 Hz\"}");
  return true;
}

// MPU-6500 registers by hand: MPU-6050 libraries reject its WHO_AM_I (0x70, not 0x68).
bool imuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool imuRead(uint8_t reg, uint8_t *data, uint8_t count) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(imuAddress, count) != count) return false;
  for (uint8_t i = 0; i < count; ++i) data[i] = Wire.read();
  return true;
}

bool beginImu() {
  for (uint8_t address : {0x68, 0x69}) {  // AD0 low, then AD0 high.
    imuAddress = address;
    uint8_t id = 0;
    if (imuRead(0x75, &id, 1) && id == 0x70 &&  // WHO_AM_I
        imuWrite(0x6B, 0x01) &&                 // PWR_MGMT_1: wake, best clock
        imuWrite(0x1C, 0x00) &&                 // ACCEL_CONFIG: ±2 g
        imuWrite(0x1D, 0x06)) {                 // ACCEL_CONFIG2: ~5 Hz low-pass; breaths are <0.7 Hz
      tiltBaselineDeg = NAN;
      imuMissingReported = false;
      Serial.printf("{\"type\":\"info\",\"v\":1,\"message\":\"GY-6500 ready at 0x%02X; belly tilt 25 Hz\"}\n", address);
      return true;
    }
  }
  imuAddress = 0;
  // Info, not error: firmware errors reset the app's pulse history; a null resp_raw already blanks breathing.
  if (!imuMissingReported) {
    Serial.println("{\"type\":\"info\",\"v\":1,\"message\":\"GY-6500 not found at 0x68/0x69; check 3V3, GND, SDA and SCL\"}");
    imuMissingReported = true;
  }
  return false;
}

void updateBelt() {
  if (BELT_SOURCE == BELT_ADC) {
    uint32_t raw = 0;
    for (int i = 0; i < 4; ++i) raw += analogRead(RESP_PIN);
    beltValue = raw / 4;
    return;
  }
  uint8_t data[6];
  if (!imuAddress || !imuRead(0x3B, data, 6)) {  // ACCEL_XOUT_H..ACCEL_ZOUT_L, big-endian
    imuAddress = 0;  // Unplugged mid-session: retry once a second.
    beltValue = -1;
    return;
  }
  const float ax = static_cast<int16_t>(data[0] << 8 | data[1]);
  const float az = static_cast<int16_t>(data[4] << 8 | data[5]);
  // Rotation about the board's Y axis. atan2 stays accurate whether gravity is
  // on X (sitting) or Z (lying back), so posture only moves the baseline.
  const float tiltDeg = atan2f(ax, az) * RAD_TO_DEG;
  if (isnan(tiltBaselineDeg)) tiltBaselineDeg = tiltDeg;
  tiltBaselineDeg += (BELT_PERIOD_MS / (IMU_BASELINE_TAU_S * 1000.0f)) * (tiltDeg - tiltBaselineDeg);
  const float counts = RESP_CENTRE + (tiltDeg - tiltBaselineDeg) * IMU_COUNTS_PER_DEG;
  // Posture change: send the clamped value (the app resets on it), then re-centre.
  if (counts < 0 || counts > 4095) tiltBaselineDeg = tiltDeg;
  beltValue = constrain(lroundf(counts), 0L, 4095L);
}

void serviceBelt(uint32_t now) {
  if (BELT_SOURCE == BELT_NONE || static_cast<uint32_t>(now - lastBelt) < BELT_PERIOD_MS) return;
  lastBelt = now;
  if (BELT_SOURCE == BELT_IMU && !imuAddress && static_cast<uint32_t>(now - lastImuAttempt) >= 1000) {
    lastImuAttempt = now;
    beginImu();
  }
  updateBelt();
}

void sendSample(uint32_t now, uint32_t ir, uint32_t red, bool beat, uint32_t interval) {
  char ibiText[12];
  if (beat) {
    snprintf(ibiText, sizeof(ibiText), "%lu", static_cast<unsigned long>(interval));
  } else {
    strcpy(ibiText, "null");
  }
  char oxygenText[12], respText[12];
  if (contact && oxygenPercent >= 0 && static_cast<uint32_t>(now - oxygenUpdated) <= 2000) {
    snprintf(oxygenText, sizeof(oxygenText), "%ld", static_cast<long>(oxygenPercent));
  } else {
    strcpy(oxygenText, "null");
  }
  if (beltValue >= 0) {
    snprintf(respText, sizeof(respText), "%ld", static_cast<long>(beltValue));
  } else {
    strcpy(respText, "null");
  }
  Serial.printf("{\"type\":\"sample\",\"v\":1,\"t_ms\":%lu,\"ir\":%lu,\"red\":%lu,\"finger\":%s,\"beat\":%s,\"ibi_ms\":%s,\"spo2\":%s,\"resp_raw\":%s}\n",
                static_cast<unsigned long>(now), static_cast<unsigned long>(ir),
                static_cast<unsigned long>(red), contact ? "true" : "false",
                beat ? "true" : "false", ibiText, oxygenText, respText);
  lastOutput = now;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setTimeOut(50);
  if (BELT_SOURCE == BELT_ADC) {
    pinMode(RESP_PIN, INPUT);
    analogReadResolution(12);
    analogSetPinAttenuation(RESP_PIN, ADC_11db);
  }
  delay(300);
  sensorReady = beginSensor();
  lastAttempt = millis();
  if (BELT_SOURCE == BELT_IMU) {
    beginImu();
    lastImuAttempt = millis();
  }
}

void loop() {
  uint32_t now = millis();
  serviceBelt(now);  // Runs even while the optical sensor is missing.
  if (!sensorReady) {
    contact = false;
    clearOxygen();
    if (static_cast<uint32_t>(now - lastOutput) >= OUTPUT_PERIOD_MS) sendSample(now, 0, 0, false, 0);
    if (static_cast<uint32_t>(now - lastAttempt) >= 1000) {
      lastAttempt = now;
      sensorReady = beginSensor();
    }
    delay(2);
    return;
  }

  sensor.check();
  while (sensor.available()) {
    now = millis();
    uint32_t ir = sensor.getFIFOIR();
    uint32_t red = sensor.getFIFORed();
    sensor.nextSample();
    if (static_cast<uint32_t>(now - lastSample) > 100) {
      contact = false;
      clearPulse();
      clearOxygen();
      Serial.println("{\"type\":\"error\",\"v\":1,\"message\":\"Sampling gap; reacquiring pulse\"}");
    }
    lastSample = now;

    // Run continuously to let the library's filter settle after contact changes.
    bool detected = checkForBeat(static_cast<int32_t>(ir));
    bool present = ir >= CONTACT_MIN_IR && ir < SATURATED_IR;
    if (!present) {
      contact = false;
      clearPulse();
    } else if (!contact) {
      contact = true;
      contactSince = now;
      clearPulse();
    }

    bool accepted = false;
    uint32_t interval = 0;
    if (haveBeat && static_cast<uint32_t>(now - lastBeat) > 2500) clearPulse();
    if (contact && static_cast<uint32_t>(now - contactSince) >= CONTACT_SETTLE_MS && detected) {
      if (!haveBeat) {
        lastBeat = now;
        haveBeat = true;
      } else {
        interval = static_cast<uint32_t>(now - lastBeat);
        if (interval >= 300) {
          lastBeat = now;
          accepted = interval <= 2000;  // Prototype range: 30–200 bpm.
        }
      }
    }
    updateOxygen(now, ir, red);
    // Send beat events immediately so decimation never hides an accepted beat.
    if (accepted || static_cast<uint32_t>(now - lastOutput) >= OUTPUT_PERIOD_MS) {
      sendSample(now, ir, red, accepted, interval);
    }
  }
  if (static_cast<uint32_t>(millis() - lastSample) > 1500) {
    sensorReady = false;
    contact = false;
    clearPulse();
    clearOxygen();
    Serial.println("{\"type\":\"error\",\"v\":1,\"message\":\"Sensor stopped delivering samples; retrying\"}");
  }
  delay(1);
}
