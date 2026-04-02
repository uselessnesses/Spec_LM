/*
 * speculative_ai.ino
 * VERSION: 002 (2026-04-02)
 * ---------------------------------------------------------
 * Build Your Speculative AI Company — Arduino Mega sketch
 *
 * Dual role:
 *   1. Sensor reader: continuously sends A0,A1,A4 over USB serial
 *      so the Flask app can drive the three on-screen controls.
 *   2. Thermal printer: receives print commands from Flask and
 *      sends them to a 58mm Adafruit-style thermal printer via
 *      SoftwareSerial on pins 5 (RX) and 6 (TX).
 *
 * Wiring
 * ──────
 * Knob 1 wiper  → A0      (left control on each screen)
 * Knob 2 wiper  → A1      (right control on each screen)
 * Slider wiper  → A4      (bottom control on each screen)
 * Printer TX    → Pin 5   (Arduino RX ← printer TX)
 * Printer RX    → Pin 6   (Arduino TX → printer RX)
 * Printer GND   ──┬── External PSU GND
 * Arduino GND   ──┘
 * Printer power → External 5V 2A supply (NOT Arduino 5V)
 *
 * Print command protocol (computer → Arduino via USB serial)
 * ───────────────────────────────────────────────────────────
 *   PRINT_START          enter print mode, wake printer
 *   TEXT:<line>          print one line of text
 *   BOLD_ON / BOLD_OFF   toggle bold
 *   SIZE:S / SIZE:M / SIZE:L   set font size
 *   ALIGN:C / ALIGN:L    centre or left justify
 *   DIVIDER              print a full-width dashed line
 *   SCORE:<n>            print 64×64 score-dial bitmap (n = 1..10)
 *   FEED:<n>             feed n blank lines
 *   PRINT_END            feed 4 lines, sleep printer, exit print mode
 *
 * Arduino acknowledges every non-empty command with:
 *   ACK
 *
 * Libraries required (install via Arduino Library Manager)
 * ──────────────────────────────────────────────────────────
 *   Adafruit Thermal Printer Library
 */

#include <SoftwareSerial.h>
#include <Adafruit_Thermal.h>
#include "bitmaps.h"

// ── Printer serial ────────────────────────────────────────────────────────────
// Pin 5 = Arduino RX  ← printer TX (usually green wire)
// Pin 6 = Arduino TX  → printer RX (usually yellow wire)
SoftwareSerial printerSerial(5, 6);
Adafruit_Thermal printer(&printerSerial);

// ── State ─────────────────────────────────────────────────────────────────────
bool   printing  = false;
String inputBuf  = "";

// Sensor timing
unsigned long lastSensorSend = 0;
const unsigned long SENSOR_INTERVAL_MS = 50;


// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  printerSerial.begin(19200);
  printer.begin();
  printer.sleep();   // start in sleep mode; wake on PRINT_START
}


// ── Main loop ─────────────────────────────────────────────────────────────────
void loop() {
  // Non-blocking serial read — buffer chars until newline
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      inputBuf.trim();
      if (inputBuf.length() > 0) {
        handleCommand(inputBuf);
        Serial.println("ACK");
      }
      inputBuf = "";
    } else if (c != '\r') {
      inputBuf += c;
    }
  }

  // Send sensor data when not printing
  if (!printing) {
    unsigned long now = millis();
    if (now - lastSensorSend >= SENSOR_INTERVAL_MS) {
      lastSensorSend = now;
      Serial.print(analogRead(A0));
      Serial.print(",");
      Serial.print(analogRead(A1));
      Serial.print(",");
      Serial.println(analogRead(A4));
    }
  }
}


// ── Command handler ───────────────────────────────────────────────────────────
void handleCommand(const String& cmd) {

  // ── Mode control (always accepted) ──────────────────────────────────────────
  if (cmd == "PRINT_START") {
    printing = true;
    printer.wake();
    printer.setDefault();
    return;
  }

  if (cmd == "PRINT_END") {
    printer.feed(4);
    printer.sleep();
    printing = false;
    return;
  }

  // All other commands require print mode to be active
  if (!printing) return;

  // ── Text / formatting ────────────────────────────────────────────────────────
  if (cmd.startsWith("TEXT:")) {
    printer.println(cmd.substring(5));

  } else if (cmd == "BOLD_ON") {
    printer.boldOn();

  } else if (cmd == "BOLD_OFF") {
    printer.boldOff();

  } else if (cmd.startsWith("SIZE:")) {
    char s = cmd.charAt(5);
    if (s == 'S' || s == 'M' || s == 'L') printer.setSize(s);

  } else if (cmd.startsWith("ALIGN:")) {
    char a = cmd.charAt(6);
    if      (a == 'C') printer.justify('C');
    else if (a == 'R') printer.justify('R');
    else               printer.justify('L');

  } else if (cmd == "DIVIDER") {
    printer.println("--------------------------------");

  // ── Paper feed ───────────────────────────────────────────────────────────────
  } else if (cmd.startsWith("FEED:")) {
    int n = cmd.substring(5).toInt();
    if (n > 0 && n <= 20) printer.feed(n);

  // ── Score dial bitmap ─────────────────────────────────────────────────────────
  } else if (cmd.startsWith("SCORE:")) {
    int s = cmd.substring(6).toInt();
    if (s >= 1 && s <= 10) {
      const uint8_t* bmp = (const uint8_t*)pgm_read_ptr(&score_bitmaps[s - 1]);
      printer.printBitmap(DIAL_SIZE, DIAL_SIZE, bmp, true);
    }
  }
}
