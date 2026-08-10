import json
from pathlib import Path
from typing import List, Optional
from interactions.models import InteractionRecord

DATA_DIR = Path("interactions/data")
DATA_FILE = DATA_DIR / "interactions.jsonl"


class InteractionStore:
    def __init__(self, path: Path = DATA_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, record: InteractionRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.json() + "\n")

    def list_recent(self, limit: int = 50) -> List[InteractionRecord]:
        rows: List[InteractionRecord] = []
        if not self.path.exists():
            return rows

        with self.path.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(InteractionRecord(**json.loads(line)))
            except Exception:
                continue
        return rows

    def list_by_conversation(self, conversation_id: str) -> List[InteractionRecord]:
        return [r for r in self.list_recent(limit=1000) if r.conversation_id == conversation_id]