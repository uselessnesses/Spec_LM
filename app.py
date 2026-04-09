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
_btn_back      = 0
_btn_next      = 0
_btn_reset     = 0
SMOOTH_ALPHA   = 0.25
_serial_lock          = threading.Lock()
_serial_io_lock       = threading.Lock()
_serial_status        = {"connected": False, "port": None, "error": None, "last_line": ""}
_user_port_override   = None          # set via /api/set-port
_serial_restart_event = threading.Event()
_ser_obj              = None          # active Serial instance, set by _serial_reader
_MANUAL_DISCONNECT_TOKEN = "__MANUAL_DISCONNECT__"
_SERIAL_RETRY_LOG_INTERVAL_S = 20.0


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


def _list_available_ports_strings():
    """Human-readable list of all serial ports currently visible to pyserial."""
    if not _SERIAL_AVAILABLE:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        desc = p.description or "Unknown device"
        out.append(f"{p.device} ({desc})")
    return out


def _serial_reader():
    global _knob_value, _knob2_value, _slider_value
    global _knob_raw, _knob2_raw, _slider_raw
    global _btn_back, _btn_next, _btn_reset
    global _knob_smooth, _knob2_smooth, _slider_smooth
    global _serial_status, _user_port_override, _ser_obj
    if not _SERIAL_AVAILABLE:
        _serial_status = {"connected": False, "port": None, "error": "pyserial not installed"}
        return

    last_log_key = None
    last_log_time = 0.0

    def throttled_log(key, msg):
        nonlocal last_log_key, last_log_time
        now = time.monotonic()
        if key != last_log_key or (now - last_log_time) >= _SERIAL_RETRY_LOG_INTERVAL_S:
            print(msg)
            last_log_key = key
            last_log_time = now

    while True:
        # Manual disconnect mode: stay detached until user picks a port.
        if _user_port_override == _MANUAL_DISCONNECT_TOKEN:
            last_line = _serial_status.get("last_line", "")
            _serial_status = {
                "connected": False,
                "port": None,
                "error": "Disconnected by user. Click NO DEVICE to pick a port.",
                "last_line": last_line,
            }
            throttled_log("manual_disconnect", "[SERIAL] Manually disconnected. Waiting for port selection...")
            _serial_restart_event.wait(timeout=1)
            _serial_restart_event.clear()
            continue

        # Resolve port: user override → hardcoded → auto-detect
        port = _user_port_override or SERIAL_PORT
        if not port:
            candidates = _list_candidate_ports()
            port = candidates[0] if candidates else None

        if not port:
            all_ports = _list_available_ports_strings()
            last_line = _serial_status.get("last_line", "")
            _serial_status = {
                "connected": False,
                "port": None,
                "error": "No Arduino found. Plug in USB and wait, or click NO DEVICE to pick a port.",
                "last_line": last_line,
            }
            if all_ports:
                preview = ", ".join(all_ports[:6])
                if len(all_ports) > 6:
                    preview += ", ..."
                throttled_log(
                    ("no_arduino", tuple(all_ports)),
                    f"[SERIAL] No likely Arduino port yet. Available serial ports: {preview}. Retrying in 3s...",
                )
            else:
                throttled_log(
                    "no_serial_ports",
                    "[SERIAL] No serial ports detected. Plug in USB and wait, or click NO DEVICE to pick a port. Retrying in 3s...",
                )
            _serial_restart_event.wait(timeout=3)
            _serial_restart_event.clear()
            continue

        throttled_log(("connect_attempt", port), f"[SERIAL] Connecting to {port} at {SERIAL_BAUD} baud...")
        try:
            with serial.Serial(port, SERIAL_BAUD, timeout=0.25) as ser:
                ser.reset_input_buffer()
                _ser_obj = ser
                _serial_status = {"connected": True, "port": port, "error": None}
                print(f"[SERIAL] Connected on {port}.")
                last_log_key = None
                while True:
                    try:
                        with _serial_io_lock:
                            line = ser.readline().decode("utf-8", errors="ignore").strip()
                    except OSError:
                        if not ser.is_open:
                            break  # port was closed externally; exit inner loop
                        continue  # transient USB-serial artefact
                    if line:
                        _serial_status["last_line"] = line
                    parts = line.split(",")
                    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                        k1 = int(parts[0])
                        k2 = int(parts[1])
                        s  = int(parts[2])
                        btn_back = 0
                        btn_next = 0
                        btn_reset = 0
                        if len(parts) >= 6 and all(p.isdigit() for p in parts[3:6]):
                            btn_back = 1 if int(parts[3]) > 0 else 0
                            btn_next = 1 if int(parts[4]) > 0 else 0
                            btn_reset = 1 if int(parts[5]) > 0 else 0
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
                            _btn_back      = btn_back
                            _btn_next      = btn_next
                            _btn_reset     = btn_reset
        except Exception as e:
            last_line = _serial_status.get("last_line", "")
            _serial_status = {"connected": False, "port": port, "error": str(e), "last_line": last_line}
            throttled_log(("connect_error", port, str(e)), f"[SERIAL] Error on {port}: {e} — retrying in 3s")
            _ser_obj = None
            time.sleep(3)


threading.Thread(target=_serial_reader, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
GENERATION_MODEL = "llama3.2"   # change this to use a different model
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "5002"))

INDEX_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
OPTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trail_options.csv")
RECEIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt_pngs")
RECEIPT_COUNTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt_counter.txt")
_receipt_id_lock = threading.Lock()

# ── Load option copy + scoring CSV ───────────────────────────────────────────
_option_controls = {}
_options_mtime = None


def _load_option_config():
    """
    Load canonical option copy from paper_trail_options.csv.
    """
    global _option_controls, _options_mtime
    _option_controls = {}
    _options_mtime = None

    if os.path.exists(OPTIONS_PATH):
        try:
            rows_by_control = {}
            with open(OPTIONS_PATH, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    control_key = row.get('control_key', '').strip()
                    option_label = row.get('option_label', '').strip()
                    option_desc = row.get('option_desc', '').strip()
                    if not control_key or not option_label:
                        continue
                    try:
                        option_index = int(str(row.get('option_index', '')).strip())
                    except ValueError:
                        # Keep malformed rows deterministic by placing them at the end.
                        option_index = 10_000
                    if control_key not in rows_by_control:
                        rows_by_control[control_key] = []
                    rows_by_control[control_key].append((option_index, option_label, option_desc))

            # Build compact arrays in index order (no empty gaps if indices were removed).
            for control_key, entries in rows_by_control.items():
                entries.sort(key=lambda item: item[0])
                _option_controls[control_key] = {
                    "names": [label for _, label, _ in entries],
                    "descs": [desc for _, _, desc in entries],
                }

            _options_mtime = os.path.getmtime(OPTIONS_PATH)
            print(f"[CONFIG] Loaded option copy for {len(_option_controls)} controls from paper_trail_options.csv")
            return
        except Exception as e:
            print(f"[CONFIG] Failed to parse {OPTIONS_PATH}: {e}")
    print(f"[CONFIG] {OPTIONS_PATH} not found - using built-in frontend CTRL defaults")


_load_option_config()
# ─────────────────────────────────────────────────────────────────────────────


def _maybe_reload_option_config():
    """Reload options CSV if it changed since the last successful load."""
    global _options_mtime
    try:
        current_mtime = os.path.getmtime(OPTIONS_PATH)
    except OSError:
        current_mtime = None
    if current_mtime != _options_mtime:
        _load_option_config()


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
        "Outsourced to a tech giant": -1,
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
        "conditions": {"model_size": "140B", "model_location": "Outsourced to a tech giant"},
        "modifier": -2,
        "reason": "A very large model on third-party cloud servers uses a lot of power over time, and that power may come from fossil fuels.",
    },
        {
        "conditions": {"model_size": "140B", "model_location": "Hosted by the organisation"},
        "modifier": -2,
        "reason": "A 140B model hosted by the organisation still needs a lot of server power every day.",
    },
    {
        "conditions": {"model_size": "140B", "model_location": "Decentralised"},
        "modifier": -3,
        "reason": "A decentralised 140B setup repeats heavy compute across many machines, so total energy use becomes very high.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Runs on devices locally"},
        "modifier": 2,
        "reason": "A small model running on local devices usually has a very low energy cost.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Runs on devices locally"},
        "modifier": 1,
        "reason": "A 7B model can run well on many modern devices, which helps keep energy use lower.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Runs on devices locally"},
        "modifier": 1,
        "reason": "A 14B model running locally can reduce reliance on always-on central servers.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Hosted by the organisation"},
        "modifier": 1,
        "reason": "A 7B model hosted by the organisation can be run efficiently without the heavy power use of very large models.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Hosted by the organisation"},
        "modifier": 1,
        "reason": "A 14B model hosted by the organisation can be scheduled and managed to use power more efficiently.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Decentralised"},
        "modifier": 1,
        "reason": "A decentralised 7B model can share work across many devices, which can reduce pressure on big data centres.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Decentralised"},
        "modifier": 1,
        "reason": "A decentralised 14B setup can make better use of existing hardware when the work is shared well.",
    },
    {
        "conditions": {"ethical": "Justice and rights centred", "model_size": "1B"},
        "modifier": 1,
        "reason": "Choosing a small model shows a clear effort to reduce environmental harm.",
    },
    {
        "conditions": {"ethical": "Harm-tolerant", "model_size": "140B"},
        "modifier": -1,
        "reason": "When the goal is extraction, there is little reason to reduce environmental damage.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "model_size": "140B"},
        "modifier": -1,
        "reason": "At mega-corporation scale, a 140B model can use huge amounts of energy.",
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
        "reason": "A public body using extractive practices could harm the citizens it is supposed to serve.",
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
        "modifier": -5,
        "reason": "Scraping client-specific data without consent is a serious breach of trust.",
    },
    {
        "conditions": {"org_type": "Community group", "data_source": "Scraped"},
        "modifier": -5,
        "reason": "A community organisation scraping data contradicts the trust-based relationship it depends on.",
    },
    {
        "conditions": {"data_type": "Social media", "data_source": "Scraped"},
        "modifier": -2,
        "reason": "Scraping social media content means using people's personal expression without their knowledge or consent.",
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
    {
        "conditions": {"org_type": "Public / governmental", "funding": "Government grants", "ethical": "Transparent and careful"},
        "modifier": 2,
        "reason": "Public funding with a careful, transparent approach can build trust because people can see how decisions are made.",
    },
    {
        "conditions": {"org_type": "Public / governmental", "funding": "Government grants", "ethical": "Harm-tolerant"},
        "modifier": -4,
        "reason": "A public body using taxpayer money while tolerating harm breaks public trust.",
    },
    {
        "conditions": {"org_type": "Public / governmental", "funding": "Rich sponsor"},
        "modifier": -3,
        "reason": "A public body funded by one rich sponsor risks private influence over public decisions.",
    },
    {
        "conditions": {"org_type": "Public / governmental", "funding": "Pay-per-use"},
        "modifier": -2,
        "reason": "Pay-per-use in a public service can shut out people who need support but cannot pay.",
    },
    {
        "conditions": {"org_type": "Community group", "funding": "Big loan", "ethical": "Growth-first"},
        "modifier": -3,
        "reason": "Debt and growth pressure can push a community group to prioritise repayment over people.",
    },
    {
        "conditions": {"org_type": "Community group", "funding": "Pay-per-use", "ethical": "Justice and rights centred"},
        "modifier": -2,
        "reason": "A pay-per-use model can conflict with a rights-centred promise if people are priced out.",
    },
    {
        "conditions": {"org_type": "Research institute", "funding": "Rich sponsor", "ethical": "Growth-first"},
        "modifier": -3,
        "reason": "A rich sponsor plus growth-first pressure can weaken research independence.",
    },
    {
        "conditions": {"org_type": "Research institute", "funding": "Government grants", "ethical": "Transparent and careful"},
        "modifier": 2,
        "reason": "Public grants and careful governance are a strong social fit for independent research.",
    },
    {
        "conditions": {"org_type": "Startup", "funding": "Big loan", "ethical": "Harm-tolerant"},
        "modifier": -3,
        "reason": "A startup under loan pressure that tolerates harm is likely to cut safety to stay afloat.",
    },
    {
        "conditions": {"org_type": "Startup", "funding": "Subscription based", "ethical": "Transparent and careful"},
        "modifier": 1,
        "reason": "A subscription model with careful governance can support steady growth without constant pressure to exploit users.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "funding": "Government grants", "ethical": "Growth-first"},
        "modifier": -3,
        "reason": "Public grants used by a growth-first mega-corporation can shift public value into private power.",
    },
    {
        "conditions": {"org_type": "Mega-corporation", "funding": "Pay-per-use", "ethical": "Harm-tolerant"},
        "modifier": -3,
        "reason": "Charging by use while tolerating harm can lock vulnerable users into costly, unsafe systems.",
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
        "reason": "An 80 billion parameter model requires specialised hardware. It will not run on a normal phone or laptop.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Runs on devices locally"},
        "modifier": -4,
        "reason": "A 14B model can technically run on high-end consumer hardware, but performance will be poor and battery life terrible.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Runs on devices locally"},
        "modifier": 1,
        "reason": "A 7B model can run locally on stronger consumer hardware, so this setup is realistic for many teams.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Hosted by the organisation"},
        "modifier": -1,
        "reason": "Hosting a 1B model on servers can be unnecessary overhead when it could run locally.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Hosted by the organisation"},
        "modifier": 1,
        "reason": "A 14B model hosted by the organisation is demanding but usually workable with modest server hardware.",
    },
    {
        "conditions": {"model_size": "140B", "model_location": "Hosted by the organisation"},
        "modifier": -6,
        "reason": "A 140B model hosted in-house requires very large infrastructure and specialist staff.",
    },
    {
        "conditions": {"model_size": "140B", "model_location": "Decentralised"},
        "modifier": -6,
        "reason": "Coordinating a frontier-scale model across decentralised nodes is an unsolved engineering problem.",
    },
    {
        "conditions": {"model_size": "80B", "model_location": "Decentralised"},
        "modifier": -5,
        "reason": "An 80B model is very hard to run in a decentralised way because each node needs heavy compute.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Decentralised"},
        "modifier": -2,
        "reason": "A decentralised 14B model is possible but difficult to run reliably across mixed hardware.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Decentralised"},
        "modifier": -1,
        "reason": "Decentralising a 7B model can work, but coordination overhead often slows delivery.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Decentralised"},
        "modifier": -2,
        "reason": "A decentralised setup for a 1B model adds complexity for little practical gain.",
    },
    {
        "conditions": {"model_size": "1B", "model_location": "Outsourced to a tech giant"},
        "modifier": -2,
        "reason": "Using a tech giant for a 1B model is usually overkill and adds avoidable vendor dependency.",
    },
    {
        "conditions": {"model_size": "7B", "model_location": "Outsourced to a tech giant"},
        "modifier": -1,
        "reason": "A 7B model can often be hosted directly, so outsourcing may add extra cost and lock-in.",
    },
    {
        "conditions": {"model_size": "14B", "model_location": "Outsourced to a tech giant"},
        "modifier": 1,
        "reason": "Outsourcing a 14B model can be practical when a team lacks in-house infrastructure.",
    },
    {
        "conditions": {"model_size": "80B", "model_location": "Outsourced to a tech giant"},
        "modifier": 2,
        "reason": "Outsourcing an 80B model is often the most practical way to access this scale.",
    },
    {
        "conditions": {"model_size": "140B", "model_location": "Outsourced to a tech giant"},
        "modifier": 2,
        "reason": "For 140B models, outsourcing is one of the few practical options for most organisations.",
    },
    {
        "conditions": {"org_type": "Community group", "model_size": "140B"},
        "modifier": -7,
        "reason": "A community group cannot afford the infrastructure to train or run a frontier-scale model. The compute costs alone would consume the entire budget.",
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
        "reason": "Unsupervised training with no human guidance is hard to reconcile with a justice-centred approach.",
    },
    {
        "conditions": {"data_use": "Fine-tuned", "data_type": "Client / task specific"},
        "modifier": 2,
        "reason": "Fine-tuning on task-specific data is the most practical path to a focused, useful product.",
    },
]

CHOICE_VALUE_ALIASES = {
    "model_location": {
        "Outsourced to third party": "Outsourced to a tech giant",
    },
}

RECEIPT_REASON_LIMIT = 3


def _normalise_choices(choices):
    normalised = dict(choices)
    for key, aliases in CHOICE_VALUE_ALIASES.items():
        value = normalised.get(key)
        if isinstance(value, str):
            normalised[key] = aliases.get(value, value)
    return normalised


def _rule_matches(conditions, choices):
    return all(choices.get(k) == v for k, v in conditions.items())


def _pick_top_reasons(triggered, limit=RECEIPT_REASON_LIMIT):
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
        t["reason"] for t in _pick_top_reasons(triggered, limit=RECEIPT_REASON_LIMIT) if t.get("reason")
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
    normalised_choices = _normalise_choices(choices)
    return {
        "environmental": _score_dimension(ENV_BASE, ENV_COMBOS, normalised_choices),
        "social": _score_dimension(SOCIAL_BASE, SOCIAL_COMBOS, normalised_choices),
        "practicality": _score_dimension(PRACTICALITY_BASE, PRACTICALITY_COMBOS, normalised_choices),
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
            "btn_back":   _btn_back,
            "btn_next":   _btn_next,
            "btn_reset":  _btn_reset,
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
        "You are an objective AI risk analyst. Based on these organisation design choices, "
        "write a concise, factual output that gives an overview of the risks, practical considerations and how long the organisation might last and why. Use simple language.\n\n"
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
        "[Maximum 30 words. One sentence. Objective and specific. "
        "Use only SOCIAL IMPACT and PRACTICALITY flags/reasons for your explanation. Ignore environmental flags. "
        "Include a lifespan estimate in years and a clear cause from the choices above. "
        "Examples of acceptable framing: 'Likely lifespan: 2-3 years, because ...' or "
        "'The organisation was still going after 45 years due to ...'. "
        "Reference concrete tensions/reasons indirectly; do not quote full reasons. "
        "If SOCIAL IMPACT is 3/10 or lower, explicitly include one concrete harm that was caused. "
        "Do not mention numeric score values or phrases like 'low social impact'. "
        "Never invent or mention any company/organisation name, title, or brand. "
        "Avoid flowery language.]"
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
        yield from stream_ollama(prompt, num_predict=160, temperature=0.4)

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
    _maybe_reload_option_config()
    return {"controls": _option_controls}


@app.route("/api/set-port", methods=["POST"])
def set_port():
    global _user_port_override
    data = request.get_json() or {}
    requested = (data.get("port") or "").strip()
    _user_port_override = requested or None
    _serial_restart_event.set()   # wake the reader immediately
    return {"ok": True, "port": _user_port_override}


@app.route("/api/disconnect-port", methods=["POST"])
def disconnect_port():
    global _user_port_override, _ser_obj, _serial_status
    _user_port_override = _MANUAL_DISCONNECT_TOKEN

    # Close current serial handle (if any) so the reader loop drops immediately.
    with _serial_io_lock:
        ser = _ser_obj
        _ser_obj = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass

    last_line = _serial_status.get("last_line", "")
    _serial_status = {
        "connected": False,
        "port": None,
        "error": "Disconnected by user. Click NO DEVICE to pick a port.",
        "last_line": last_line,
    }
    _serial_restart_event.set()
    return {"ok": True}


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


def _normalize_spaces(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


STORY_MAX_WORDS = 30
LOW_SOCIAL_HARM_THRESHOLD = 3


def _truncate_words(text, max_words):
    clean = _normalize_spaces(text)
    if not clean:
        return ""
    words = clean.split(" ")
    if len(words) <= max_words:
        return clean
    return " ".join(words[:max_words])


def _word_count(text):
    clean = _normalize_spaces(text)
    return len(clean.split(" ")) if clean else 0


def _story_looks_like_named_org(text):
    if re.search(r"\b(named|called|known as|branded as|titled)\b", text, flags=re.IGNORECASE):
        return True
    if re.search(r"[\"“”'‘’][^\"“”'‘’]{2,40}[\"“”'‘’]", text):
        return True
    return False


def _story_looks_flowery(text):
    return re.search(
        r"\b(visionary|transformative|revolutionary|groundbreaking|utopian|inspiring|remarkable|extraordinary)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_mentions_score_tension(text):
    return re.search(
        r"\b(social|practical|fund|grant|loan|subscription|data|model|compute|cost|feasib|viab|sustain|risk|impact|trust|consent|adoption|safeguard)\w*\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_mentions_environment_dimension(text):
    return re.search(
        r"\b(environment|environmental|carbon|emission|climate|ecology|biodiversity)\w*\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_mentions_lifespan(text):
    return re.search(
        r"\b(\d+\s*-\s*\d+\s*years?|\d+\+?\s*years?|under\s+\d+\s*years?|within\s+\d+\s*years?|months?)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_has_causal_link(text):
    return re.search(
        r"\b(because|due to|driven by|caused by|as|after|from)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_too_score_focused(text):
    return re.search(
        r"\b\d+\s*\/\s*10\b|\b(low|high)\s+(environmental impact|social impact|practicality)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _story_mentions_harm(text):
    return re.search(
        r"\b(harm|harmed|harms|exploit|exploitation|abuse|abusive|injury|injuries|surveillance|discrimination|unsafe|misuse|consent breach|privacy)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _reason_snippet(reasons, max_words=10):
    if not isinstance(reasons, list):
        return ""
    for reason in reasons:
        if not reason:
            continue
        first_clause = re.split(r"[.!?]", str(reason), maxsplit=1)[0]
        snippet = _truncate_words(first_clause, max_words).rstrip(" ,;:-")
        if snippet:
            return snippet[0].lower() + snippet[1:] if len(snippet) > 1 else snippet.lower()
    return ""


def _harm_phrase_from_reasons(reasons):
    blob = " ".join(str(r).lower() for r in (reasons or []) if r)
    if re.search(r"consent|scrap|social media|personal expression|without their knowledge", blob):
        return "non-consensual data use"
    if re.search(r"crowd|underpay|labour|extractive", blob):
        return "exploitative labour practices"
    if re.search(r"weapon|guardrail|safety", blob):
        return "unsafe outputs enabling misuse"
    if re.search(r"public body|citizens|community|trust", blob):
        return "loss of trust in essential services"
    if re.search(r"surveillance|privacy", blob):
        return "surveillance and privacy abuse"
    return "people being harmed through unfair deployment"


def _estimate_lifespan_phrase(social_score, prac_score):
    viability = (0.6 * float(prac_score)) + (0.4 * float(social_score))
    if viability <= 2.5:
        return "under 1 year"
    if viability <= 3.5:
        return "1-2 years"
    if viability <= 4.5:
        return "2-3 years"
    if viability <= 6.0:
        return "3-5 years"
    if viability <= 7.5:
        return "5-8 years"
    if viability <= 9.0:
        return "8-12 years"
    if viability <= 9.4:
        return "12-20 years"
    return "45 years"


def _fallback_story_from_scores(data):
    social = int(data.get("social_score", 5))
    prac = int(data.get("prac_score", 5))
    dims = [
        ("social", social, data.get("social_reasons", [])),
        ("practicality", prac, data.get("prac_reasons", [])),
    ]
    worst_key, _, _ = min(dims, key=lambda x: x[1])
    lifespan = _estimate_lifespan_phrase(social, prac)

    snippet = ""
    snippet_words = 7 if social <= LOW_SOCIAL_HARM_THRESHOLD else 9
    ordered_reasons = [reasons for key, _, reasons in dims if key == worst_key] + [reasons for key, _, reasons in dims if key != worst_key]
    for reasons in ordered_reasons:
        snippet = _reason_snippet(reasons, max_words=snippet_words)
        if snippet:
            break

    low_social = social <= LOW_SOCIAL_HARM_THRESHOLD
    harm_phrase = _harm_phrase_from_reasons(
        (data.get("social_reasons", []) or [])
        + (data.get("prac_reasons", []) or [])
    )

    if low_social and snippet:
        sentence = f"Expected lifespan is {lifespan} because {snippet}; harm included {harm_phrase}."
    elif low_social:
        sentence = f"Expected lifespan is {lifespan} because social safeguards failed; harm included {harm_phrase}."
    elif lifespan == "45 years":
        if snippet:
            sentence = f"The organisation was still going after 45 years due to {snippet}."
        else:
            sentence = "The organisation was still going after 45 years due to resilient funding, manageable operating costs, and sustained public trust."
    elif snippet and worst_key == "practicality":
        sentence = f"Likely lifespan is {lifespan} because {snippet}."
    elif snippet and worst_key == "social":
        sentence = f"Expected lifespan is {lifespan} because {snippet}."
    elif snippet:
        sentence = f"Estimated lifespan is {lifespan} because {snippet}."
    elif worst_key == "practicality":
        sentence = f"Likely lifespan is {lifespan} because delivery and operating costs are hard to sustain."
    elif worst_key == "social":
        sentence = f"Expected lifespan is {lifespan} because trust and consent issues reduce adoption."
    else:
        sentence = f"Estimated lifespan is {lifespan} because energy and resource demands compound over time."

    if _word_count(sentence) > STORY_MAX_WORDS:
        sentence = _truncate_words(sentence, STORY_MAX_WORDS).rstrip(" ,;:-")
    if not sentence.endswith((".", "!", "?")):
        sentence += "."
    return sentence


def _sanitize_story_for_receipt(story_text, data):
    clean = _normalize_spaces(story_text)
    clean = re.sub(r"^\s*story\s*:\s*", "", clean, flags=re.IGNORECASE)
    clean = clean.rstrip(" ,;:-")
    low_social = int(data.get("social_score", 5)) <= LOW_SOCIAL_HARM_THRESHOLD

    if clean and (
        _word_count(clean) > STORY_MAX_WORDS
        or clean.count(".") + clean.count("!") + clean.count("?") > 1
        or _story_looks_like_named_org(clean)
        or _story_looks_flowery(clean)
        or _story_mentions_environment_dimension(clean)
        or _story_too_score_focused(clean)
        or not _story_mentions_lifespan(clean)
        or not _story_has_causal_link(clean)
        or not _story_mentions_score_tension(clean)
        or (low_social and not _story_mentions_harm(clean))
    ):
        clean = ""

    if not clean:
        clean = _fallback_story_from_scores(data)

    if not clean.endswith((".", "!", "?")):
        clean += "."
    return clean


def _build_print_commands(data):
    """Return ordered list of Arduino print command strings for one receipt."""
    WRAP = 32   # characters per line at small font
    DASH_LINE = "TEXT:--------------------------------"
    receipt_id = str(data.get("receipt_id", "PT-?????"))

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
        reasons = reasons[:RECEIPT_REASON_LIMIT]
        if reasons:
            for reason in reasons:
                reason_lines = textwrap.wrap(str(reason), WRAP - 2) or [""]
                for i, line in enumerate(reason_lines):
                    prefix = "> " if i == 0 else "  "
                    cmds.append(f"TEXT:{prefix}{line}")
        cmds.append("FEED:1")
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
    print(f"Starting Paper Trail on {APP_HOST}:{APP_PORT}")
    if APP_HOST == "0.0.0.0":
        print(f"Open locally: http://localhost:{APP_PORT}")
    print(f"Using model: {GENERATION_MODEL}")
    print(f"Ollama expected at: {OLLAMA_URL}")
    app.run(host=APP_HOST, debug=True, port=APP_PORT, use_reloader=False)
