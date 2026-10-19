"""Local browser regression fixture. Real API/database; explicitly fake model IO.

Never deploy this fixture. Run from the repository with python tests/browser_server.py.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///" + (ROOT / "artifacts" / "browser-fixture.db").as_posix()
os.environ["TOOLS_MODE"] = "mock"
os.environ["APP_ENV"] = "test"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["OPENAI_API_KEY"] = "browser-fixture-not-a-real-key"
os.environ["OPS_SESSION_SECRET"] = "browser-fixture-session-secret-not-for-deployment"
os.environ["LLM_PROVIDER"] = "openai"
for name in ("SUPERVISOR_MODEL", "PLANNER_MODEL", "QA_MODEL"):
    os.environ[name] = "gpt-4o-mini"
os.environ["KNOWLEDGE_EMBEDDINGS"] = "none"
(ROOT / "artifacts").mkdir(exist_ok=True)

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


def fixture_model(self, prompt, **kwargs):
    text = str(prompt)
    if "CLASSIFICATION RULES" in text:
        return AIMessage(content='{"intent":"policy_query","intent_type":"knowledge","risk":"low"}')
    if "POLICY FACTS" in text:
        return AIMessage(content="Returns require clear photographs of damaged items within seven days.")
    return AIMessage(content="Please contact the support team for assistance.")


ChatOpenAI.invoke = fixture_model
from gateway.main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
