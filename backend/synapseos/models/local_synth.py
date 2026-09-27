"""LocalSynthesizerLLM — the offline, always-available model.

Extractive synthesis: scores sentences from the retrieved CONTEXT by weighted term
overlap with the question, then composes a grounded answer with numbered citations.
Style directives (verbosity, citation density) from the reward model shape the
output. When nothing in the context is relevant it says so honestly instead of
hallucinating — and the interaction is flagged for review by the self-critic.

This keeps the *entire* learning loop (feedback → reward → retrieval bias →
critique → drift) demonstrable with zero API keys. Swap in a real LLM via
SYNAPSE_MODEL_PROVIDER without touching anything else.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from synapseos.models.base import BaseLLM, GenRequest, GenResult

_WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
        "and", "or", "it", "its", "this", "that", "with", "as", "by", "at", "be",
        "what", "which", "who", "how", "why", "when", "where", "do", "does", "did",
        "can", "could", "should", "would", "you", "your", "me", "my", "i", "we",
        "tell", "about", "give", "explain", "please", "there", "their", "from", "will"}


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class LocalSynthesizerLLM(BaseLLM):
    name = "synapse-local-synth-1"
    provider = "local"

    def generate(self, req: GenRequest) -> GenResult:
        q = req.question or ""
        q_terms = {w for w in words(q) if w not in STOP and len(w) > 2}
        verbosity = float(req.style.get("verbosity", 1.0))
        citation_density = float(req.style.get("citation_density", 1.0))
        max_sents = max(1, round(3 * verbosity))

        # idf over context sentences
        sents: list[tuple[float, int, str]] = []  # (score, ctx_idx, sentence)
        ctx_terms: list[set[str]] = []
        for ci, c in enumerate(req.context):
            text = (c.get("text") or "").strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", text):
                s = s.strip()
                if len(s) < 25:
                    continue
                st = set(w for w in words(s) if w not in STOP)
                ctx_terms.append(st)
                overlap = len(st & q_terms)
                score = overlap / (1 + 0.05 * len(st))
                if overlap > 0:
                    sents.append((score, ci, s))
        idf = Counter()
        for st in ctx_terms:
            idf.update(st)
        n_docs = max(len(ctx_terms), 1)
        # weighted scoring with term rarity
        weighted: list[tuple[float, int, str]] = []
        for (score, ci, s) in sents:
            st = set(w for w in words(s) if w not in STOP)
            w_sum = sum(math.log(1 + n_docs / (1 + idf[t])) for t in (st & q_terms))
            weighted.append((score + 0.35 * w_sum, ci, s))
        weighted.sort(key=lambda x: -x[0])

        cited: list[str] = []
        used_ctx: set[int] = set()
        top = weighted[:max_sents]
        if q_terms and top and top[0][0] > 0.3:
            for score, ci, s in top:
                marker = f" [{ci + 1}]" if citation_density >= 0.5 else ""
                cited.append(f"{s.rstrip('.!?')}{marker}.".replace("..", "."))
                used_ctx.add(ci)
            intro = "Based on the knowledge base"
            if req.facts:
                intro += " and approved learned facts"
            answer = f"{intro}: " + " ".join(cited)
            if req.memories:
                mem = req.memories[0]
                answer += f" (Recalled from memory: {mem['text']})"
        elif req.facts:
            answer = "From approved learned facts: " + "; ".join(req.facts[:3]) + "."
            used_ctx = set()
        elif req.memories:
            answer = ("I don't have grounded knowledge-base content for this yet, but I recall: "
                      + " ".join(m["text"] for m in req.memories[:2]))
        else:
            answer = ("I don't have enough grounded information in my knowledge base to answer "
                      f"\"{q.strip()[:120]}\" confidently. This response is being flagged for review — "
                      "an admin can ingest documents on the Knowledge page or approve a learned fact, "
                      "and I'll be able to answer this next time.")
        return GenResult(text=answer, model=self.name, provider=self.provider,
                         usage={"sentences_used": len(cited), "contexts_used": len(used_ctx)})
