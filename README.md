# Build Your Speculative AI Company

An interactive tool for exploring the ethical and practical consequences of AI design decisions. You step through 7 choices to design a fictional AI company — its purpose, funding, data, and infrastructure — and Ollama generates a speculative story about where it ends up: who it helps, who it harms, and how it probably fails.

The output appears as a thermal printer receipt.

---

## Requirements

- Python 3.8+
- [Ollama](https://ollama.com) running locally
- `llama3.2:3b` model pulled (or change `GENERATION_MODEL` in `app.py`)
- Optional: Arduino Mega + two potentiometers (see [Hardware](#hardware) below)

---

## Setup

```bash
pip install flask requests pyserial

# Pull the model (first time only)
ollama pull llama3.2:3b

# Start Ollama if it isn't running
ollama serve

# Run the app
python app.py
```

Open **http://localhost:5002** in your browser.

---

## Hardware

The app supports optional physical controls: a rotary knob (controls the current stage) and a linear slider (controls Model Size from any stage).

### Wiring

**Linear slider (A4 → Model Size)**

Use pins **1, 2, 3** — not the primed variants (1′, 2′, 3′) that may also be present on the component.

| Slider pin             | Arduino pin |
|------------------------|-------------|
| Pin 1 (left)           | GND         |
| Pin 2 (middle / wiper) | A4          |
| Pin 3 (right)          | 5V          |

**Rotary knob 1 (A0 → left control on each screen)**

Looking at the flat face of the potentiometer with the shaft pointing away from you, the pins left to right are:

| Knob 1 pin     | Arduino pin |
|----------------|-------------|
| Left           | GND         |
| Middle (wiper) | A0          |
| Right          | 5V          |

**Rotary knob 2 (A1 → right control on each screen)**

| Knob 2 pin     | Arduino pin |
|----------------|-------------|
| Left           | GND         |
| Middle (wiper) | A1          |
| Right          | 5V          |

### Arduino sketch

Upload this to the board:

```cpp
void setup() {
  Serial.begin(9600);
}

void loop() {
  Serial.print(analogRead(A0));
  Serial.print(",");
  Serial.print(analogRead(A1));
  Serial.print(",");
  Serial.println(analogRead(A4));
  delay(50);
}
```

### Thermal printer

The receipt output can be printed on an Adafruit-style 58mm thermal printer connected to the Arduino via a software serial connection.

#### Power (DC IN socket)

Do **not** power the printer from the Arduino's 5V pin — it draws too much current during printing and will brown out the board. Use a separate 5V 2A supply (e.g. a USB wall adapter with a 2.1mm barrel jack and terminal block adapter).

| Printer power wire | External power supply |
|--------------------|-----------------------|
| Red                | 5V (+)                |
| Black              | GND (−)               |

#### Connect the grounds together

External GND ──┬── Printer power GND
               └── Arduino GND

#### Data (3-pin data socket)

Wire colours vary between batches — check yours. Typically:

| Printer wire           | Arduino Mega pin                    |
|------------------------|-------------------------------------|
| GND (usually black)    | GND                                 |
| TX  (usually green)    | Pin 5 (this is the Arduino's RX)    |
| RX  (usually yellow)   | Pin 6 (this is the Arduino's TX)    |

---

### Connecting

The app auto-detects common USB-serial adapters (CH340, CP210x, usbmodem). If it doesn't find the port automatically, set it manually at the top of `app.py`:

```python
SERIAL_PORT = "/dev/cu.usbserial-10"  # macOS example
SERIAL_PORT = "COM3"                   # Windows example
```

Close the Arduino IDE's Serial Monitor before running — it will block the port.

---

## The 3 Screens

Each screen shows two rotary knobs (top row) and one slider (bottom row). All three descriptions are visible at once. Turn the knobs or move the slider to change the selection.

### Screen 1 — Who Are You?

| Control | Hardware | Options |
|---------|----------|---------|
| Org Type | Knob 1 (A0) | NGO / Non-profit, Gov / Public, Private startup, Big Tech |
| Funding | Knob 2 (A1) | Govt grants, Subscription, Venture capital, Corp sponsor |
| Ethical Framework | Slider (A4) | Open ethics → Harm-tolerant (5 positions) |

### Screen 2 — Your Data

| Control | Hardware | Options |
|---------|----------|---------|
| Data Types | Knob 1 (A0) | General web, Books / Academic, Proprietary client, Social media |
| Data Use | Knob 2 (A1) | Internal research, Product features, Sold to third parties, Open source |
| Data Source | Slider (A4) | Open datasets → Synthetic (5 positions) |

### Screen 3 — Your Model

| Control | Hardware | Options |
|---------|----------|---------|
| Model Location | Knob 1 (A0) | Cloud, On-premise, Edge device, Decentralised |
| System Prompt | Knob 2 (A1) | Open / transparent, Lightly guided, Commercially optimised, Restricted |
| Model Size | Slider (A4) | 1B → 140B (5 positions, labelled) |

Press **GENERATE** on screen 3 to produce the receipt.

---

## The Receipt

After generation, the output appears as a thermal printer receipt containing:

- A blank **Company Name** field (for the user to write on the printed receipt)
- Your full spec summary (org, ethics, funding, data, model)
- Three impact dials: **Environmental**, **Social**, and **Practicality/Sustainability** (each scored 1–10, computed from `scores.csv`)
- A 15–20 word summary beneath each dial explaining the score
- A 3–4 sentence **speculative narrative** of the organisation's arc
- A blank **Your Response** field (for the user to write on the printed receipt)

### Tuning the scores

Open `scores.csv` to adjust how each choice affects the three scores. Each row covers one option of one control. Scores are integers 1–10.

```
control,option_index,option_label,env_score,social_score,practicality_score
s1_knob1,0,NGO / Non-profit,7,9,4
...
```

---

## Changing the Model

Open `app.py` and edit the top:

```python
GENERATION_MODEL = "llama3.2:3b"  # change this
```

A larger model (`llama3.2:latest`, `qwen2.5:7b`) produces better analysis in the final receipt.

---

## Architecture

- `app.py` — Flask backend, `/api/knob` + `/api/generate` endpoints, CSV score loader, serves `index.html`
- `scores.csv` — Scoring weights for all 9 controls × 3 dimensions
- `index.html` — Complete single-file frontend: all HTML, CSS, JS inline
- `index.html` — Complete single-file frontend: all HTML, CSS, and JS inline
- No build step. No npm. No frameworks.
