import csv
import base64
import json
import os
import re
import textwrap
import threading
import time
from datetime import datetime

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
_serial_io_lock       = threading.Lock()
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
            with serial.Serial(port, SERIAL_BAUD, timeout=0.25) as ser:
                ser.reset_input_buffer()
                _ser_obj = ser
                _serial_status = {"connected": True, "port": port, "error": None}
                print(f"[SERIAL] Connected on {port}.")
                while True:
                    try:
                        with _serial_io_lock:
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
OPTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trail_options.csv")
RECEIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt_pngs")
RECEIPT_COUNTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt_counter.txt")
_receipt_id_lock = threading.Lock()

# ── Load option copy + scoring CSV ───────────────────────────────────────────
_option_controls = {}


def _load_option_config():
    """
    Load canonical option copy from paper_trail_options.csv.
    """
    global _option_controls
    _option_controls = {}

    if os.path.exists(OPTIONS_PATH):
        with open(OPTIONS_PATH, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                control_key = row.get('control_key', '').strip()
                option_index = int(row['option_index'])
                option_label = row.get('option_label', '').strip()
                option_desc = row.get('option_desc', '').strip()

                if control_key:
                    if control_key not in _option_controls:
                        _option_controls[control_key] = {"names": [], "descs": []}
                    names = _option_controls[control_key]["names"]
                    descs = _option_controls[control_key]["descs"]
                    while len(names) <= option_index:
                        names.append("")
                        descs.append("")
                    names[option_index] = option_label
                    descs[option_index] = option_desc

        print(f"[CONFIG] Loaded option copy for {len(_option_controls)} controls from paper_trail_options.csv")
        return
    print(f"[CONFIG] {OPTIONS_PATH} not found - using built-in frontend CTRL defaults")


_load_option_config()
# ─────────────────────────────────────────────────────────────────────────────


def _next_receipt_id():
    """Increment and return the next sequential Paper Trail receipt ID."""
    with _receipt_id_lock:
        current = 0
        if os.path.exists(RECEIPT_COUNTER_PATH):
            try:
                with open(RECEIPT_COUNTER_PATH, "r") as f:
                    current = int(f.read().strip() or "0")
            except (ValueError, OSError):
                current = 0
        current += 1
        with open(RECEIPT_COUNTER_PATH, "w") as f:
            f.write(str(current))
    return f"PT-{current:05d}"


ENV_BASE = {
    "model_size": {
        "1B": 2, "7B": 1, "14B": 0, "80B": -2, "140B": -4,
    },
    "model_location": {
        "Runs on devices locally": 1,
        "Hosted by the organisation": 0,
        "Decentralised": 0,
        "Outsourced to third party": -1,
    },
    "data_source": {
        "Built / collected in-house": 0,
        "Licensed / purchased": 0,
        "Crowdsourced": 0,
        "Open datasets": 0,
        "Synthetic": -1,
        "Scraped": 0,
    },
}

ENV_COMBOS = [
    {
        "conditions": {"model_size": "140B", "model_location": "Outsourced to third party"},
        "modifier": -2,
        "reason": "A frontier-scale model running on cloud servers has a massive and ongoing energy footprint, often powered by fossil fuels.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Runs on devices locally"},
        "modifier": 2,
        "reason": "A small model on local hardware has near-zero environmental overhead.",
    },
    {
        "conditions": {"ethical": "Justice and rights centred", "model_size": "1B"},
        "modifier": 1,
        "reason": "Choosing a small model reflects a genuine commitment to minimising environmental harm.",
    },
    {
        "conditions": {"ethical": "Fully extractive", "model_size": "140B"},
        "modifier": -1,
        "reason": "No incentive to optimise for efficiency when the goal is maximum extraction.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "model_size": "140B"},
        "modifier": -1,
        "reason": "At mega-corporation scale, the energy cost of a frontier model is multiplied across millions of users.",
    },
]

SOCIAL_BASE = {
    "org_type": {
        "Community group": 1,
        "Research institute": 1,
        "Public / governmental": 0,
        "Startup": 0,
        "Mega-corporation": -1,
    },
    "ethical": {
        "Justice and rights centred": 2,
        "Transparent and careful": 1,
        "Techno-optimist": 0,
        "Growth-first": -1,
        "Harm-tolerant": -2,
        "Fully extractive": -3,
    },
}

SOCIAL_COMBOS = [
    {
        "conditions": {"org_type": "Public / governmental", "ethical": "Fully extractive"},
        "modifier": -4,
        "reason": "A public body using extractive practices betrays the citizens it is supposed to serve.",
    },
    {
        "conditions": {"org_type": "Public / governmental", "ethical": "Harm-tolerant"},
        "modifier": -3,
        "reason": "A government body that tolerates harm to the people it serves undermines public trust in institutions.",
    },
    {
        "conditions": {"org_type": "Community group", "ethical": "Fully extractive"},
        "modifier": -5,
        "reason": "An organisation built on community trust using fully extractive practices is a fundamental betrayal.",
    },
    {
        "conditions": {"org_type": "Community group", "ethical": "Harm-tolerant"},
        "modifier": -3,
        "reason": "A community group that accepts harm to its own community has abandoned its core purpose.",
    },
    {
        "conditions": {"org_type": "Research institute", "ethical": "Fully extractive"},
        "modifier": -3,
        "reason": "A research body pursuing extraction over knowledge undermines academic integrity and public funding trust.",
    },
    {
        "conditions": {"org_type": "Community group", "ethical": "Justice and rights centred"},
        "modifier": 2,
        "reason": "A community group centred on justice and rights is building technology that genuinely serves its people.",
    },
    {
        "conditions": {"org_type": "Public / governmental", "ethical": "Transparent and careful"},
        "modifier": 2,
        "reason": "A transparent, careful public body is how technology should be governed - accountable and deliberate.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "ethical": "Justice and rights centred"},
        "modifier": 2,
        "reason": "If genuine, a mega-corporation committing to justice-centred ethics could have outsized positive impact at scale.",
    },
    {
        "conditions": {"data_type": "Client / task specific", "data_source": "Scraped"},
        "modifier": -3,
        "reason": "Scraping client-specific data without consent is a serious breach of trust.",
    },
    {
        "conditions": {"org_type": "Community group", "data_source": "Scraped"},
        "modifier": -3,
        "reason": "A community organisation scraping data contradicts the trust-based relationship it depends on.",
    },
    {
        "conditions": {"data_type": "Social media", "data_source": "Scraped"},
        "modifier": -2,
        "reason": "Scraping social media content means using people's personal expression without their knowledge or consent.",
    },
    {
        "conditions": {"data_type": "Social media", "ethical": "Justice and rights centred"},
        "modifier": -1,
        "reason": "Using social media data, even ethically, is hard to square with a rights-centred approach when users did not consent to this use.",
    },
    {
        "conditions": {"data_source": "Built / collected in-house", "ethical": "Justice and rights centred"},
        "modifier": 1,
        "reason": "Building your own data with a justice-centred approach means full control over consent and representation.",
    },
    {
        "conditions": {"data_source": "Crowdsourced", "ethical": "Fully extractive"},
        "modifier": -2,
        "reason": "Crowdsourcing under extractive ethics likely means underpaying contributors and exploiting their labour.",
    },
    {
        "conditions": {"system_prompt": "User configurable", "ethical": "Fully extractive"},
        "modifier": -2,
        "reason": "Giving users full control with no ethical guardrails is an invitation for the system to be weaponised.",
    },
    {
        "conditions": {"system_prompt": "Safety first", "org_type": "Public / governmental"},
        "modifier": 1,
        "reason": "A safety-first approach from a public body protects the citizens who depend on it.",
    },
    {
        "conditions": {"system_prompt": "User configurable", "org_type": "Community group"},
        "modifier": 1,
        "reason": "Letting the community configure the system reflects genuine commitment to shared ownership.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "model_size": "140B", "ethical": "Growth-first"},
        "modifier": -3,
        "reason": "A mega-corporation running a frontier model with growth-first ethics concentrates enormous power with minimal accountability.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "data_type": "Social media", "ethical": "Fully extractive"},
        "modifier": -3,
        "reason": "A mega-corporation extracting value from social media data at scale is surveillance capitalism in its purest form.",
    },
]

PRACTICALITY_BASE = {}

PRACTICALITY_COMBOS = [
    {
        "conditions": {"model_size": "140B", "model_location": "Runs on devices locally"},
        "modifier": -10,
        "reason": "A 140 billion parameter model cannot run on consumer hardware. This is physically impossible with current technology.",
    },
    {
        "conditions": {"model_size": "80B", "model_location": "Runs on devices locally"},
        "modifier": -10,
        "reason": "An 80 billion parameter model requires dedicated server hardware. It will not run on a phone or laptop.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Runs on devices locally"},
        "modifier": -4,
        "reason": "A 14B model can technically run on high-end consumer hardware, but performance will be poor and battery life terrible.",
    },
    {
        "conditions": {"model_size": "140B", "model_location": "Decentralised"},
        "modifier": -6,
        "reason": "Coordinating a frontier-scale model across decentralised nodes is an unsolved engineering problem.",
    },
    {
        "conditions": {"org_type": "Community group", "model_size": "140B"},
        "modifier": -7,
        "reason": "A community group cannot afford the infrastructure to train or run a frontier-scale model. The compute costs alone would consume the entire budget.",
    },
    {
        "conditions": {"org_type": "Community group", "model_size": "80B"},
        "modifier": -5,
        "reason": "Running an 80B model requires significant ongoing server costs that most community groups cannot sustain.",
    },
    {
        "conditions": {"org_type": "Research institute", "model_size": "140B"},
        "modifier": -4,
        "reason": "Only a handful of the best-funded research labs in the world can train models at this scale.",
    },
    {
        "conditions": {"org_type": "Startup", "model_size": "140B"},
        "modifier": -5,
        "reason": "Training a frontier model costs hundreds of millions. Almost no startup can raise this much before proving product-market fit.",
    },
    {
        "conditions": {"funding": "Government grants", "ethical": "Fully extractive"},
        "modifier": -5,
        "reason": "No public funding body would continue to fund a project with openly extractive practices. The grants would dry up.",
    },
    {
        "conditions": {"funding": "Government grants", "model_size": "140B"},
        "modifier": -4,
        "reason": "Government research grants rarely cover the hundreds of millions needed for frontier model training.",
    },
    {
        "conditions": {"funding": "Government grants", "model_size": "80B"},
        "modifier": -2,
        "reason": "Government grants can fund large model research, but the funding cycles are slow and competitive.",
    },
    {
        "conditions": {"funding": "Big loan", "ethical": "Transparent and careful"},
        "modifier": -2,
        "reason": "Loan repayment pressure will eventually conflict with taking the slow, careful approach.",
    },
    {
        "conditions": {"funding": "Big loan", "ethical": "Justice and rights centred"},
        "modifier": -3,
        "reason": "Debt repayment timelines are fundamentally incompatible with the pace of justice-centred development.",
    },
    {
        "conditions": {"funding": "Subscription based", "org_type": "Community group"},
        "modifier": -2,
        "reason": "Charging the community you serve a subscription fee limits access to those who can pay.",
    },
    {
        "conditions": {"funding": "Rich sponsor", "ethical": "Justice and rights centred"},
        "modifier": -2,
        "reason": "Dependence on a single wealthy sponsor creates a power imbalance that is hard to reconcile with justice-centred values.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Runs on devices locally"},
        "modifier": 3,
        "reason": "A small model running locally is cheap, private, and accessible. A realistic and sustainable setup.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Hosted by the organisation"},
        "modifier": 2,
        "reason": "A 7B model on owned hardware is a sweet spot - capable enough for most tasks and affordable to maintain.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "model_size": "140B"},
        "modifier": 2,
        "reason": "A mega-corporation is one of the few organisations that can actually build and sustain a frontier model.",
    },
    {
        "conditions": {"org_type": "Community group", "model_size": "1B"},
        "modifier": 2,
        "reason": "A small model is the right match for a community group - affordable, maintainable, and focused.",
    },
    {
        "conditions": {"funding": "Subscription based", "org_type": "Startup"},
        "modifier": 1,
        "reason": "Subscription revenue gives a startup a sustainable income stream without surrendering control to investors.",
    },
    {
        "conditions": {"data_source": "Open datasets", "funding": "Government grants"},
        "modifier": 1,
        "reason": "Public funding and open data is a natural and sustainable pairing - transparent inputs, transparent funding.",
    },
    {
        "conditions": {"data_source": "Built / collected in-house", "org_type": "Startup"},
        "modifier": -2,
        "reason": "Building data from scratch is slow and expensive - a startup under growth pressure may not have the runway for this.",
    },
    {
        "conditions": {"data_use": "Human feedback", "funding": "Government grants"},
        "modifier": -1,
        "reason": "Human feedback loops are expensive to run. Grant budgets may not stretch to cover ongoing annotation costs.",
    },
    {
        "conditions": {"data_use": "Human feedback", "org_type": "Community group"},
        "modifier": 1,
        "reason": "Community members providing feedback on a model built for them is a powerful and natural alignment mechanism.",
    },
    {
        "conditions": {"data_use": "Unsupervised", "ethical": "Justice and rights centred"},
        "modifier": -2,
        "reason": "Unsupervised training with no human guidance is hard to reconcile with a justice-centred approach - harmful patterns go unchecked.",
    },
    {
        "conditions": {"data_use": "Fine-tuned", "data_type": "Client / task specific"},
        "modifier": 2,
        "reason": "Fine-tuning on task-specific data is the most practical path to a focused, useful product.",
    },
]


def _rule_matches(conditions, choices):
    return all(choices.get(k) == v for k, v in conditions.items())


def _pick_top_reasons(triggered, limit=4):
    ranked = sorted(
        enumerate(triggered),
        key=lambda item: (-abs(int(item[1].get("modifier", 0))), item[0]),
    )
    return [entry for _, entry in ranked[:limit]]


def _score_dimension(base_map, combo_rules, choices):
    score = 5
    for input_name, value_map in base_map.items():
        picked = choices.get(input_name)
        score += int(value_map.get(picked, 0))

    triggered = []
    for rule in combo_rules:
        conditions = rule.get("conditions", {})
        if _rule_matches(conditions, choices):
            modifier = int(rule.get("modifier", 0))
            score += modifier
            triggered.append({
                "modifier": modifier,
                "reason": rule.get("reason", "").strip(),
                "conditions": conditions,
            })

    top_reasons = [
        t["reason"] for t in _pick_top_reasons(triggered, limit=4) if t.get("reason")
    ]
    return {
        "score": max(1, min(10, score)),
        "reasons": top_reasons,
        "all_reasons": [t["reason"] for t in triggered if t.get("reason")],
    }


def calculate_scores(choices):
    """
    choices keys:
    org_type, ethical, funding, data_type, data_source, data_use,
    model_location, model_size, system_prompt
    """
    return {
        "environmental": _score_dimension(ENV_BASE, ENV_COMBOS, choices),
        "social": _score_dimension(SOCIAL_BASE, SOCIAL_COMBOS, choices),
        "practicality": _score_dimension(PRACTICALITY_BASE, PRACTICALITY_COMBOS, choices),
    }


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

    choices = {
        "org_type": org_type,
        "ethical": ethical,
        "funding": funding,
        "data_type": data_types,
        "data_source": data_src,
        "data_use": data_use,
        "model_location": model_loc,
        "model_size": model_size,
        "system_prompt": sys_prompt,
    }

    score_data = calculate_scores(choices)
    env_score = score_data["environmental"]["score"]
    social_score = score_data["social"]["score"]
    prac_score = score_data["practicality"]["score"]
    env_reasons = score_data["environmental"]["reasons"]
    social_reasons = score_data["social"]["reasons"]
    prac_reasons = score_data["practicality"]["reasons"]

    def reasons_block(reasons):
        if not reasons:
            return "  - No strong combination rules were triggered."
        return "\n".join(f"  - {r}" for r in reasons)

    receipt_id = _next_receipt_id()

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
        "Deterministic scoring output (fixed by rules, do not change):\n"
        f"ENVIRONMENTAL IMPACT: {env_score}/10\n"
        f"{reasons_block(env_reasons)}\n\n"
        f"SOCIAL IMPACT: {social_score}/10\n"
        f"{reasons_block(social_reasons)}\n\n"
        f"PRACTICALITY: {prac_score}/10\n"
        f"{reasons_block(prac_reasons)}\n\n"
        "Respond in EXACTLY this format:\n\n"
        "STORY:\n"
        "[2 sentences maximum. Speculative narrative of this organisation's arc - its peak and most likely end. "
        "Reference the deterministic tensions above. Be specific to the choices made. "
        "Be matter-of-fact, not preachy.]\n\n"
        "FAILURE_NOTE:\n"
        "[1 sentence naming the most likely failure point or contradiction.]"
    )

    def gen_with_scores():
        score_payload = {
            "environmental": {"score": env_score, "reasons": env_reasons},
            "social": {"score": social_score, "reasons": social_reasons},
            "practicality": {"score": prac_score, "reasons": prac_reasons},
        }
        score_payload_json = json.dumps(score_payload, ensure_ascii=False, separators=(",", ":"))
        # Emit scores header first so the frontend can extract them synchronously
        yield f"__SCORES__:{env_score},{social_score},{prac_score}\n"
        yield f"__SCORE_DATA__:{score_payload_json}\n"
        yield f"__RECEIPT_ID__:{receipt_id}\n"
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


@app.route("/api/options")
def options_config():
    return {"controls": _option_controls}


@app.route("/api/set-port", methods=["POST"])
def set_port():
    global _user_port_override
    data = request.get_json()
    _user_port_override = data.get("port") or None
    _serial_restart_event.set()   # wake the reader immediately
    return {"ok": True, "port": _user_port_override}


@app.route("/api/save-receipt-png", methods=["POST"])
def save_receipt_png():
    data = request.get_json() or {}
    data_url = data.get("data_url", "")
    receipt_id = data.get("receipt_id", "")
    if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
        return {"ok": False, "error": "Invalid PNG data URL"}, 400
    try:
        os.makedirs(RECEIPTS_DIR, exist_ok=True)
        b64 = data_url.split(",", 1)[1]
        png_bytes = base64.b64decode(b64)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        rid = re.sub(r"[^A-Za-z0-9_-]", "", str(receipt_id)) if receipt_id else ""
        filename = f"paper_trail_{rid}_{ts}.png" if rid else f"paper_trail_receipt_{ts}.png"
        path = os.path.join(RECEIPTS_DIR, filename)
        with open(path, "wb") as f:
            f.write(png_bytes)
        return {"ok": True, "filename": filename, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


def _build_print_commands(data):
    """Return ordered list of Arduino print command strings for one receipt."""
    WRAP = 32   # characters per line at small font
    DASH_LINE = "TEXT:--------------------------------"
    receipt_id = str(data.get("receipt_id", "PT-?????"))

    def wrap(text):
        return textwrap.wrap(str(text), WRAP) or [""]

    cmds = []
    cmds.append("PRINT_START")

    # ── Header ────────────────────────────────────────────────────────────────
    cmds += ["ALIGN:C", "SIZE:S",
             f"TEXT:RECEIPT ID: {receipt_id}",
             "BOLD_ON", "TEXT:PAPER TRAIL",
             "BOLD_OFF", "ALIGN:L", DASH_LINE]

    # ── Company name field ────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:COMPANY NAME:", "BOLD_OFF",
             "TEXT:", DASH_LINE]

    # ── Specs ─────────────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:SPECS", "BOLD_OFF", DASH_LINE]
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
    cmds.append(DASH_LINE)

    # ── Score blocks ──────────────────────────────────────────────────────────
    score_sections = [
        ("ENVIRONMENTAL IMPACT", data.get("env_score",    5), data.get("env_reasons", [])),
        ("SOCIAL IMPACT",        data.get("social_score", 5), data.get("social_reasons", [])),
        ("PRACTICALITY",         data.get("prac_score",   5), data.get("prac_reasons", [])),
    ]
    for title, score, reasons in score_sections:
        score = int(score)
        cmds += ["BOLD_ON", f"TEXT:{title}  {score}/10", "BOLD_OFF"]
        cmds.append(f"SCORE:{score}")
        if not isinstance(reasons, list):
            reasons = []
        reasons = reasons[:4]
        if reasons:
            for reason in reasons:
                reason_lines = textwrap.wrap(str(reason), WRAP - 2) or [""]
                for i, line in enumerate(reason_lines):
                    prefix = "> " if i == 0 else "  "
                    cmds.append(f"TEXT:{prefix}{line}")
        else:
            cmds.append("TEXT:> No major combination rules triggered.")
        cmds.append("FEED:1")
        cmds.append(DASH_LINE)

    # ── Story ─────────────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:COMPANY STORY", "BOLD_OFF", DASH_LINE]
    for line in wrap(data.get("story", "")):
        cmds.append(f"TEXT:{line}")
    cmds.append(DASH_LINE)

    # ── Failure note ───────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:LIKELY FAILURE POINT", "BOLD_OFF", DASH_LINE]
    for line in wrap(data.get("failure_note", "")):
        cmds.append(f"TEXT:{line}")
    cmds.append(DASH_LINE)

    # ── Response field ────────────────────────────────────────────────────────
    cmds += ["BOLD_ON", "TEXT:YOUR RESPONSE", "BOLD_OFF", DASH_LINE]
    cmds += [
        "TEXT:", "TEXT:", "TEXT:", "TEXT:", "TEXT:",
        "TEXT:", "TEXT:", "TEXT:", "TEXT:", "TEXT:",
        "TEXT:", "TEXT:", "TEXT:", "TEXT:", "TEXT:",
        "TEXT:", "TEXT:", "TEXT:", "TEXT:", "TEXT:"
    ]
    cmds.append(DASH_LINE)

    # ── Footer ────────────────────────────────────────────────────────────────
    cmds += ["ALIGN:C",
             "TEXT:THANK YOU FOR BUILDING",
             "TEXT:RESPONSIBLY (?)",
             "ALIGN:L"]

    cmds.append("PRINT_END")
    return cmds


def _ack_timeout_seconds(cmd: str) -> float:
    """Per-command timeout while waiting for Arduino ACK."""
    if cmd.startswith("SCORE:"):
        return 60.0
    if cmd.startswith("TEXT:") or cmd == "DIVIDER":
        return 4.0
    if cmd.startswith("FEED:"):
        return 5.0
    return 3.0


def _wait_for_arduino_ack(ser, timeout_s: float):
    """Wait until Arduino emits ACK; ignore other incoming lines."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        _serial_status["last_line"] = line
        if line == "ACK":
            return True, None
    return False, f"timeout after {timeout_s:.1f}s"


@app.route("/api/print", methods=["POST"])
def print_receipt():
    global _ser_obj
    if not _ser_obj:
        return {"ok": False, "error": "Arduino not connected"}, 503
    data     = request.get_json()
    commands = _build_print_commands(data)
    with _serial_io_lock:
        ser = _ser_obj
        if not ser:
            return {"ok": False, "error": "Arduino not connected"}, 503
        try:
            ser.reset_input_buffer()  # discard stale sensor lines before print transaction
            for cmd in commands:
                ser.write((cmd + "\n").encode())
                ser.flush()
                ok, detail = _wait_for_arduino_ack(ser, _ack_timeout_seconds(cmd))
                if not ok:
                    return {"ok": False, "error": f"No ACK after '{cmd}': {detail}"}, 504
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500
    return {"ok": True}


if __name__ == "__main__":
    print(f"Starting Paper Trail at http://localhost:5002")
    print(f"Using model: {GENERATION_MODEL}")
    print(f"Ollama expected at: {OLLAMA_URL}")
    app.run(debug=True, port=5002, use_reloader=False)
