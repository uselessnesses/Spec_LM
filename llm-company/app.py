import json
import os
import threading
import time

import requests
import serial
import serial.tools.list_ports
from flask import Flask, Response, request, send_file, stream_with_context

app = Flask(__name__)

# ── Arduino serial knob ───────────────────────────────────────────────────────
SERIAL_PORT = None   # None = auto-detect; override e.g. "/dev/cu.usbmodem10"
SERIAL_BAUD = 9600
_knob_value = 512    # default midpoint (0–1023)
_serial_lock = threading.Lock()


def _find_arduino_port():
    for p in serial.tools.list_ports.comports():
        desc = (p.description + p.hwid).lower()
        if any(k in desc for k in ('arduino', 'usbmodem', 'usbserial', 'ch340', 'cp210')):
            return p.device
    return None


def _serial_reader():
    global _knob_value
    port = SERIAL_PORT or _find_arduino_port()
    if not port:
        print("[SERIAL] No Arduino found — knob disabled. Set SERIAL_PORT manually if needed.")
        return
    print(f"[SERIAL] Connecting to {port} at {SERIAL_BAUD} baud…")
    while True:
        try:
            with serial.Serial(port, SERIAL_BAUD, timeout=2) as ser:
                print(f"[SERIAL] Connected.")
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line.isdigit():
                        with _serial_lock:
                            _knob_value = int(line)
        except Exception as e:
            print(f"[SERIAL] Error: {e} — retrying in 3s")
            time.sleep(3)


threading.Thread(target=_serial_reader, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
GENERATION_MODEL = "llama3.2:3b"   # change this to use a different model

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# Ethical tone strings mapped to slider positions 1-7
ETHICAL_TONES = {
    1: (
        "The company is deeply ethical and idealistic. It exists to serve a marginalised "
        "community or address a genuine social/environmental crisis. Its mission statement "
        "should sound sincere, humble, and focused on collective good."
    ),
    2: (
        "The company is well-intentioned with a clear social purpose. Mostly ethical with "
        "some pragmatic business language. Genuine but realistic."
    ),
    3: (
        "The company is a social enterprise — trying to do good but also needs to be "
        "sustainable. Mix of idealism and business pragmatism."
    ),
    4: (
        "The company is a standard tech startup. Neutral corporate tone. Talks about "
        "innovation, disruption, and market opportunity. Ethics mentioned vaguely if at all."
    ),
    5: (
        "The company is commercially aggressive. Focused on growth, scale, data extraction, "
        "and market dominance. Ethics are PR dressing."
    ),
    6: (
        "The company is ethically dubious. It does something that sounds useful but has "
        "clear potential for exploitation, surveillance, or harm. The mission statement "
        "tries to spin this positively."
    ),
    7: (
        "The company is actively harmful but disguised in positive corporate language. "
        "Think surveillance tech sold as safety, or extraction sold as empowerment. "
        "The mission statement sounds inspiring but is sinister if you read carefully."
    ),
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


@app.route("/api/knob")
def knob():
    with _serial_lock:
        return {"value": _knob_value}


@app.route("/api/company-function", methods=["POST"])
def company_function():
    data = request.get_json()
    position = max(1, min(7, int(data.get("position", 4))))
    tone = ETHICAL_TONES[position]

    prompt = (
        "Generate a short description of a fictional AI company. Include:\n"
        "1. What the company does (one sentence, max 20 words, specific and concrete)\n"
        "2. A mission statement / manifesto for the company (2 sentences maximum)\n\n"
        f"Ethical tone: {tone}\n\n"
        "Generate something different from previous responses. Be creative and specific.\n"
        "Do NOT invent a company name.\n\n"
        "Respond in EXACTLY this format, nothing else:\n"
        "FUNCTION: [what the company does]\n"
        "MISSION: [the mission statement / manifesto]"
    )

    return streamed(stream_ollama(prompt, num_predict=100, temperature=0.92))


@app.route("/api/company-name", methods=["POST"])
def company_name():
    data = request.get_json()
    company_function = data.get("company_function", "an AI company")
    previous_names = data.get("previous_names", [])

    avoid = ""
    if previous_names:
        avoid = f"\nGenerate a completely different name from: {', '.join(previous_names)}"

    prompt = (
        f'Generate a single company name for a fictional AI company that does the following:\n'
        f'"{company_function}"\n\n'
        "The name should feel like a real tech company name — it can be a made-up word, "
        "an acronym, a portmanteau, or a real word used cleverly.\n"
        "Just the name, nothing else. No quotes, no explanation, no punctuation."
        f"{avoid}"
    )

    return streamed(stream_ollama(prompt, num_predict=15, temperature=0.95))


@app.route("/api/describe", methods=["POST"])
def describe():
    data = request.get_json()
    company_name = data.get("company_name", "the company")
    company_function = data.get("company_function", "an AI service")
    stage = data.get("stage", "business_model")
    data_type = data.get("data_type", "")

    if stage == "business_model":
        prompt = (
            f'An AI company called "{company_name}" does the following: "{company_function}"\n\n'
            "For each of the following funding models, write one sentence only (max 20 words) "
            "on what it would specifically mean for this company — who has power and what "
            "compromises might be made.\n\n"
            "Respond in EXACTLY this format:\n"
            "GOVT_GRANTS: [explanation]\n"
            "PAY_TO_PLAY: [explanation]\n"
            "BIG_LOAN: [explanation]\n"
            "RICH_DONOR: [explanation]"
        )
    elif stage == "data_type":
        prompt = (
            f'An AI company called "{company_name}" does the following: "{company_function}"\n\n'
            "For each of the following training data types, write one sentence only (max 20 words) "
            "on what this data would mean for this specific company.\n\n"
            "Respond in EXACTLY this format:\n"
            "GENERAL_WEB: [explanation]\n"
            "BOOKS_ACADEMIC: [explanation]\n"
            "PROPRIETARY_CLIENT: [explanation]\n"
            "SOCIAL_MEDIA: [explanation]"
        )
    elif stage == "data_acquisition":
        data_type_label = data_type or "general"
        prompt = (
            f'An AI company called "{company_name}" does the following: "{company_function}". '
            f"It trains its model on {data_type_label} data.\n\n"
            "For each of the following data acquisition methods, write one sentence only "
            "(max 20 words) on what this would mean for this company.\n\n"
            "Respond in EXACTLY this format:\n"
            "SCRAPED: [explanation]\n"
            "LICENSED: [explanation]\n"
            "CROWDSOURCED: [explanation]\n"
            "SYNTHETIC: [explanation]"
        )
    else:
        return streamed(iter(["Unknown stage"]))

    return streamed(stream_ollama(prompt, num_predict=130, temperature=0.8))


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    name = data.get("company_name", "Unnamed Corp")
    function = data.get("company_function", "an AI company")
    mission = data.get("mission_statement", "")
    business_model = data.get("business_model", "unknown")
    data_type = data.get("data_type", "unknown")
    acquisition = data.get("data_acquisition", "unknown")
    model_size = data.get("model_size", "7B")
    hosting = data.get("hosting", "cloud")

    prompt = (
        "You are a speculative fiction analyst examining a fictional AI company. "
        "Based on the following design choices, write a brief critical analysis.\n\n"
        f"COMPANY NAME: {name}\n"
        f"COMPANY FUNCTION: {function}\n"
        f'MISSION: "{mission}"\n'
        f"BUSINESS MODEL: {business_model}\n"
        f"DATA TYPE: {data_type}\n"
        f"DATA ACQUISITION: {acquisition}\n"
        f"MODEL SIZE: {model_size}\n"
        f"HOSTING: {hosting}\n\n"
        "Respond with EXACTLY this format (keep each section very concise):\n\n"
        "STORY:\n"
        "[Write a 3-4 sentence speculative narrative of this company's trajectory — its "
        "founding, its peak, and its end. If the company is likely to fail, say so. If it "
        "would cause tangible harm, describe it plainly. If it could do genuine good, say "
        "that too. Be specific to the choices made. Do not be preachy — be matter-of-fact.]\n\n"
        "SOCIETAL_IMPACT: [a single integer from 1-10, where 1 = deeply harmful, 10 = profoundly beneficial]\n\n"
        "ENVIRONMENTAL_IMPACT: [a single integer from 1-10, where 1 = devastating damage, 10 = actively regenerative]\n\n"
        "FAILURE_NOTE:\n"
        "[One sentence on the most likely way this company fails or causes harm, linking it "
        "to a specific design choice made above.]"
    )

    return streamed(stream_ollama(prompt, num_predict=450, temperature=0.7))


if __name__ == "__main__":
    print(f"Starting Build Your Speculative AI Company at http://localhost:5002")
    print(f"Using model: {GENERATION_MODEL}")
    print(f"Ollama expected at: {OLLAMA_URL}")
    app.run(debug=True, port=5002)
