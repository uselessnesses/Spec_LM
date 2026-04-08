/*
 * paper_trail.ino
 * VERSION: 008 (2026-04-08)
 * ---------------------------------------------------------
 * Paper Trail — Arduino Mega sketch
 *
 * Dual role:
 *   1. Sensor reader: continuously sends A0,A1,A4 and 3 button states
 *      over USB serial so the Flask app can drive controls + navigation.
 *   2. Thermal printer: receives print commands from Flask and
 *      sends them to a 58mm Adafruit-style thermal printer via
 *      SoftwareSerial on pins 5 (RX) and 6 (TX).
 *
 * Wiring
 * ──────
 * Knob 1 wiper  → A0      (left control on each screen)
 * Knob 2 wiper  → A1      (right control on each screen)
 * Slider wiper  → A4      (bottom control on each screen)
 * Back button   → D7      (to GND when pressed; INPUT_PULLUP)
 * Next button   → D8      (to GND when pressed; INPUT_PULLUP)
 * Reset button  → D9      (to GND when pressed; INPUT_PULLUP)
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
 *   SCORE:<n>            print enlarged score dial (n = 1..10)
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

// Navigation buttons (active-low with INPUT_PULLUP)
const uint8_t BTN_BACK_PIN  = 7;
const uint8_t BTN_NEXT_PIN  = 8;
const uint8_t BTN_RESET_PIN = 9;

// Sensor timing
unsigned long lastSensorSend = 0;
const unsigned long SENSOR_INTERVAL_MS = 50;

// Score bitmap scaling: keep source bitmaps at 128x128 in flash, print 2x in both
// directions (256x256) while using a small strip buffer in SRAM for speed.
const uint16_t DIAL_SRC_W = DIAL_SIZE;
const uint16_t DIAL_SRC_H = DIAL_SIZE;
const uint8_t  DIAL_SCALE = 2;
const uint16_t DIAL_PRINT_W = DIAL_SRC_W * DIAL_SCALE;
const uint16_t DIAL_PRINT_H = DIAL_SRC_H * DIAL_SCALE;
const uint16_t DIAL_ROW_BYTES_SRC = (DIAL_SRC_W + 7) / 8;
const uint16_t DIAL_ROW_BYTES_DST = (DIAL_PRINT_W + 7) / 8;
const uint8_t  DIAL_STRIP_ROWS = 16;
uint8_t scoreScaledStripBuf[DIAL_ROW_BYTES_DST * DIAL_STRIP_ROWS];


// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  printerSerial.begin(19200);
  pinMode(BTN_BACK_PIN, INPUT_PULLUP);
  pinMode(BTN_NEXT_PIN, INPUT_PULLUP);
  pinMode(BTN_RESET_PIN, INPUT_PULLUP);
  printer.begin();
  printer.sleep();   // start in sleep mode; wake on PRINT_START
}


// ── Divider helpers ───────────────────────────────────────────────────────────
bool isDividerCandidate(const String& s) {
  if (s.length() < 8) return false;
  for (int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c != '-' && c != '=' && c != '_') return false;
  }
  return true;
}

void printDividerLine() {
  // 32 chars wide on common 58mm printers at small size.
  printer.println("================================");
}

void applyPrinterQualityPreset() {
  // ESC 7 n1 n2 n3 : heat config (max dots, heat time, heat interval).
  printerSerial.write((uint8_t)27);
  printerSerial.write((uint8_t)55);
  printerSerial.write((uint8_t)11);
  printerSerial.write((uint8_t)150);
  printerSerial.write((uint8_t)30);

  // DC2 # n : print density and break time.
  // n = (breakTime << 5) | density
  printerSerial.write((uint8_t)18);
  printerSerial.write((uint8_t)35);
  printerSerial.write((uint8_t)((2 << 5) | 15));
}

uint16_t expandByte2x(uint8_t b) {
  // Expand 8 source pixels into 16 pixels by duplicating each bit horizontally.
  uint16_t out = 0;
  for (uint8_t i = 0; i < 8; i++) {
    if (b & (0x80 >> i)) out |= (uint16_t)0x3 << (14 - (i * 2));
  }
  return out;
}

void expandSourceRow2x(const uint8_t* bmp, uint16_t ySrc, uint8_t* dstRow) {
  const uint16_t srcBase = ySrc * DIAL_ROW_BYTES_SRC;
  for (uint16_t bx = 0; bx < DIAL_ROW_BYTES_SRC; bx++) {
    uint8_t srcByte = pgm_read_byte(bmp + srcBase + bx);
    uint16_t ex = expandByte2x(srcByte);
    const uint16_t di = bx * 2;
    dstRow[di]     = (uint8_t)(ex >> 8);
    dstRow[di + 1] = (uint8_t)(ex & 0xFF);
  }
}

void printScoreScaled2x(const uint8_t* bmp) {
  // Center the dial and print in strips for much lower command overhead.
  printer.justify('C');

  for (uint16_t yOutStart = 0; yOutStart < DIAL_PRINT_H; yOutStart += DIAL_STRIP_ROWS) {
    uint16_t rowsThisStrip = DIAL_PRINT_H - yOutStart;
    if (rowsThisStrip > DIAL_STRIP_ROWS) rowsThisStrip = DIAL_STRIP_ROWS;

    for (uint16_t r = 0; r < rowsThisStrip; r++) {
      const uint16_t yOut = yOutStart + r;
      const uint16_t ySrc = yOut / DIAL_SCALE;
      uint8_t* dstRow = &scoreScaledStripBuf[r * DIAL_ROW_BYTES_DST];
      expandSourceRow2x(bmp, ySrc, dstRow);
    }

    printer.printBitmap(DIAL_PRINT_W, rowsThisStrip, scoreScaledStripBuf, false);
  }

  // Restore default text alignment used by the rest of the receipt.
  printer.justify('L');
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

      uint8_t btnBackPressed  = (digitalRead(BTN_BACK_PIN)  == LOW) ? 1 : 0;
      uint8_t btnNextPressed  = (digitalRead(BTN_NEXT_PIN)  == LOW) ? 1 : 0;
      uint8_t btnResetPressed = (digitalRead(BTN_RESET_PIN) == LOW) ? 1 : 0;

      Serial.print(analogRead(A0));
      Serial.print(",");
      Serial.print(analogRead(A1));
      Serial.print(",");
      Serial.print(analogRead(A4));
      Serial.print(",");
      Serial.print(btnBackPressed);
      Serial.print(",");
      Serial.print(btnNextPressed);
      Serial.print(",");
      Serial.println(btnResetPressed);
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
    applyPrinterQualityPreset();
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
    String line = cmd.substring(5);
    if (isDividerCandidate(line)) printDividerLine();
    else                          printer.println(line);

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
    printDividerLine();

  // ── Paper feed ───────────────────────────────────────────────────────────────
  } else if (cmd.startsWith("FEED:")) {
    int n = cmd.substring(5).toInt();
    if (n > 0 && n <= 20) printer.feed(n);

  // ── Score dial bitmap ─────────────────────────────────────────────────────────
  } else if (cmd.startsWith("SCORE:")) {
    int s = cmd.substring(6).toInt();
    if (s >= 1 && s <= 10) {
      const uint8_t* bmp = (const uint8_t*)pgm_read_ptr(&score_bitmaps[s - 1]);
      printScoreScaled2x(bmp);
    }
  }
}
