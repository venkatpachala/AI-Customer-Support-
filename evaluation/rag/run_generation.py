"""Score citation and faithfulness on Recall@5 hits. Runs only after retrieval validates.

The QA prompt is the production qa_node. Tool results stay empty.
RAG_JUDGE=1 is unused: the resume number is the deterministic check.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage

from evaluation.rag.metrics import (
    abstains,
    cites_clause,
    claims_refund_processed,
    facts_supported,
    mean,
)
from evaluation.rag.validate import LATEST, failures_of, load_report

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "rag" / "dataset.json"


def _reply_text(result: Dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    message = messages[-1]
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "")


def _gold_chunk_text(gold_clause: str, docs: List[Any]) -> str:
    from evaluation.rag.metrics import first_gold_rank

    chunks = []
    for doc in docs:
        if isinstance(doc, dict):
            metadata = doc.get("metadata") or {}
            content = doc.get("page_content") or ""
        else:
            metadata = doc.metadata or {}
            content = doc.page_content or ""
        chunks.append({"clause": metadata.get("clause"), "content": content})
    rank = first_gold_rank(chunks, gold_clause)
    if rank:
        chosen = docs[rank - 1]
        if isinstance(chosen, dict):
            return str(chosen.get("page_content") or "")
        return str(chosen.page_content or "")
    parts = []
    for doc in docs[:5]:
        if isinstance(doc, dict):
            parts.append(str(doc.get("page_content") or ""))
        else:
            parts.append(str(getattr(doc, "page_content", "") or ""))
    return "\n".join(parts)


def _docs_from_query(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    saved = list(query.get("scored_chunks") or [])
    return [
        {
            "page_content": chunk.get("content") or "",
            "metadata": {
                "clause": chunk.get("clause"),
                "source_id": chunk.get("source_id"),
                "tenant_id": chunk.get("tenant_id"),
                "page": chunk.get("page"),
                "chunk_id": chunk.get("chunk_id"),
                "citation": ", ".join(
                    part for part in (
                        "Zepto Terms of Use",
                        f"Page {chunk.get('page')}" if chunk.get("page") not in (None, "") else "",
                        f"Clause {chunk.get('clause')}" if chunk.get("clause") else "",
                    ) if part
                ),
            },
        }
        for chunk in saved
    ]


def _answer(retriever: Any, row: Dict[str, Any], saved_docs: List[Dict[str, Any]] | None = None):
    from agents.qa import qa_node
    from rag.tenant_filter import pinecone_tenant_filter

    if saved_docs:
        prefetched = saved_docs
        citations = [(doc.get("metadata") or {}).get("citation", "") for doc in saved_docs]
        docs = saved_docs
    else:
        retrieved = retriever.retrieve(
            row["question"],
            k=20,
            final_k=10,
            use_hybrid=True,
            metadata_filter=pinecone_tenant_filter(row.get("tenant_id") or "zepto"),
        ) or []
        prefetched = [
            {"page_content": doc.page_content, "metadata": dict(doc.metadata or {})}
            for doc in retrieved
        ]
        citations = [(doc.metadata or {}).get("citation", "") for doc in retrieved]
        docs = prefetched
    result = qa_node({
        "messages": [HumanMessage(content=row["question"])],
        "tenant_id": row.get("tenant_id") or "zepto",
        "request_id": f"rag-{row['id']}",
        "prefetched_docs": prefetched,
        "prefetched_citations": citations,
        "tool_results": {},
        "needs_identity": False,
        "intent": "policy",
        "current_plan": {"intent": "policy", "missing_inputs": []},
    })
    reply = _reply_text(result)
    return reply, docs


def run(report_path: Path | None = None) -> Path:
    import pickle

    from rag.retrieval import AdvancedRAGRetriever

    path = report_path or LATEST
    if not path.is_file():
        raise SystemExit("retrieval report is missing; run evaluation.rag.run_retrieval first")
    report = load_report(path)
    reasons = failures_of(report)
    if reasons:
        print("VALIDATE FAIL")
        for reason in reasons:
            print(f"- {reason}")
        raise SystemExit(1)

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in dataset}
    retriever = AdvancedRAGRetriever()
    with (ROOT / "rag" / "bm25_corpus_zepto.pkl").open("rb") as handle:
        retriever.load_bm25_documents(pickle.load(handle))

    citation_flags: List[float] = []
    faith_flags: List[float] = []
    abstain_flags: List[float] = []
    for query in report["queries"]:
        row = by_id.get(query["id"])
        if row is None or float(query.get("recall@5") or 0) < 1:
            continue
        reply, docs = _answer(retriever, row, _docs_from_query(query))
        gold = str(row.get("gold_clause") or "")
        cited = cites_clause(reply, gold)
        supported = facts_supported(list(row.get("gold_answer_facts") or []), _gold_chunk_text(gold, docs))
        faithful = supported and not claims_refund_processed(reply)
        query["reply"] = reply
        query["citation_hit"] = bool(cited)
        query["faithfulness"] = bool(faithful)
        query["abstained"] = abstains(reply)
        citation_flags.append(1.0 if cited else 0.0)
        faith_flags.append(1.0 if faithful else 0.0)
        abstain_flags.append(0.0 if query["abstained"] else 1.0)

    extra = []
    for row in dataset:
        if row.get("answerable") is not False:
            continue
        reply, _docs = _answer(retriever, row)
        abstained = abstains(reply)
        extra.append({
            "id": row["id"],
            "answerable": False,
            "question": row["question"],
            "reply": reply,
            "abstained": abstained,
        })
        abstain_flags.append(1.0 if abstained else 0.0)
    report["unanswerable_queries"] = extra

    report["citation_hit"] = round(mean(citation_flags), 4) if citation_flags else None
    report["faithfulness"] = round(mean(faith_flags), 4) if faith_flags else None
    report["abstention"] = round(mean(abstain_flags), 4) if abstain_flags else None
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    reasons = failures_of(report)
    if reasons:
        print("VALIDATE FAIL")
        for reason in reasons:
            print(f"- {reason}")
        raise SystemExit(1)
    if path.resolve() != LATEST.resolve():
        shutil.copyfile(path, LATEST)
    print(f"citation_hit={report['citation_hit']} faithfulness={report['faithfulness']} abstention={report['abstention']}")
    return path


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run(target)


if __name__ == "__main__":
    main()
