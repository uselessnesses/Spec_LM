import csv
import json
import os
import threading
import time

import requests
try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False
    print("[SERIAL] pyserial not installed — knob disabled. Run: pip3 install pyserial")
from flask import Flask, Response, request, send_file, stream_with_context

app = Flask(__name__)

# ── Arduino serial ────────────────────────────────────────────────────────────
SERIAL_PORT = "/dev/cu.usbserial-10"
SERIAL_BAUD = 9600
_knob_value    = 512   # A0 smoothed
_knob2_value   = 512   # A1 smoothed
_slider_value  = 512   # A4 smoothed
_knob_raw      = 512
_knob2_raw     = 512
_slider_raw    = 512
_knob_smooth   = 512.0
_knob2_smooth  = 512.0
_slider_smooth = 512.0
SMOOTH_ALPHA   = 0.25
_serial_lock   = threading.Lock()


def _find_arduino_port():
    if not _SERIAL_AVAILABLE:
        return None
    for p in serial.tools.list_ports.comports():
        desc = (p.description + p.hwid).lower()
        if any(k in desc for k in ('arduino', 'usbmodem', 'usbserial', 'ch340', 'cp210')):
            return p.device
    return None


def _serial_reader():
    global _knob_value, _knob2_value, _slider_value
    global _knob_raw, _knob2_raw, _slider_raw
    global _knob_smooth, _knob2_smooth, _slider_smooth
    if not _SERIAL_AVAILABLE:
        return
    port = SERIAL_PORT or _find_arduino_port()
    if not port:
        print("[SERIAL] No Arduino found — knob disabled. Set SERIAL_PORT manually if needed.")
        return
    print(f"[SERIAL] Connecting to {port} at {SERIAL_BAUD} baud…")
    while True:
        try:
            with serial.Serial(port, SERIAL_BAUD, timeout=2) as ser:
                ser.reset_input_buffer()
                print(f"[SERIAL] Connected.")
                while True:
                    try:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                    except OSError:
                        continue  # transient USB-serial artefact
                    parts = line.split(",")
                    if len(parts) == 3 and all(p.isdigit() for p in parts):
                        k1 = int(parts[0])
                        k2 = int(parts[1])
                        s  = int(parts[2])
                        if not (0 <= k1 <= 1023 and 0 <= k2 <= 1023 and 0 <= s <= 1023):
                            continue  # discard corrupted readings
                        with _serial_lock:
                            _knob_raw      = k1
                            _knob2_raw     = k2
                            _slider_raw    = s
                            _knob_smooth   = SMOOTH_ALPHA * k1 + (1 - SMOOTH_ALPHA) * _knob_smooth
                            _knob2_smooth  = SMOOTH_ALPHA * k2 + (1 - SMOOTH_ALPHA) * _knob2_smooth
                            _slider_smooth = SMOOTH_ALPHA * s  + (1 - SMOOTH_ALPHA) * _slider_smooth
                            _knob_value    = round(_knob_smooth)
                            _knob2_value   = round(_knob2_smooth)
                            _slider_value  = round(_slider_smooth)
        except Exception as e:
            print(f"[SERIAL] Error: {e} — retrying in 3s")
            time.sleep(3)


threading.Thread(target=_serial_reader, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
GENERATION_MODEL = "llama3.2:3b"   # change this to use a different model

INDEX_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
SCORES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores.csv")

# ── Load scoring CSV ──────────────────────────────────────────────────────────
_scores = {}


def _load_scores():
    global _scores
    if not os.path.exists(SCORES_PATH):
        print(f"[SCORES] {SCORES_PATH} not found — all scores default to 5")
        return
    with open(SCORES_PATH, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row['control'], int(row['option_index']))
            _scores[key] = {
                'env':          int(row['env_score']),
                'social':       int(row['social_score']),
                'practicality': int(row['practicality_score']),
            }
    print(f"[SCORES] Loaded {len(_scores)} entries from scores.csv")


_load_scores()
# ─────────────────────────────────────────────────────────────────────────────


def compute_scores(choices):
    envs, socs, pracs = [], [], []
    for ctrl, idx in choices:
        s = _scores.get((ctrl, idx), {'env': 5, 'social': 5, 'practicality': 5})
        envs.append(s['env'])
        socs.append(s['social'])
        pracs.append(s['practicality'])
    if not envs:
        return 5, 5, 5
    env  = max(1, min(10, round(sum(envs) / len(envs))))
    soc  = max(1, min(10, round(sum(socs) / len(socs))))
    prac = max(1, min(10, round(sum(pracs) / len(pracs))))
    return env, soc, prac


def stream_ollama(prompt, num_predict=150, temperature=0.85):
    payload = {
        "model": GENERATION_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    try:
        with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=120) as r:
            for line in r.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            return
                    except json.JSONDecodeError:
                        continue
    except requests.exceptions.ConnectionError:
        yield (
            "\n[OLLAMA NOT RUNNING]\n"
            "Start Ollama with: ollama serve\n"
            "Then pull the model: ollama pull llama3.2:3b"
        )
    except requests.exceptions.Timeout:
        yield "\n[TIMEOUT] Ollama took too long to respond."


def streamed(generator):
    return Response(
        stream_with_context(generator),
        mimetype="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/")
def index():
    return send_file(INDEX_PATH)


@app.route("/api/knob")
def knob():
    with _serial_lock:
        return {
            "knob":       _knob_value,
            "knob2":      _knob2_value,
            "slider":     _slider_value,
            "knob_raw":   _knob_raw,
            "knob2_raw":  _knob2_raw,
            "slider_raw": _slider_raw,
        }


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()

    # Labels for human-readable prompt
    org_type   = data.get("org_type",   "Unknown")
    ethical    = data.get("ethical",    "Unknown")
    funding    = data.get("funding",    "Unknown")
    data_types = data.get("data_types", "Unknown")
    data_src   = data.get("data_source","Unknown")
    data_use   = data.get("data_use",   "Unknown")
    model_size = data.get("model_size", "Unknown")
    model_loc  = data.get("model_location", "Unknown")
    sys_prompt = data.get("system_prompt",  "Unknown")

    # Indices for score lookup
    choices = [
        ("s1_knob1", data.get("org_type_idx",   0)),
        ("s1_slider", data.get("ethical_idx",   2)),
        ("s1_knob2",  data.get("funding_idx",   0)),
        ("s2_knob1",  data.get("data_types_idx",0)),
        ("s2_slider", data.get("data_source_idx",2)),
        ("s2_knob2",  data.get("data_use_idx",  0)),
        ("s3_slider", data.get("model_size_idx",2)),
        ("s3_knob1",  data.get("model_location_idx",0)),
        ("s3_knob2",  data.get("system_prompt_idx",0)),
    ]
    env_score, social_score, prac_score = compute_scores(choices)

    prompt = (
        "You are a speculative fiction analyst. Based on these AI organisation design choices, "
        "write a brief critical analysis.\n\n"
        f"ORG TYPE: {org_type}\n"
        f"ETHICAL FRAMEWORK: {ethical}\n"
        f"FUNDING: {funding}\n"
        f"DATA TYPES: {data_types}\n"
        f"DATA SOURCE: {data_src}\n"
        f"DATA USE: {data_use}\n"
        f"MODEL SIZE: {model_size}\n"
        f"MODEL LOCATION: {model_loc}\n"
        f"SYSTEM PROMPT STYLE: {sys_prompt}\n\n"
        "Pre-computed scores (do not change these numbers — write summaries that explain them):\n"
        f"  Environmental impact: {env_score}/10\n"
        f"  Social impact: {social_score}/10\n"
        f"  Practicality/sustainability: {prac_score}/10\n\n"
        "Respond in EXACTLY this format:\n\n"
        "STORY:\n"
        "[3-4 sentence speculative narrative of this organisation's arc — its founding, its peak, "
        "and most likely end. Be specific to the choices made. Be matter-of-fact, not preachy.]\n\n"
        f"ENV_SUMMARY: [10-12 words explaining the {env_score}/10 environmental impact score]\n\n"
        f"SOCIAL_SUMMARY: [10-12 words explaining the {social_score}/10 social impact score]\n\n"
        f"PRACTICALITY_SUMMARY: [10-12 words explaining the {prac_score}/10 practicality score]"
    )

    def gen_with_scores():
        # Emit scores header first so the frontend can extract them synchronously
        yield f"__SCORES__:{env_score},{social_score},{prac_score}\n"
        yield from stream_ollama(prompt, num_predict=450, temperature=0.7)

    return streamed(gen_with_scores())


if __name__ == "__main__":
    print(f"Starting Build Your Speculative AI Company at http://localhost:5002")
    print(f"Using model: {GENERATION_MODEL}")
    print(f"Ollama expected at: {OLLAMA_URL}")
    app.run(debug=True, port=5002, use_reloader=False)
