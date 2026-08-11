import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
load_dotenv(override=True)

from langchain_openai import ChatOpenAI
from rag.retrieval import AdvancedRAGRetriever
from common.llm import get_qa_llm


ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = Path(__file__).parent / "dataset.json"
REPORT_DIR = ROOT / "evaluation" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_dataset() -> List[Dict[str, str]]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_answer_and_contexts(question: str) -> Dict[str, Any]:
    retriever = AdvancedRAGRetriever()
    docs = retriever.retrieve(question, k=6, final_k=3, use_hybrid=True) or []
    contexts = [d.page_content for d in docs]
    context_text = "\n\n".join(contexts) if contexts else "No policy context found."

    prompt = f"""You are a customer support policy assistant for Zepto.
Answer ONLY using the policy context.
If context is insufficient, say you don't have enough policy information.
Keep the answer concise.

POLICY CONTEXT:
{context_text}

QUESTION:
{question}

ANSWER:"""

    llm = get_qa_llm(temperature=0)
    resp = llm.invoke(prompt)
    answer = resp.content if hasattr(resp, "content") else str(resp)

    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
    }


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


def judge_sample(question: str, answer: str, contexts: List[str]) -> Dict[str, float]:
    """
    Lightweight LLM judge approximating RAGAS metrics.
    Returns scores in [0, 1].
    """
    context_text = "\n\n".join(contexts) if contexts else "NO_CONTEXT"

    prompt = f"""You are an evaluation judge for a policy QA system.
Score the sample on three metrics from 0.0 to 1.0.

Metrics:
1) faithfulness: does the answer stick to the provided context without inventing facts?
2) answer_relevancy: does the answer address the question?
3) context_precision: are the retrieved contexts relevant to the question?

Return ONLY valid JSON:
{{
  "faithfulness": 0.0,
  "answer_relevancy": 0.0,
  "context_precision": 0.0,
  "notes": "short reason"
}}

QUESTION:
{question}

CONTEXT:
{context_text}

ANSWER:
{answer}
"""

    judge = ChatOpenAI(
        model=os.getenv("QA_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    raw = judge.invoke(prompt)
    content = raw.content if hasattr(raw, "content") else str(raw)
    data = _extract_json(content)

    def clamp(x, default=0.0):
        try:
            v = float(x)
            return max(0.0, min(1.0, v))
        except Exception:
            return default

    return {
        "faithfulness": clamp(data.get("faithfulness")),
        "answer_relevancy": clamp(data.get("answer_relevancy")),
        "context_precision": clamp(data.get("context_precision")),
        "notes": data.get("notes", ""),
    }


def mean(xs: List[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def main():
    rows = load_dataset()
    samples = []

    print(f"Running RAGAS-lite on {len(rows)} policy questions...")

    for row in rows:
        qid = row.get("id", "unknown")
        question = row["question"]
        print(f"- {qid}")

        try:
            item = build_answer_and_contexts(question)
            scores = judge_sample(item["question"], item["answer"], item["contexts"])
            item.update(scores)
            item["id"] = qid
            samples.append(item)
            print(
                f"  f={scores['faithfulness']:.2f} "
                f"r={scores['answer_relevancy']:.2f} "
                f"p={scores['context_precision']:.2f}"
            )
        except Exception as e:
            print(f"  failed: {e}")
            samples.append({
                "id": qid,
                "question": question,
                "answer": "",
                "contexts": [],
                "faithfulness": 0.0,
                "answer_relevancy": 0.0,
                "context_precision": 0.0,
                "notes": f"error: {e}",
            })

    summary = {
        "faithfulness": mean([s["faithfulness"] for s in samples]),
        "answer_relevancy": mean([s["answer_relevancy"] for s in samples]),
        "context_precision": mean([s["context_precision"] for s in samples]),
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORT_DIR / f"ragas_report_{stamp}.json"
    payload = {
        "created_at": stamp,
        "engine": "ragas_lite_llm_judge",
        "n_questions": len(samples),
        "scores": summary,
        "samples": samples,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n===== RAGAS-LITE SUMMARY =====")
    print(json.dumps(summary, indent=2))
    print(f"Report saved to: {out}")


if __name__ == "__main__":
    main()