"""Remote LLM providers (OpenAI / Anthropic / OpenAI-compatible)."""
from __future__ import annotations

import httpx

from synapseos.core.config import Settings
from synapseos.models.base import BaseLLM, GenRequest, GenResult
from synapseos.models.local_synth import LocalSynthesizerLLM


class _RemoteLLM(BaseLLM):
    provider = "remote"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._fallback = LocalSynthesizerLLM()

    def _call(self, req: GenRequest) -> str:
        raise NotImplementedError

    def generate(self, req: GenRequest) -> GenResult:
        try:
            text = self._call(req)
            if not text.strip():
                raise RuntimeError("empty completion")
            return GenResult(text=text, model=self.name, provider=self.provider)
        except Exception as e:  # noqa: BLE001 — never break the loop on provider failure
            res = self._fallback.generate(req)
            res.degraded = True
            res.model = f"{self.name}→fallback"
            res.usage["fallback_reason"] = str(e)[:300]
            return res


class OpenAICompatibleLLM(_RemoteLLM):
    """Works with OpenAI, Ollama (/v1), vLLM, LM Studio, OpenRouter, etc."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.name = settings.model_name or "gpt-4o-mini"
        base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self._url = f"{base}/chat/completions"
        self._headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}

    def _call(self, req: GenRequest) -> str:
        r = httpx.post(self._url, headers=self._headers, timeout=self.settings.llm_timeout, json={
            "model": self.name,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "messages": [
                {"role": "system", "content": req.system + "\nStyle directives: " +
                 ("; ".join(f"{k}={v}" for k, v in req.style.items()) or "default")},
                {"role": "user", "content": req.render_prompt()},
            ],
        })
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


class AnthropicLLM(_RemoteLLM):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.name = settings.model_name or "claude-3-5-haiku-latest"
        self._key = settings.llm_api_key

    def _call(self, req: GenRequest) -> str:
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": self._key, "anthropic-version": "2023-06-01"},
                       timeout=self.settings.llm_timeout, json={
                           "model": self.name,
                           "max_tokens": req.max_tokens,
                           "temperature": req.temperature,
                           "system": req.system,
                           "messages": [{"role": "user", "content": req.render_prompt()}],
                       })
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))


def build_llm(settings: Settings) -> BaseLLM:
    if settings.model_provider == "openai":
        return OpenAICompatibleLLM(settings)
    if settings.model_provider == "anthropic":
        return AnthropicLLM(settings)
    if settings.model_provider == "openai_compatible":
        if not settings.model_name:
            settings.model_name = "llama3.1"
        return OpenAICompatibleLLM(settings)
    return LocalSynthesizerLLM()
