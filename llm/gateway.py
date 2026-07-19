from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
import os

class LLMGateway:
    def __init__(self):
        self.primary = "ollama"  # Change to "openai" when needed
        llm = ChatOllama(
    model="qwen2.5:7b",
    base_url="http://127.0.0.1:11434",   # Use 127.0.0.1 instead of localhost
    temperature=0.6
)
        self.openai = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)

    def invoke(self, prompt):
        if self.primary == "ollama":
            try:
                print("Using Ollama (qwen2.5:7b)")
                return self.ollama.invoke(prompt)
            except Exception as e:
                print(f"Ollama failed: {e}")
                print("Falling back to OpenAI GPT-4o-mini")
                return self.openai.invoke(prompt)
        else:
            print("Using OpenAI GPT-4o-mini")
            return self.openai.invoke(prompt)

# Global instance
llm_gateway = LLMGateway()