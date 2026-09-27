# SynapseOS

**A self-learning AI system** — a continuous learning loop wrapped around retrieval, memory and
generation, with human-in-the-loop safety and a full admin dashboard. Every interaction makes the
next answer better, *without retraining*.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            SYNAPSEOS                                    │
│                                                                          │
│   user ──► multi-modal input (text · image · voice)                      │
│              │  unified embedding pipeline                               │
│              ▼                                                            │
│   ┌─────────────────────┐   ┌──────────────────────┐                     │
│   │  ADAPTIVE RETRIEVAL │   │  REWARD MODEL         │◄── feedback         │
│   │  docs · facts ·      │   │  thumbs/ratings/      │   (👍👎 ★ ✎)      │
│   │  memories ·          │   │  corrections → [-1,1] │                    │
│   │  high-reward         │   │  per-topic EMAs,      │                    │
│   │  exemplars           │   │  policy params        │                    │
│   └─────────┬───────────┘   └──────────┬────────────┘                    │
│             ▼                          │ style bias                      │
│   ┌─────────────────────┐   ┌──────────▼────────────┐                    │
│   │  PERSONALIZATION    │──►│  GENERATION           │                    │
│   │  per-user profiles  │   │  (local synth /       │                    │
│   └─────────────────────┘   │   OpenAI / Anthropic /│                    │
│                             │   Ollama …)           │                    │
│                             └──────────┬────────────┘                    │
│                              self-eval │ second pass                     │
│                             ┌──────────▼────────────┐                    │
│                             │  EXPLAINABILITY        │──► confidence,    │
│                             │  sources · trace       │    sources, trace │
│                             └──────────┬────────────┘                    │
│             low confidence ────────────┼────────────► REVIEW QUEUE       │
│                                         │            (human-in-loop)     │
│   DRIFT MONITOR (PSI · reward · volume) │                                 │
│   VERSIONED KB  (approve · rollback)    │                                 │
└─────────────────────────────────────────┴────────────────────────────────┘
```

## Feature checklist

**Core learning engine**

| Feature | Implementation |
|---|---|
| Continuous learning loop | feedback → normalized reward → retrieval bias + generation-policy updates; no retraining |
| Memory layer | short-term session memory (Redis or in-process TTL cache) + persistent long-term memory (embedded in the vector store, user-scoped or global) |
| Feedback ingestion pipeline | every interaction, output, correction and timestamp persisted in a structured ledger (`interactions`, `feedback` tables) ready for fine-tuning export or RAG updates |
| Adaptive retrieval (RAG) | growing vector DB (embedded SQLite+numpy store, or Qdrant) over documents + learned facts + memories + exemplars |
| Reinforcement signal | reward model: thumbs/ratings/corrections → [-1,+1]; per-topic EMAs; high-reward answers retrieved as exemplars; verbosity/citation-density policy learned from feedback text |

**Additional features**

| Feature | Implementation |
|---|---|
| Multi-modal input | text, image (PIL feature extraction + derived captions), voice (transcript or spectral fingerprint) — one unified embedding pipeline |
| Self-evaluation | second-pass critic scores grounding, retrieval confidence, citations, repetition → confidence; low-confidence answers logged for human review |
| Drift detection | PSI on query-embedding distribution, reward-EMA degradation, volume z-score anomaly — events + dashboard alerts |
| Personalization | per-user learned profiles: topic affinities, verbosity preference, liked/disliked topics, correction history |
| Explainability | every answer ships with sources (type, ref, snippet, score), confidence score and a step-by-step reasoning trace |
| Admin dashboard | Next.js: learning curves, feedback stats, review queue, KB versions, drift alerts, user profiles |
| Human-in-the-loop | learned facts are `pending` until an admin approves; approve/reject/rollback from dashboard or API |
| API-first | REST `/api/v1/*` (OpenAPI docs at `/docs`), everything the dashboard does is an API call |
| Versioned knowledge base | immutable KB snapshots on every change; one-click rollback of bad learned updates |
| Security-audit mode | `synapseos audit` — pentest battery against a running instance (Parrot OS / Kali friendly) |

## Quickstart (no API keys, no external services)

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e . --no-deps        # installs the `synapseos` CLI
.venv/bin/python -m synapseos.cli serve     # API on :8000, docs on :8000/docs

# another terminal — seed demo data (docs, 3 weeks of interactions + feedback)
cd backend && .venv/bin/python -m synapseos.cli seed --reset

# dashboard
cd frontend
npm install
npm run dev                                 # dashboard on :3000
```

The default model is the built-in **`synapse-local-synth-1`** — an offline extractive synthesizer
that grounds every answer in retrieved context with citations. It makes the whole learning loop
runnable with zero dependencies. Point it at a real LLM whenever you want (below).

## Using a real model layer

```bash
# OpenAI
export SYNAPSE_MODEL_PROVIDER=openai
export SYNAPSE_MODEL_NAME=gpt-4o-mini
export SYNAPSE_LLM_API_KEY=sk-...

# Anthropic
export SYNAPSE_MODEL_PROVIDER=anthropic
export SYNAPSE_MODEL_NAME=claude-3-5-haiku-latest
export SYNAPSE_LLM_API_KEY=sk-ant-...

# Ollama / vLLM / LM Studio / OpenRouter (any OpenAI-compatible endpoint)
export SYNAPSE_MODEL_PROVIDER=openai_compatible
export SYNAPSE_LLM_BASE_URL=http://localhost:11434/v1
export SYNAPSE_MODEL_NAME=llama3.1

# semantic embeddings (optional; falls back to the offline hashing embedder)
export SYNAPSE_EMBED_PROVIDER=openai
```

If a remote provider fails, the engine automatically falls back to the local synthesizer and marks
the response degraded — the learning loop never stops.

## Docker

```bash
docker compose up --build            # lite: backend + dashboard (SQLite, embedded vectors)

# full stack: + PostgreSQL + Redis + Qdrant
SYNAPSE_DB_URL=postgresql+psycopg2://synapse:synapse@postgres:5432/synapseos \
SYNAPSE_REDIS_URL=redis://redis:6379/0 \
SYNAPSE_VECTOR_BACKEND=qdrant \
docker compose --profile full up --build
```

## API (v1)

Interactive docs: `http://localhost:8000/docs`

| Method & path | Purpose |
|---|---|
| `POST /api/v1/chat` | inference: text + image/audio attachments (base64) |
| `POST /api/v1/chat/upload` | inference with multipart file uploads |
| `POST /api/v1/chat/feedback` | thumbs up/down, 1–5 rating, correction, free text |
| `GET  /api/v1/chat/history` | session history (short-term memory) |
| `POST /api/v1/documents` | ingest text into the RAG corpus |
| `POST /api/v1/documents/upload` | ingest files (txt/md, images, audio) |
| `GET/DELETE /api/v1/documents[/{id}]` | list / deactivate (versioned) |
| `GET/POST /api/v1/kb/facts` | list / propose learned facts |
| `POST /api/v1/kb/facts/{id}/approve\|reject` | human-in-the-loop decisions (admin) |
| `GET  /api/v1/kb/versions` | KB version history |
| `POST /api/v1/kb/versions/{id}/rollback` | rollback of bad learned updates (admin) |
| `GET/POST /api/v1/users[...]` | user profiles, history, memories |
| `GET  /api/v1/admin/overview` | dashboard aggregate |
| `GET  /api/v1/admin/metrics/learning-curve` | daily reward/confidence/flags |
| `GET  /api/v1/admin/metrics/feedback` | feedback statistics |
| `GET  /api/v1/admin/metrics/topics` | per-topic reward EMAs |
| `GET  /api/v1/admin/interactions` | full interaction ledger with explanations |
| `GET/POST /api/v1/admin/drift/...` | drift events + on-demand checks |
| `GET/POST /api/v1/admin/review[...]` | human-review queue + resolve |
| `GET  /api/v1/health`, `/api/v1/meta/config` | health, sanitized config |

Auth: set `SYNAPSE_API_KEYS` (comma list) to require `X-API-Key` on all endpoints and
`SYNAPSE_ADMIN_KEY` for admin operations. Unset = dev mode (open, and the security audit will
tell you so).

## CLI

```bash
synapseos serve                          # run the API
synapseos chat "How does drift detection work?" --user alice
synapseos chat "analyze this" --image diagram.png
synapseos feedback 42 --kind thumb --thumb up
synapseos feedback 42 --kind correction --text "the threshold is 0.45"
synapseos ingest docs/*.md               # bulk ingest
synapseos facts list/approve/reject/propose
synapseos kb versions / rollback --version 3 / resync
synapseos stats                          # system summary
synapseos users [alice]                  # profiles + memories
synapseos audit                          # security audit of a running instance
synapseos seed [--reset]                 # demo data
```

### Security-audit mode

Built for pentest workflows on Parrot OS / Kali — probes a running instance and prints a
severity-tagged report (`audit-report.json` is written too; exit code 1 on high findings):

```
$ synapseos audit
 [HIGH    ] [FAIL] auth-mode     — API authentication is DISABLED (dev mode)
 [HIGH    ] [FAIL] admin-access  — admin endpoint open — no admin key configured
 [LOW     ] [INFO] cors          — CORS allows any origin (*)
 [INFO    ] [PASS] payload-limit — oversized payload rejected (status 413)
 [INFO    ] [PASS] injection     — no 5xx on injection payloads
 [INFO    ] [PASS] headers       — security headers present
 [INFO    ] [PASS] rate-limit    — rate limiter engaged after 233 requests
 ...
```

## Configuration

All settings are environment variables (see [.env.example](.env.example)): storage (SQLite /
Postgres), vector backend (lite / Qdrant), Redis, model provider, embeddings, API keys, CORS,
rate limits, body size, docs on/off, review thresholds, drift thresholds.

## Repository layout

```
backend/
  synapseos/
    core/        config, rate limiter
    db/          SQLAlchemy models (interactions, feedback, facts, versions, drift…)
    embeddings/  text embedder, image/audio features, unified multi-modal pipeline
    vectors/     embedded SQLite+numpy vector store (+ Qdrant adapter)
    memory/      short-term session cache, long-term vector memory
    models/      LLM layer: local synthesizer, OpenAI/Anthropic/Ollama providers
    rag/         adaptive retriever (docs + facts + memories + exemplars)
    learning/    reward model, personalization, self-eval critic, drift monitor
    kb/          versioned knowledge base + rollback
    security/    audit battery
    api/         FastAPI routers (chat, documents, kb, users, admin, meta)
    engine.py    the learning-loop orchestrator
    cli.py       the synapseos CLI
frontend/        Next.js dashboard (chat, review, knowledge, metrics, drift, users)
docs/            architecture deep-dive
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full data-flow walkthrough.

## License

MIT — see [LICENSE](LICENSE).
