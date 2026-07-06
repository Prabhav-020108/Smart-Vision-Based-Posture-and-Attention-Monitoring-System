/*
 * PostureGuard - ESP32 Sensor + Buzzer Controller
 * Board  : ESP32 Dev Module
 * Baud   : 9600
 *
 * OUTPUT (existing, now non-blocking):
 *   Active buzzer on GPIO2. The original sketch used delay() to time each
 *   buzz, which blocks the whole MCU for up to ~2 seconds per alert. That
 *   was fine when buzzing was the only job, but it is not fine now that the
 *   sensors below need to be sampled continuously -- so buzzing is now
 *   driven by a small non-blocking state machine (see BuzzPattern) that
 *   times itself against millis() instead of delay().
 *
 * NEW SENSORS:
 *   - MAX30102 pulse sensor over I2C (SDA=GPIO21, SCL=GPIO22) using
 *     SparkFun's "SparkFun MAX3010x Pulse and Proximity Sensor Library"
 *     (install via Arduino Library Manager: search "MAX30105" by SparkFun
 *     Electronics -- that library explicitly supports the MAX30102 too).
 *     Reports an approximate BPM and beat-to-beat interval from a simple
 *     threshold-crossing detector on the IR channel. This is described as
 *     an "HRV proxy" everywhere in this project, not a validated clinical
 *     HRV metric -- a PPG sensor only gives a clean reading with a still
 *     finger, so every reading also carries a 0-100 "quality" figure and a
 *     plausibility check, and nothing is sent at all while no finger is
 *     detected. See README for why it's built this way.
 *   - LDR ambient-light sensor on GPIO34 (ADC1_CH6, input-only, safe pin).
 *
 * SERIAL PROTOCOL:
 *   ESP32 -> Python   HR:<bpm>:<ibi_ms>:<quality0-100>\n   e.g. HR:74:812:85
 *   ESP32 -> Python   LUX:<raw_adc_0_4095>\n                e.g. LUX:2130
 *   Python -> ESP32   one of: PAY ATTENTION / FOCUS ON STUDY /
 *                     CRITICAL DISTRACTION / FIX YOUR POSTURE
 *
 * WIRING:
 *   MAX30102  VIN -> 3.3V   GND -> GND   SDA -> GPIO21   SCL -> GPIO22
 *   LDR       one leg -> 3.3V, other leg -> GPIO34 AND -> GND through a
 *             ~10k resistor (a standard voltage-divider). If your readings
 *             come out backwards (darker room reads a higher number),
 *             that's just this divider's polarity -- swap which leg feeds
 *             GPIO34 and which feeds GND, or flip the sign in
 *             src/sensor_manager.py's brightness_score calculation.
 *   Buzzer    positive -> GPIO2   negative -> GND   (unchanged)
 */

#include <Wire.h>
#include "MAX30105.h"

#define BUZZER_PIN 2
#define LDR_PIN 34

#define FINGER_PRESENT_IR_THRESHOLD 40000UL
#define BEAT_REFRACTORY_MS 280UL          // caps detectable rate at ~214bpm
#define MIN_PLAUSIBLE_BPM 40.0
#define MAX_PLAUSIBLE_BPM 180.0
#define SENSOR_REPORT_INTERVAL_MS 1000UL
#define HR_STALE_AFTER_MS 3000UL          // stop reporting HR if no beat detected recently

MAX30105 particleSensor;
bool sensorReady = false;

unsigned long lastBeatMs = 0;
double lastIbiMs = 0;
double lastBpm = 0;
unsigned long irBaseline = 0;
bool aboveBaseline = false;

unsigned long lastSensorReportMs = 0;

// ---------------------------------------------------------------------------
// Non-blocking buzzer pattern (replaces the original delay()-based buzz())
// ---------------------------------------------------------------------------
struct BuzzPattern {
  int repeatsRemaining = 0;
  unsigned long onMs = 0;
  unsigned long gapMs = 0;
  bool active = false;
  bool inOnPhase = false;
  unsigned long phaseStartedAt = 0;
};
BuzzPattern buzzPattern;

void startBuzzPattern(int repeats, unsigned long onMs, unsigned long gapMs) {
  buzzPattern.repeatsRemaining = repeats;
  buzzPattern.onMs = onMs;
  buzzPattern.gapMs = gapMs;
  buzzPattern.active = true;
  buzzPattern.inOnPhase = true;
  buzzPattern.phaseStartedAt = millis();
  digitalWrite(BUZZER_PIN, HIGH);
}

void updateBuzzPattern() {
  if (!buzzPattern.active) return;
  unsigned long elapsed = millis() - buzzPattern.phaseStartedAt;

  if (buzzPattern.inOnPhase && elapsed >= buzzPattern.onMs) {
    digitalWrite(BUZZER_PIN, LOW);
    buzzPattern.repeatsRemaining--;
    if (buzzPattern.repeatsRemaining <= 0) {
      buzzPattern.active = false;
    } else {
      buzzPattern.inOnPhase = false;
      buzzPattern.phaseStartedAt = millis();
    }
  } else if (!buzzPattern.inOnPhase && elapsed >= buzzPattern.gapMs) {
    digitalWrite(BUZZER_PIN, HIGH);
    buzzPattern.inOnPhase = true;
    buzzPattern.phaseStartedAt = millis();
  }
}

void handleAlertMessage(const String &message) {
  Serial.print("Received: ");
  Serial.println(message);

  if (message == "PAY ATTENTION") {
    startBuzzPattern(1, 500, 0);
  } else if (message == "FOCUS ON STUDY") {
    startBuzzPattern(2, 500, 200);
  } else if (message == "CRITICAL DISTRACTION") {
    startBuzzPattern(3, 400, 150);
  } else if (message == "FIX YOUR POSTURE") {
    startBuzzPattern(1, 800, 0);
  }
}

// ---------------------------------------------------------------------------
// MAX30102 -- simple threshold-crossing beat detector
// ---------------------------------------------------------------------------
void updateHeartRate() {
  if (!sensorReady) return;

  long irValue = particleSensor.getIR();
  bool fingerPresent = irValue > (long)FINGER_PRESENT_IR_THRESHOLD;

  if (!fingerPresent) {
    aboveBaseline = false;
    return;
  }

  // Slow-moving baseline (simple exponential low-pass) so we detect the
  // rising edge of each pulse rather than reacting to the much larger,
  // roughly-constant IR offset caused by the finger just sitting there.
  if (irBaseline == 0) {
    irBaseline = irValue;
  } else {
    irBaseline = (irBaseline * 15 + irValue) / 16;
  }

  bool nowAboveBaseline = irValue > (long)(irBaseline + irBaseline / 100 + 200);

  if (nowAboveBaseline && !aboveBaseline) {
    unsigned long now = millis();
    unsigned long sinceLastBeat = now - lastBeatMs;

    if (lastBeatMs != 0 && sinceLastBeat >= BEAT_REFRACTORY_MS) {
      lastIbiMs = sinceLastBeat;
      lastBpm = 60000.0 / lastIbiMs;
    }
    lastBeatMs = now;
  }
  aboveBaseline = nowAboveBaseline;
}

int estimateHrQuality(double bpm) {
  if (bpm < MIN_PLAUSIBLE_BPM || bpm > MAX_PLAUSIBLE_BPM) return 30;
  return 85;
}

void reportSensors() {
  unsigned long now = millis();
  if (now - lastSensorReportMs < SENSOR_REPORT_INTERVAL_MS) return;
  lastSensorReportMs = now;

  bool fingerPresent = sensorReady && particleSensor.getIR() > (long)FINGER_PRESENT_IR_THRESHOLD;
  bool beatIsRecent = (lastBeatMs != 0) && (now - lastBeatMs < HR_STALE_AFTER_MS);

  if (fingerPresent && beatIsRecent && lastBpm > 0) {
    int quality = estimateHrQuality(lastBpm);
    Serial.print("HR:");
    Serial.print((int)round(lastBpm));
    Serial.print(":");
    Serial.print((int)round(lastIbiMs));
    Serial.print(":");
    Serial.println(quality);
  }
  // If there's no reliable reading right now, we simply send nothing for
  // HR this cycle rather than sending a stale or made-up number -- the
  // Python side treats "no recent line" as "no reliable signal".

  int rawLight = analogRead(LDR_PIN);
  Serial.print("LUX:");
  Serial.println(rawLight);
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(9600);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(LDR_PIN, INPUT);

  Wire.begin();
  sensorReady = particleSensor.begin(Wire, I2C_SPEED_FAST);
  if (sensorReady) {
    // powerLevel, sampleAverage, ledMode(2=Red+IR), sampleRate, pulseWidth, adcRange
    particleSensor.setup(60, 4, 2, 100, 411, 4096);
  } else {
    Serial.println("MAX30102 not detected -- HR readings disabled, everything else continues.");
  }

  Serial.println("PostureGuard ESP32 Ready");
}

void loop() {
  updateBuzzPattern();
  updateHeartRate();
  reportSensors();

  if (Serial.available() > 0) {
    String message = Serial.readStringUntil('\n');
    message.trim();
    handleAlertMessage(message);
  }
}
