"""One bounded provider configuration for routing, planning and generation."""
from __future__ import annotations
import os
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


def _client(role: str, temperature: float):
    configured = os.getenv(f"{role}_MODEL", "")
    provider = os.getenv("LLM_PROVIDER", "ollama" if ":" in configured or "qwen" in configured.lower() else "openai").lower()
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    if provider == "ollama":
        return ChatOllama(model=os.getenv(f"{role}_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:3b")),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            temperature=temperature, num_predict=600, client_kwargs={"timeout": timeout})
    if provider != "openai":
        raise ValueError("LLM_PROVIDER must be openai or ollama")
    model = os.getenv(f"{role}_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    from observability.models import ModelMetrics
    if ":" in model or "qwen" in model.lower():
        raise ValueError(f"{role}_MODEL is not an OpenAI model; select LLM_PROVIDER=ollama")
    return ChatOpenAI(model=model, temperature=temperature, timeout=timeout,
                      api_key=os.getenv("OPENAI_API_KEY") or "unconfigured",
                      callbacks=[ModelMetrics(model)], max_retries=1, max_tokens=600)


def get_supervisor_llm(temperature: float = 0.0):
    return _client("SUPERVISOR", temperature)


def get_planner_llm(temperature: float = 0.0):
    return _client("PLANNER", temperature)


def get_qa_llm(temperature: float = 0.1):
    return _client("QA", temperature)


def get_chat_llm(temperature: float = 0.0):
    return _client("QA", temperature)
