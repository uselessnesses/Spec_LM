/*
 * speculative_ai.ino  v5
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
 *   SCORE:<n>            print 384×256 score-dial bitmap (n = 1..10)
 *   FEED:<n>             feed n blank lines
 *   PRINT_END            feed 4 lines, sleep printer, exit print mode
 *
 * Libraries required (install via Arduino Library Manager)
 * ──────────────────────────────────────────────────────────
 *   Adafruit Thermal Printer Library
 */

#include <SoftwareSerial.h>
#include <Adafruit_Thermal.h>
#include "bitmaps.h"

// Many 58mm clone printers ship at 9600 baud.
// If yours needs 19200, change this value and re-upload.
const long PRINTER_BAUD = 9600;

// ── Printer serial ────────────────────────────────────────────────────────────
// Pin 5 = Arduino RX  ← printer TX (green wire)
// Pin 6 = Arduino TX  → printer RX (yellow wire)
SoftwareSerial printerSerial(5, 6);
Adafruit_Thermal printer(&printerSerial);

// ── Far-PROGMEM address table ─────────────────────────────────────────────────
// pgm_get_far_address() is a GCC statement-expression; it cannot be used in a
// static initialiser, so we populate this array at runtime in initScoreAddrs().
static uint32_t score_addrs[10];

void initScoreAddrs() {
  score_addrs[0] = pgm_get_far_address(score_1);
  score_addrs[1] = pgm_get_far_address(score_2);
  score_addrs[2] = pgm_get_far_address(score_3);
  score_addrs[3] = pgm_get_far_address(score_4);
  score_addrs[4] = pgm_get_far_address(score_5);
  score_addrs[5] = pgm_get_far_address(score_6);
  score_addrs[6] = pgm_get_far_address(score_7);
  score_addrs[7] = pgm_get_far_address(score_8);
  score_addrs[8] = pgm_get_far_address(score_9);
  score_addrs[9] = pgm_get_far_address(score_10);
}

// ── State ─────────────────────────────────────────────────────────────────────
bool   printing  = false;
String inputBuf  = "";

// Sensor timing
unsigned long lastSensorSend = 0;
const unsigned long SENSOR_INTERVAL_MS = 50;


// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  initScoreAddrs();
  Serial.begin(9600);
  printerSerial.begin(PRINTER_BAUD);
  printer.begin();
  printer.sleep();   // start in sleep mode; wake on PRINT_START
}


// ── Bitmap print via far PROGMEM (ELPM) ──────────────────────────────────────
// Sends DC2 '*' bitmap command directly to printerSerial so we can read bytes
// with pgm_read_byte_far() rather than going through the library's fromProgmem
// path, which uses pgm_read_byte() (LPM — only reaches lower 64 KB of flash).
void printBitmapFromFarProgmem(uint32_t addr) {
  const uint8_t ROW_BYTES = DIAL_W / 8;   // 48 bytes per row
  int rowsLeft = DIAL_H;
  while (rowsLeft > 0) {
    uint8_t chunk = (rowsLeft > 255) ? 255 : (uint8_t)rowsLeft;
    printerSerial.write(0x12);    // DC2
    printerSerial.write('*');
    printerSerial.write(chunk);
    printerSerial.write(ROW_BYTES);
    for (int r = 0; r < chunk; r++) {
      for (int b = 0; b < ROW_BYTES; b++) {
        printerSerial.write(pgm_read_byte_far(addr++));
      }
    }
    rowsLeft -= chunk;
  }
}


// ── Main loop ─────────────────────────────────────────────────────────────────
void loop() {
  // Non-blocking serial read — buffer chars until newline
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      inputBuf.trim();
      if (inputBuf.length() > 0) handleCommand(inputBuf);
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
    delay(80);  // give sleepy printers a moment before first text command
    Serial.println("OK");
    return;
  }

  if (cmd == "PRINT_END") {
    printer.feed(4);
    printer.sleep();
    printing = false;
    Serial.println("OK");
    return;
  }

  // All other commands require print mode to be active
  if (!printing) { Serial.println("OK"); return; }

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
      printBitmapFromFarProgmem(score_addrs[s - 1]);
    }
  }

  // ACK — tells Flask the command is done and it can send the next one
  Serial.println("OK");
}
