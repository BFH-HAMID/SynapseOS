"""Model layer abstraction. Providers:

- local             — LocalSynthesizerLLM: offline extractive answer synthesizer.
                      Grounds every sentence in retrieved context, cites sources,
                      honors style parameters. Zero dependencies, fully deterministic.
- openai            — OpenAI chat completions (SYNAPSE_LLM_API_KEY / OPENAI_API_KEY)
- anthropic         — Anthropic messages API
- openai_compatible — Ollama / vLLM / LM Studio / OpenRouter (SYNAPSE_LLM_BASE_URL)

All providers consume the same structured prompt (question + facts + context +
memories + exemplars + style) and fall back to the local synthesizer on failure,
so the learning loop keeps running even when an upstream API is down.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GenRequest:
    system: str = "You are SynapseOS, a self-learning assistant."
    question: str = ""
    facts: list[str] = field(default_factory=list)          # approved learned facts
    context: list[dict] = field(default_factory=list)        # [{id,title,text,kind,score}]
    memories: list[dict] = field(default_factory=list)       # long-term memory hits
    exemplars: list[dict] = field(default_factory=list)      # high-reward past Q/A
    session_history: list[dict] = field(default_factory=list)
    style: dict = field(default_factory=dict)                # verbosity, citation_density...
    temperature: float = 0.3
    max_tokens: int = 600

    def render_prompt(self) -> str:
        parts: list[str] = []
        parts.append(f"### QUESTION\n{self.question}")
        if self.facts:
            parts.append("### APPROVED FACTS\n" + "\n".join(f"- {f}" for f in self.facts))
        if self.context:
            blocks = [f"[{i+1}] {c.get('title') or c.get('kind','source')} (relevance {c.get('score', 0):.2f})\n{c.get('text','')}"
                      for i, c in enumerate(self.context)]
            parts.append("### CONTEXT\n" + "\n\n".join(blocks))
        if self.memories:
            parts.append("### MEMORIES\n" + "\n".join(f"- ({m['scope']}) {m['text']}" for m in self.memories))
        if self.exemplars:
            parts.append("### PREFERRED PAST ANSWERS (high reward — imitate their style)\n" +
                         "\n---\n".join(f"Q: {e['question']}\nA: {e['answer']}" for e in self.exemplars))
        if self.session_history:
            parts.append("### RECENT CONVERSATION\n" + "\n".join(
                f"{m['role']}: {m['content']}" for m in self.session_history[-8:]))
        style = "; ".join(f"{k}={v}" for k, v in self.style.items()) or "default"
        parts.append(f"### STYLE DIRECTIVES\n{style}")
        return "\n\n".join(parts)


@dataclass
class GenResult:
    text: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    degraded: bool = False   # True if a remote provider failed and local synth answered


class BaseLLM(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, req: GenRequest) -> GenResult: ...
