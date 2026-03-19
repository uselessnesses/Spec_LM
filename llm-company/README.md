# Build Your Speculative AI Company

An interactive tool for exploring the ethical and practical consequences of AI design decisions. You step through 7 choices to design a fictional AI company — its purpose, funding, data, and infrastructure — and Ollama generates a speculative story about where it ends up: who it helps, who it harms, and how it probably fails.

The output appears as a thermal printer receipt.

---

## Requirements

- Python 3.8+
- [Ollama](https://ollama.com) running locally
- `llama3.2:3b` model pulled (or change `GENERATION_MODEL` in `app.py`)

---

## Setup

```bash
cd llm-company
pip install flask requests

# Pull the model (first time only)
ollama pull llama3.2:3b

# Start Ollama if it isn't running
ollama serve

# Run the app
python app.py
```

Open **http://localhost:5002** in your browser.

---

## The 7 Stages

| # | Stage | Control | LLM? |
|---|-------|---------|------|
| 1 | **Company Function** — what does it do? | Slider (7 positions, unlabelled) | Live — generates on every move |
| 2 | **Company Name** — what is it called? | Slider (7 positions, unlabelled) | Live — generates on every move |
| 3 | **Business Model** — how is it funded? | Rotary knob (4 options) | Batched on stage load |
| 4 | **Data Type** — what does it learn from? | Rotary knob (4 options) | Batched on stage load |
| 5 | **Data Acquisition** — how was data obtained? | Rotary knob (4 options) | Batched on stage load |
| 6 | **Model Size** — how large is the model? | Slider (5 labelled positions: 1B–32B) | Static descriptions |
| 7 | **Model Hosting** — where does it run? | Rotary knob (4 options) | Static descriptions |

**Stage 1 (Company Function):** Moving the slider left produces more ethical, socially beneficial company concepts. Moving right produces more commercially aggressive or ethically questionable ones. This is not labelled anywhere in the UI — you discover the pattern by exploring.

**Stages 3–5:** When you arrive at a knob stage, the app makes one Ollama call to generate contextual descriptions for all 4 options at once, specific to your company. Turning the knob shows cached results instantly with no further LLM calls.

You can press **[ GENERATE ]** at any time to skip ahead with whatever choices are currently set.

---

## The Receipt

After generation, the output appears as a thermal printer receipt containing:

- Your company specs (name, function, funding, data, model)
- The generated mission statement
- A 3–4 sentence speculative narrative of the company's arc
- Two impact dials: **Societal Impact** and **Environmental Impact** (scored 1–10)
- A one-sentence **Risk Factor** note on how it most likely fails or causes harm

---

## Changing the Model

Open `app.py` and edit the top:

```python
GENERATION_MODEL = "llama3.2:3b"  # change this
```

A faster model (`llama3.2:1b`) makes Stage 1 and 2 more responsive. A larger model (`llama3.2:latest`, `qwen2.5:7b`) produces better analysis in the final receipt.

---

## Architecture

- `app.py` — Flask backend, 4 streaming API endpoints, serves `index.html`
- `index.html` — Complete single-file frontend: all HTML, CSS, and JS inline
- No build step. No npm. No frameworks.
