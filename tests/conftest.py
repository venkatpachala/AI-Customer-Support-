"""Legacy fixtures explicitly opt into old internal actor headers; production never does.

Tests must not mutate the developer's database or use real provider credentials.
"""
import os
import tempfile
import pytest
from pathlib import Path

_database_dir = tempfile.TemporaryDirectory(prefix="d2c-tests-", ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_database_dir.name) / "tests.db").as_posix()
os.environ["ALLOW_LEGACY_ACTOR_HEADERS"] = "1"
os.environ["TOOLS_MODE"] = "mock"
os.environ["KNOWLEDGE_EMBEDDINGS"] = "none"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ.setdefault("OPS_SESSION_SECRET", "test-session-secret-that-is-at-least-32-characters")
os.environ["LLM_PROVIDER"] = "openai"
os.environ["SUPERVISOR_MODEL"] = "gpt-4o-mini"
os.environ["PLANNER_MODEL"] = "gpt-4o-mini"
os.environ["QA_MODEL"] = "gpt-4o-mini"


@pytest.fixture(autouse=True)
def no_paid_model_calls(monkeypatch):
    def disabled(*args, **kwargs):
        raise RuntimeError("Model calls require an explicit test double")
    monkeypatch.setattr("langchain_openai.ChatOpenAI.invoke", disabled)
    monkeypatch.setattr("langchain_ollama.ChatOllama.invoke", disabled)


def pytest_sessionfinish(session, exitstatus):
    from db.session import engine
    engine.dispose()
