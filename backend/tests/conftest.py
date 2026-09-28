"""Shared test fixtures: isolated env + fresh settings per test."""
from __future__ import annotations

import os

import pytest


@pytest.fixture()
def isolated_env(monkeypatch, tmp_path):
    """Isolated data dir + clean SYNAPSE_* environment, restored after the test."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("SYNAPSE_")}
    for k in list(os.environ):
        if k.startswith("SYNAPSE_"):
            del os.environ[k]
    os.environ["SYNAPSE_DATA_DIR"] = str(tmp_path)
    os.environ["SYNAPSE_DB_URL"] = f"sqlite:///{tmp_path}/test.db"

    from synapseos.core import config

    monkeypatch.setattr(config, "_settings", None)
    yield os.environ
    for k in list(os.environ):
        if k.startswith("SYNAPSE_"):
            del os.environ[k]
    os.environ.update(saved)
    monkeypatch.setattr(config, "_settings", None)
