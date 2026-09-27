# ── SynapseOS backend ───────────────────────────────────────────────
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml .
COPY synapseos ./synapseos
RUN pip install -e . --no-deps

# unprivileged runtime user
RUN useradd -m synapse && chown -R synapse:synapse /app
USER synapse

ENV SYNAPSE_DATA_DIR=/app/data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "synapseos.main:app", "--host", "0.0.0.0", "--port", "8000"]
