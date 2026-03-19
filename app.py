import json
import sys

import requests
from flask import Flask, Response, render_template, request, stream_with_context

from data.funders import FUNDERS
from data.stages import STAGES

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:latest"


def build_prompt(funder, selections):
    lines = [
        "You are a critical AI ethics analyst. A user has designed a speculative large language model with these specifications:",
        "",
        f"FUNDER: {funder['name']} — {funder['brief']}",
        "",
    ]
    for i, sel in enumerate(selections, 1):
        stage_name = sel.get("stageName", f"Stage {i}")
        label = sel.get("label", "Unknown")
        description = sel.get("description", "")
        lines.append(f"STAGE {i} — {stage_name}: {label} — {description}")

    lines += [
        "",
        "Write a 150-word critical summary of this model. Include:",
        "1. What this model would be good at",
        "2. Who it serves and who it might harm",
        "3. The key ethical tensions and biases baked into its design",
        "4. One sharp question the designers should be asking themselves",
        "",
        "Be specific, direct, and critical. Don't be preachy — be analytical.",
        "Reference the specific choices made. No bullet points — write in prose.",
    ]
    return "\n".join(lines)


@app.route("/")
def index():
    funders_json = json.dumps(FUNDERS)
    stages_json = json.dumps(STAGES)
    return render_template("index.html", funders_json=funders_json, stages_json=stages_json)


@app.route("/api/generate", methods=["POST"])
def generate():
    payload = request.get_json()
    funder = payload.get("funder", {})
    selections = payload.get("selections", [])

    prompt = build_prompt(funder, selections)

    ollama_payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
    }

    def stream_ollama():
        try:
            with requests.post(
                OLLAMA_URL,
                json=ollama_payload,
                stream=True,
                timeout=120,
            ) as resp:
                if resp.status_code != 200:
                    yield f"ERROR: Ollama returned status {resp.status_code}"
                    return
                for line in resp.iter_lines():
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
                "\n\n[OLLAMA NOT RUNNING]\n\n"
                "Could not connect to Ollama at localhost:11434.\n"
                "Please start Ollama with: ollama serve\n"
                "Then ensure the model is available: ollama pull llama3.2:latest"
            )
        except requests.exceptions.Timeout:
            yield "\n\n[TIMEOUT] Ollama took too long to respond. Try a smaller model."

    return Response(
        stream_with_context(stream_ollama()),
        mimetype="text/plain",
        headers={"X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    port = 5001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    print(f"Starting Build Your Own LLM at http://localhost:{port}")
    app.run(debug=True, port=port)
