# SynapseOS — Architecture Deep-Dive

## 1. The learning loop (no retraining)

```
        ┌────────────────────────── feedback ──────────────────────────┐
        │                                                               │
        ▼                                                               │
   [ generation ]  ◄── style bias ◄── [ reward model ]  ◄── normalize(👍👎 ★ ✎)
        │                                    │
        ├── answer + explanation              ├── interaction.reward
        ├── self-eval critique                ├── topic/global reward EMAs
        └── ledger row                        ├── policy (verbosity, citations)
                                              ├── user profile update
                                              └── exemplar vector meta update
```

Improvement happens through three online mechanisms:

1. **Retrieval bias** — every past interaction's *query* is embedded into the
   `interactions` collection with its (initially zero) reward. Feedback updates that
   reward. At retrieval time, high-reward past answers to *similar* questions are
   fetched as **exemplars** and injected into the generation prompt ("imitate these").
   A bad answer therefore gets buried; a corrected answer surfaces for similar queries.
2. **Policy parameters** — the reward model maintains EMAs and knobs
   (`verbosity`, `citation_density`) adjusted from feedback text heuristics
   ("too long", "more detail") and from thumbs-down patterns. Topic EMAs below zero
   automatically make answers more cautious/tight for that topic.
3. **Knowledge** — corrections write long-term memories (immediately effective for
   that user) and propose learned facts (pending admin approval; approved facts join
   the retrieval corpus and are versioned).

## 2. Memory layers

- **Short-term**: session transcripts in Redis (or in-process TTL cache),
  keyed `s{user_id}:{session_id}`, last 8 turns injected into the prompt.
- **Long-term**: `memories` table + `memory` vector collection. Entries are
  user-scoped (corrections, stated preferences) or global (approved knowledge).
  `recall()` prefers user memories, falls back to global ones.
  Explicit "remember that …" instructions write memory directly.

## 3. Multi-modal unified embedding pipeline

`UnifiedEmbedder` maps any input to an `EmbeddedItem`:

- **text** → hashing embedder (word unigrams + char trigrams → signed 384-dim
  vector, sublinear TF, L2-normalized) or OpenAI embeddings when configured.
- **image** → derived caption (dimensions, dominant colors, brightness, optional
  user caption) embedded in text space (cross-modal retrieval) **plus** a native
  24×16 grayscale pixel vector stored in the `media` collection (search-by-image).
- **audio** → transcript (if provided, e.g. by client-side speech-to-text or
  Whisper) as primary text; WAV inputs get a 32-band log-energy spectral
  fingerprint as the native vector.

All modality descriptors live in the same vector space via their text
representation, so one retriever serves every input type.

## 4. Self-evaluation (second pass)

`SelfCritic` scores the draft answer *before* it is returned:

- **grounding** — fraction of answer content words covered by retrieved sources
- **retrieval confidence** — mean and top retrieval scores
- **citation presence**, **length sanity**, **repetition penalty**, **question coverage**
- hedge phrases ("I don't have…") cap the confidence

Weighted sum → `confidence ∈ [0,1]`; below `0.45` the interaction is flagged and a
review-queue item is created. The critique is stored with the interaction and shown
in the chat UI ("why?" panel) and review dashboard.

## 5. Drift & anomaly detection

- **Input drift (PSI)**: query embeddings land in the `queries` collection.
  The monitor projects baseline vs. recent windows onto 4 fixed random directions,
  computes the Population Stability Index per direction, and fires when mean PSI
  crosses `0.25` — i.e. new topics/users/data arriving that the system wasn't
  answering before.
- **Reward drift**: current global reward EMA vs. 7-day baseline; drop > `0.15`
  fires a warning, > 2× that is critical.
- **Volume anomaly**: hourly interaction counts (48h window), z-score ≥ 3.

Events dedupe within 6 hours; critical ones also enter the review queue. Checks run
on a 60s background timer and on demand (`POST /admin/drift/recompute`).

## 6. Versioned knowledge base + rollback

Every mutation (document add/deactivate, fact approve/reject, rollback) appends an
immutable `kb_versions` snapshot `{fact_ids, doc_ids}`. Rollback to version *v*
restores exactly that active set — facts are re-activated/retired, document vectors
re-indexed or removed — then snapshots the rollback itself. `POST /kb/resync`
rebuilds vectors from relational truth at any time.

## 7. Storage

| Store | Default | Production |
|---|---|---|
| Structured ledger (interactions, feedback, facts, versions, drift, profiles) | SQLite (`backend/data/synapseos.db`) | PostgreSQL (`SYNAPSE_DB_URL`) |
| Vectors | embedded LiteVectorStore (SQLite + numpy, exact cosine) | Qdrant (`SYNAPSE_VECTOR_BACKEND=qdrant`) |
| Session cache | in-process TTL dict | Redis (`SYNAPSE_REDIS_URL`) |

## 8. Security posture

- API-key auth (`X-API-Key`/`Bearer`) on all inference endpoints when configured;
  separate admin key gates approve/reject/rollback/metrics.
- Token-bucket rate limiting per key/IP; body-size limit (default 8 MB);
  security headers on every response (including 413/429).
- Uploads are parsed in memory (PIL) — no filesystem writes of user files.
- Global exception handler never leaks stack traces unless docs mode is on.
- `synapseos audit` continuously verifies all of the above against a live instance.

## 9. Fine-tuning export path

The structured ledger (`interactions` + `feedback`, with rewards normalized to
[-1,1]) is exactly a preference/DPO-style dataset:

```sql
SELECT i.id, i.input_text, i.output_text, f.kind, f.value AS reward, f.correction_text
FROM interactions i JOIN feedback f ON f.interaction_id = i.id
WHERE i.reward IS NOT NULL;
```

High-reward pairs export as SFT examples; (bad answer, correction) pairs export as
DPO preference pairs — a natural future upgrade path from the online loop to
periodic LoRA/PEFT fine-tunes while the RAG + feedback wrapper keeps learning
between trainings.
