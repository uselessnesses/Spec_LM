import csv
import json
import os
import textwrap
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
# Set SERIAL_PORT to a specific device path to override auto-detect, e.g.:
#   SERIAL_PORT = "/dev/cu.usbserial-10"   # macOS
#   SERIAL_PORT = "COM3"                    # Windows
# Leave as None to auto-detect.
SERIAL_PORT = None
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
_serial_lock          = threading.Lock()
_serial_status        = {"connected": False, "port": None, "error": None, "last_line": ""}
_user_port_override   = None          # set via /api/set-port
_serial_restart_event = threading.Event()
_ser_obj              = None          # active Serial instance, set by _serial_reader


def _list_candidate_ports():
    """Return all likely Arduino ports, sorted by likelihood."""
    if not _SERIAL_AVAILABLE:
        return []
    candidates = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description + p.hwid).lower()
        if any(k in desc for k in ('arduino', 'usbmodem', 'usbserial', 'ch340', 'cp210')):
            candidates.append(p.device)
    return candidates


def _serial_reader():
    global _knob_value, _knob2_value, _slider_value
    global _knob_raw, _knob2_raw, _slider_raw
    global _knob_smooth, _knob2_smooth, _slider_smooth
    global _serial_status, _user_port_override, _ser_obj
    if not _SERIAL_AVAILABLE:
        _serial_status = {"connected": False, "port": None, "error": "pyserial not installed"}
        return
    while True:
        # Resolve port: user override → hardcoded → auto-detect
        port = _user_port_override or SERIAL_PORT
        if not port:
            candidates = _list_candidate_ports()
            port = candidates[0] if candidates else None
            if candidates:
                print(f"[SERIAL] Auto-detected ports: {candidates}")
        if not port:
            _serial_status = {"connected": False, "port": None,
                              "error": "No Arduino found. Plug in USB and wait, or click NO DEVICE to pick a port."}
            print(f"[SERIAL] {_serial_status['error']} Retrying in 3s…")
            _serial_restart_event.wait(timeout=3)
            _serial_restart_event.clear()
            continue
        print(f"[SERIAL] Connecting to {port} at {SERIAL_BAUD} baud…")
        try:
            with serial.Serial(port, SERIAL_BAUD, timeout=2) as ser:
                ser.reset_input_buffer()
                _ser_obj = ser
                _serial_status = {"connected": True, "port": port, "error": None}
                print(f"[SERIAL] Connected on {port}.")
                while True:
                    try:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                    except OSError:
                        continue  # transient USB-serial artefact
                    if line:
                        _serial_status["last_line"] = line
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
            _serial_status = {"connected": False, "port": port, "error": str(e)}
            print(f"[SERIAL] Error on {port}: {e} — retrying in 3s")
            _ser_obj = None
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


@app.route("/api/serial-status")
def serial_status():
    return _serial_status


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
        "[2 sentences maximum. Speculative narrative of this organisation's arc — its peak and most likely end. "
        "Be specific to the choices made. Be matter-of-fact, not preachy.]\n\n"
        f"ENV_SUMMARY: [10-12 words explaining the {env_score}/10 environmental impact score]\n\n"
        f"SOCIAL_SUMMARY: [10-12 words explaining the {social_score}/10 social impact score]\n\n"
        f"PRACTICALITY_SUMMARY: [10-12 words explaining the {prac_score}/10 practicality score]"
    )

    def gen_with_scores():
        # Emit scores header first so the frontend can extract them synchronously
        yield f"__SCORES__:{env_score},{social_score},{prac_score}\n"
        yield from stream_ollama(prompt, num_predict=450, temperature=0.7)

    return streamed(gen_with_scores())


@app.route("/api/list-ports")
def list_ports():
    if not _SERIAL_AVAILABLE:
        return {"ports": [], "error": "pyserial not installed"}
    ports = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description + p.hwid).lower()
        likely = any(k in desc for k in ('arduino', 'usbmodem', 'usbserial', 'ch340', 'cp210'))
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
            "likely_arduino": likely,
        })
    ports.sort(key=lambda x: (not x["likely_arduino"], x["device"]))
    return {"ports": ports}


@app.route("/api/set-port", methods=["POST"])
def set_port():
    global _user_port_override
    data = request.get_json()
    _user_port_override = data.get("port") or None
    _serial_restart_event.set()   # wake the reader immediately
    return {"ok": True, "port": _user_port_override}


def _build_print_commands(data):
    """Return ordered list of Arduino print command strings for one receipt."""
    WRAP = 32   # characters per line at small font

    def wrap(text):
        return textwrap.wrap(str(text), WRAP) or [""]

    cmds = []
    cmds.append("PRINT_START")

    # ── Header ────────────────────────────────────────────────────────────────
    cmds += ["ALIGN:C", "BOLD_ON", "SIZE:S",
             "TEXT:BUILD YOUR SPECULATIVE",
             "TEXT:AI COMPANY",
             "BOLD_OFF", "ALIGN:L", "DIVIDER"]

    # ── Company name field ────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:COMPANY NAME:", "BOLD_OFF",
             "TEXT:", "DIVIDER"]

    # ── Specs ─────────────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:SPECS", "BOLD_OFF"]
    specs = [
        ("ORG",    data.get("org_type",       "")),
        ("ETHICS", data.get("ethical",        "")),
        ("FUND",   data.get("funding",        "")),
        ("DATA",   f"{data.get('data_types','')} / {data.get('data_source','')}"),
        ("USE",    data.get("data_use",       "")),
        ("MODEL",  f"{data.get('model_size','')} - {data.get('model_location','')}"),
        ("PROMPT", data.get("system_prompt",  "")),
    ]
    for label, value in specs:
        cmds.append(f"TEXT:{label:<7}{value}")
    cmds.append("DIVIDER")

    # ── Score blocks ──────────────────────────────────────────────────────────
    score_sections = [
        ("ENVIRONMENTAL IMPACT", data.get("env_score",    5), data.get("env_summary",    "")),
        ("SOCIAL IMPACT",        data.get("social_score", 5), data.get("social_summary", "")),
        ("PRACTICALITY",         data.get("prac_score",   5), data.get("practicality_summary", "")),
    ]
    for title, score, summary in score_sections:
        score = int(score)
        cmds += ["BOLD_ON", f"TEXT:{title}  {score}/10", "BOLD_OFF"]
        cmds.append(f"SCORE:{score}")
        for line in wrap(summary):
            cmds.append(f"TEXT:{line}")
        cmds.append("FEED:1")
    cmds.append("DIVIDER")

    # ── Story ─────────────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:COMPANY STORY", "BOLD_OFF"]
    for line in wrap(data.get("story", "")):
        cmds.append(f"TEXT:{line}")
    cmds.append("DIVIDER")

    # ── Response field ────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:YOUR RESPONSE", "BOLD_OFF"]
    cmds += ["TEXT:", "TEXT:", "TEXT:", "TEXT:", "TEXT:"]
    cmds.append("DIVIDER")

    # ── Footer ────────────────────────────────────────────────────────────────
    cmds += ["ALIGN:C",
             "TEXT:THANK YOU FOR BUILDING",
             "TEXT:RESPONSIBLY (?)",
             "ALIGN:L"]

    cmds.append("PRINT_END")
    return cmds


def _command_delay_seconds(cmd: str) -> float:
    """
    Return a conservative inter-command delay so Arduino USB RX buffer
    does not overflow while the printer is physically rendering output.
    """
    if cmd.startswith("SCORE:"):
        return 0.55  # bitmap transfer is the heaviest command
    if cmd.startswith("TEXT:") or cmd == "DIVIDER":
        return 0.12
    if cmd.startswith("FEED:"):
        return 0.08
    return 0.04


@app.route("/api/print", methods=["POST"])
def print_receipt():
    global _ser_obj
    if not _ser_obj:
        return {"ok": False, "error": "Arduino not connected"}, 503
    data     = request.get_json()
    commands = _build_print_commands(data)
    with _serial_lock:
        if not _ser_obj:
            return {"ok": False, "error": "Arduino not connected"}, 503
        try:
            for cmd in commands:
                _ser_obj.write((cmd + "\n").encode())
                _ser_obj.flush()
                time.sleep(_command_delay_seconds(cmd))
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500
    return {"ok": True}


if __name__ == "__main__":
    print(f"Starting Build Your Speculative AI Company at http://localhost:5002")
    print(f"Using model: {GENERATION_MODEL}")
    print(f"Ollama expected at: {OLLAMA_URL}")
    app.run(debug=True, port=5002, use_reloader=False)
