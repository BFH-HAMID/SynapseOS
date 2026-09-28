"""Topic classifier — lightweight keyword bucketing used to segment reward EMAs,
personalization affinities and drift statistics."""
from __future__ import annotations

TOPIC_KEYWORDS: dict[str, set[str]] = {
    "security": {"security", "pentest", "pentesting", "exploit", "vulnerability", "cve",
                 "hack", "hacking", "firewall", "encryption", "payload", "nmap", "kali",
                 "parrot", "osint", "phishing", "malware", "auth", "api key", "threat",
                 "attack", "breach", "hash", "tls", "ssl", "injection", "xss", "csrf"},
    "ai_ml": {"ai", "model", "llm", "embedding", "rag", "retrieval", "vector", "training",
              "fine-tuning", "lora", "peft", "reinforcement", "reward", "neural",
              "transformer", "gpt", "prompt", "memory", "learning", "drift", "dataset"},
    "data": {"database", "sql", "postgres", "redis", "query", "schema", "migration",
             "table", "index", "transaction", "analytics", "metrics", "statistics"},
    "api": {"api", "endpoint", "rest", "grpc", "http", "websocket", "rate limit",
            "middleware", "openapi", "sdk", "webhook", "curl"},
    "deployment": {"docker", "container", "compose", "kubernetes", "k8s", "deploy",
                   "ci", "cd", "devops", "nginx", "scaling", "cloud", "server"},
}


def classify(text: str) -> str:
    t = text.lower()
    best, best_score = "general", 0
    for topic, kws in TOPIC_KEYWORDS.items():
        score = sum(1 for k in kws if k in t)
        if score > best_score:
            best, best_score = topic, score
    return best
