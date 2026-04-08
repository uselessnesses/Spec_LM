# Paper Trail

An interactive tool for exploring the ethical and practical consequences of AI design decisions. Step through 3 screens to design a fictional AI company — its purpose, funding, data, and infrastructure — and an LLM generates a speculative story about where it ends up: who it helps, who it harms, and how it probably fails.

The output appears as a thermal printer receipt. A PNG copy is auto-saved to `receipt_pngs/`.

---

## Quick Start (no hardware)

The app runs fully in a browser without any Arduino attached. The physical knobs, slider, and navigation buttons are optional.

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

Upload the sketch in this repo to an Arduino Mega:

1. Open `arduino/paper_trail/paper_trail.ino` in the Arduino IDE.
2. Ensure `arduino/paper_trail/bitmaps.h` is in the same sketch folder.
3. Select **Board: Arduino Mega 2560** and the correct serial port.
4. Click **Upload**.

If you modify score dial generation, regenerate the bitmap header first:

```bash
python generate_bitmaps.py
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

### Navigation buttons (optional)

Add three normally-open push buttons for hardware navigation.

- The sketch uses `INPUT_PULLUP`, so each button should connect:
- One side to the Arduino digital pin
- The other side to `GND`
- Pressed = `LOW` electrically (interpreted as pressed in software)

| Button function         | Arduino pin |
|-------------------------|-------------|
| Back (previous page)    | D8          |
| Next / Generate         | D9          |
| Reset (browser refresh) | D7          |

For 4-leg tactile/panel buttons: use one leg from each internally-connected pair (effectively across the switch), not two legs on the same side.

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

Hardware button behavior matches the on-screen flow:

- **Back (D8):** previous screen
- **Next (D9):** next screen, or **Generate** on screen 3
- **Reset (D7):** refreshes the browser page

---

## The Receipt

After generation, the output shows:

- A blank **Company Name** field (write on the printed receipt)
- Your full spec summary (org type, ethics, funding, data, model)
- Three ratings — **Environmental**, **Social**, **Practicality/Sustainability** (0–10, from CSV config)
- A 10–12 word summary beneath each score explaining it
- A 2-sentence **speculative narrative** about the organisation's arc
- A blank **Your Response** field (write your reaction on the printed receipt)
- A sequential receipt ID (shown on both digital and physical receipt)

Each generated receipt is auto-printed once and auto-saved as a PNG in `receipt_pngs/`.  
Use **PRINT** to create an extra copy.

### Tuning copy + scores

Open `paper_trail_options.csv` to edit the interaction option labels/descriptions and all three rating values.  
This is the canonical file used by the app for both interface copy and scoring.

- Ratings are integers **0–10** (`0 = bad`, `10 = good`).
- `scores.csv` is kept as a compatibility export for tooling that still expects the old format.

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
| `app.py`     | Flask backend — serial reader (knobs, slider, and nav button states), `/api/knob`, `/api/serial-status`, `/api/list-ports`, `/api/set-port`, `/api/generate`, `/api/print`, `/api/save-receipt-png`, receipt ID generation, CSV score loader |
| `paper_trail_options.csv` | Canonical control data + option copy + env/social/practicality ratings (editable)                                         |
| `scores.csv` | Compatibility score export (`control, option_index, option_label, env_score, social_score, practicality_score`)                           |
| `index.html` | Complete single-file frontend — HTML, CSS, and JS inline, no build step                                                                  |
