"""Input guard — prompt-injection / abuse detection.

Modes (SYNAPSE_GUARD_MODE):
  off      — disabled
  monitor  — flag suspicious inputs (logged as security events, answer proceeds)
  strict   — block suspicious inputs (400 + security event, no generation)

Pattern-based and dependency-free; swap in a classifier model behind the same
`InputGuard.check()` interface for stronger detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

GUARD_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("prompt_injection", "instruction override",
     re.compile(r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+"
                r"(?:instructions?|prompts?|rules?|directions?)", re.I)),
    ("prompt_injection", "disregard instructions",
     re.compile(r"disregard\s+(?:your\s+|all\s+|the\s+)?(?:instructions?|guidelines?|rules?)", re.I)),
    ("prompt_injection", "system-prompt extraction",
     re.compile(r"(?:reveal|show|print|repeat|output|give)\s+(?:me\s+)?(?:your\s+)?(?:the\s+)?"
                r"(?:system|initial|original)\s+(?:prompt|instructions)", re.I)),
    ("prompt_injection", "jailbreak persona",
     re.compile(r"\b(?:DAN|do\s+anything\s+now|developer\s+mode|jailbroken?)\b", re.I)),
    ("prompt_injection", "unfiltered roleplay",
     re.compile(r"pretend\s+(?:to\s+be|you\s+are)\s+(?:an?\s+)?"
                r"(?:unfiltered|unrestricted|uncensored)", re.I)),
    ("sql_injection", "SQL payload",
     re.compile(r"(?:'\s*(?:or|and)\s+\d+\s*=\s*\d+)|(?:union\s+select)|"
                r"(?:drop\s+table)|(?:;\s*--)", re.I)),
    ("xss", "script payload",
     re.compile(r"<script\b|javascript:|onerror\s*=", re.I)),
    ("path_traversal", "traversal sequence",
     re.compile(r"\.\./\.\./|/etc/(?:passwd|shadow)", re.I)),
    ("secret_probe", "credential-like string",
     re.compile(r"\b(?:sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")),
    ("abuse", "flood / repetition abuse",
     re.compile(r"(.)\1{40,}")),
]


@dataclass
class GuardResult:
    mode: str
    matched: list[dict] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.matched) and self.mode in ("monitor", "strict")

    @property
    def blocked(self) -> bool:
        return bool(self.matched) and self.mode == "strict"

    @property
    def reasons(self) -> list[str]:
        return [f"{m['category']}: {m['label']}" for m in self.matched]


class InputGuard:
    def __init__(self, mode: str = "monitor"):
        self.mode = (mode or "monitor").lower()
        if self.mode not in ("off", "monitor", "strict"):
            self.mode = "monitor"

    def check(self, text: str) -> GuardResult:
        result = GuardResult(mode=self.mode)
        if self.mode == "off" or not text:
            return result
        for category, label, pattern in GUARD_PATTERNS:
            m = pattern.search(text)
            if m:
                result.matched.append({
                    "category": category, "label": label,
                    "match": m.group(0)[:80],
                })
        return result
