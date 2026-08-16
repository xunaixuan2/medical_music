from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.culture_qa import answer_culture_question


class CultureGraphState(TypedDict, total=False):
    course_id: str
    message: str
    tutor_turn: dict[str, Any]
    sources: list[dict[str, Any]]


def build_culture_graph():
    """文化导师子图：本地知识检索始终可用，配置 API Key 时增加 LLM 表达。"""

    def tutor(state: CultureGraphState) -> dict[str, Any]:
        result = answer_culture_question((state.get("message") or "").strip())
        return {
            "tutor_turn": {
                "answer": result["answer"],
                "concept_updates": result["concept_updates"],
                "misconception_tags": result["misconception_tags"],
                "retrieved_cards": result["retrieved_cards"],
                "mode": result["mode"],
            },
            "sources": result["sources"],
        }

    graph = StateGraph(CultureGraphState)
    graph.add_node("tutor", tutor)
    graph.add_edge(START, "tutor")
    graph.add_edge("tutor", END)
    return graph.compile()
