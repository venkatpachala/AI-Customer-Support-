import os
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

# Routing / planning: faster, smaller
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "qwen2.5:3b")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "qwen2.5:3b")

# Final answer quality
QA_MODEL = os.getenv("QA_MODEL", "qwen2.5:7b")

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def get_supervisor_llm(temperature: float = 0.0) -> ChatOllama:
    return ChatOllama(
        model=SUPERVISOR_MODEL,
        base_url=OLLAMA_BASE,
        temperature=temperature,
    )


def get_planner_llm(temperature: float = 0.0) -> ChatOllama:
    return ChatOllama(
        model=PLANNER_MODEL,
        base_url=OLLAMA_BASE,
        temperature=temperature,
    )


def get_qa_llm(temperature: float = 0.1):
    model = os.getenv("QA_MODEL", "gpt-4o-mini")

    # safety: never send Ollama model names to OpenAI
    if "qwen" in model.lower() or ":" in model:
        model = "gpt-4o-mini"

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=os.getenv("OPENAI_API_KEY"),
    )

import os
from langchain_openai import ChatOpenAI

def get_chat_llm(temperature: float = 0):
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            temperature=temperature,
        )
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=temperature,
    )