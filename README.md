# Build Your Speculative AI Company

An interactive tool for exploring the ethical and practical consequences of AI design decisions. Step through 3 screens to design a fictional AI company — its purpose, funding, data, and infrastructure — and an LLM generates a speculative story about where it ends up: who it helps, who it harms, and how it probably fails.

The output appears as a thermal printer receipt that can be saved as a PNG.

---

## Quick Start (no hardware)

The app runs fully in a browser without any Arduino attached. The physical knobs and slider are optional.

```bash
# 1. Install Python dependencies
pip install flask requests pyserial

# 2. Install and start Ollama
#    Download from https://ollama.com, then:
ollama serve

# 3. Pull the language model (first time only, ~2 GB)
ollama pull llama3.2:3b

# 4. Start the app
python app.py
```

Open **http://localhost:5002** in your browser.

---

## Full Setup (with Arduino)

### 1. Python dependencies

```bash
pip install flask requests pyserial
```

### 2. Ollama

Download from [ollama.com](https://ollama.com) and install.

```bash
# Pull the model (one-time, ~2 GB download)
ollama pull llama3.2:3b

# Start Ollama (keep this running in a separate terminal)
ollama serve
```

A larger model produces richer output. To switch models, edit `GENERATION_MODEL` at the top of `app.py`:

```python
GENERATION_MODEL = "llama3.2:3b"   # or: "llama3.2:latest", "qwen2.5:7b"
```

### 3. Arduino

Upload the sketch below to an Arduino Mega:

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

**Important:** close the Arduino IDE's Serial Monitor before running the app — it blocks the serial port.

### 4. Wiring

**Rotary knob 1 — A0 (left control on each screen)**

Looking at the flat face of the pot with the shaft pointing away from you:

| Knob 1 pin     | Arduino pin |
|----------------|-------------|
| Left           | GND         |
| Middle (wiper) | A0          |
| Right          | 5V          |

**Rotary knob 2 — A1 (right control on each screen)**

| Knob 2 pin     | Arduino pin |
|----------------|-------------|
| Left           | GND         |
| Middle (wiper) | A1          |
| Right          | 5V          |

### Linear slider — A4 (bottom control on each screen)

Use pins **1, 2, 3** — not the primed variants (1′, 2′, 3′).

| Slider pin             | Arduino pin |
|------------------------|-------------|
| Pin 1 (left)           | GND         |
| Pin 2 (middle / wiper) | A4          |
| Pin 3 (right)          | 5V          |

### 5. Run the app

```bash
python app.py
```

Open <http://localhost:5002>. The serial status indicator in the top-right corner shows the connection state:

- **Green dot + port name** — Arduino connected and sending data
- **Red dot + NO DEVICE** — not connected

### 6. Connecting the Arduino

The app auto-detects common USB-serial adapters (CH340, CP210x, usbmodem). If auto-detect fails:

1. Click the **NO DEVICE** indicator in the top-right corner.
2. A panel lists all available serial ports with their descriptions.
3. Ports that look like Arduino are shown first with a **◆ LIKELY ARDUINO** badge.
4. Click a port — the app immediately tries to connect.

If you know the port in advance, you can hardcode it in `app.py`:

```python
SERIAL_PORT = "/dev/cu.usbserial-10"   # macOS example
SERIAL_PORT = "COM3"                    # Windows example
```

---

## Thermal Printer (optional)

The receipt output can be printed on an Adafruit-style 58mm thermal printer connected to the Arduino via software serial.

### Power

Do **not** power the printer from the Arduino's 5V pin — it draws too much current and will brown out the board. Use a separate 5V 2A supply (USB wall adapter + 2.1mm barrel jack + terminal block adapter).

| Printer wire | External supply |
|--------------|-----------------|
| Red          | 5V (+)          |
| Black        | GND (−)         |

Connect the external GND to the Arduino GND as well.

### Data

Wire colours vary between batches — check yours. Typically:

| Printer wire        | Arduino Mega pin                |
|---------------------|---------------------------------|
| GND (usually black) | GND                             |
| TX  (usually green) | Pin 5 (Arduino's RX)            |
| RX  (usually yellow)| Pin 6 (Arduino's TX)            |

---

## The 3 Screens

Each screen shows two knob panels (top row) and one slider panel (bottom row). All three descriptions update live as you turn the controls.

### Screen 1 — Who Are You?

| Control           | Hardware    | Options                                                   |
|-------------------|-------------|-----------------------------------------------------------|
| Org Type          | Knob 1 (A0) | NGO / Non-profit, Gov / Public, Private startup, Big Tech |
| Funding           | Knob 2 (A1) | Govt grants, Subscription, Venture capital, Corp sponsor  |
| Ethical Framework | Slider (A4) | Open ethics → Harm-tolerant (5 positions)                 |

### Screen 2 — Your Data

| Control      | Hardware    | Options                                                         |
|--------------|-------------|-----------------------------------------------------------------|
| Data Types   | Knob 1 (A0) | General web, Books / Academic, Proprietary client, Social media |
| Data Use     | Knob 2 (A1) | Unsupervised, Human feedback, Rule-based, Fine-tuned            |
| Data Source  | Slider (A4) | Open datasets → Synthetic (5 positions)                         |

### Screen 3 — Your Model

| Control        | Hardware    | Options                                                                 |
|----------------|-------------|-------------------------------------------------------------------------|
| Model Location | Knob 1 (A0) | Cloud, On-premise, Edge device, Decentralised                           |
| System Prompt  | Knob 2 (A1) | Open / transparent, Lightly guided, Commercially optimised, Restricted  |
| Model Size     | Slider (A4) | 1B → 140B (5 positions)                                                 |

Press **GENERATE** on screen 3 to produce the receipt.

---

## The Receipt

After generation, the output shows:

- A blank **Company Name** field (write on the printed receipt)
- Your full spec summary (org type, ethics, funding, data, model)
- Three impact scores — **Environmental**, **Social**, **Practicality/Sustainability** (1–10, from `scores.csv`)
- A 10–12 word summary beneath each score explaining it
- A 2-sentence **speculative narrative** about the organisation's arc
- A blank **Your Response** field (write your reaction on the printed receipt)

Press **↓ SAVE AS PNG** to download the receipt as a high-resolution image.

### Tuning the scores

Open `scores.csv` to adjust how each design choice affects the three scores. Each row covers one option of one control. Scores are integers 1–10.

```
control,option_index,option_label,env_score,social_score,practicality_score
s1_knob1,0,NGO / Non-profit,7,9,4
...
```

---

## Troubleshooting

**Ollama not running**
The receipt will show `[OLLAMA NOT RUNNING]`. Start it with `ollama serve` in a separate terminal.

**Arduino not detected**
Click the NO DEVICE indicator and pick from the port list. If no ports appear, check USB cable and driver installation (CH340 or CP210x driver for cheap Arduino clones).

**Serial Monitor blocking the port**
Close the Arduino IDE's Serial Monitor before running `python app.py`.

**Two serial readers / double output**
Make sure `use_reloader=False` is set in `app.py` (already the default). Flask's debug reloader forks the process, starting two serial threads.

**Wrong model size / slow generation**
Edit `GENERATION_MODEL` in `app.py`. `llama3.2:3b` is fast; `qwen2.5:7b` produces better writing.

---

## Architecture

| File         | Purpose                                                                                                                                  |
|--------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `app.py`     | Flask backend — serial reader, `/api/knob`, `/api/serial-status`, `/api/list-ports`, `/api/set-port`, `/api/generate`, CSV score loader  |
| `scores.csv` | Scoring weights for all 9 controls × 3 impact dimensions                                                                                 |
| `index.html` | Complete single-file frontend — HTML, CSS, and JS inline, no build step                                                                  |
