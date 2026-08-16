from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class SessionRepository:
    """学习会话持久化仓库。

    MVP 阶段落地为「内存索引 + 追加写 JSONL 文件」，避免引入数据库依赖，
    先把学习闭环跑通。后续可无缝替换为 PostgreSQL 实现（保持 persist 签名不变即可）。
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "data"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._base_dir / "sessions.jsonl"
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def persist(
        self,
        session: dict[str, Any],
        action: str,
        payload: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        """记录一次学习动作。签名与 learning_graph.persist 节点保持一致。"""
        record: dict[str, Any] = {
            "id": len(self._records) + 1,
            "timestamp": time.time(),
            "action": action,
            "session": session,
            "payload": payload,
            "response": response,
        }
        with self._lock:
            self._records.append(record)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def all(self) -> list[dict[str, Any]]:
        """返回全部已持久化的动作记录（按写入顺序）。"""
        return list(self._records)

    def count(self) -> int:
        return len(self._records)
