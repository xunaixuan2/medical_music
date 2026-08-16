from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class CultureGraphState(TypedDict, total=False):
    course_id: str
    message: str
    tutor_turn: dict[str, Any]
    sources: list[dict[str, Any]]


# 概念知识库（MVP 桩）。后续替换为 RAG：检索 knowledge_chunks + LLM 生成分层解释。
_CONCEPT_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "spring_renewal": {
        "answer": "「天地俱生，万物以荣」讲的是春天阳气生发、万物复苏的景象。这里的“生”“荣”描述的是自然界的生机，属于观察与取象，不涉及好坏判断。",
        "concept_updates": {"spring_renewal": 20},
        "sources": [
            {"title": "黄帝内经·素问·四气调神大论", "authority": "primary", "citation": "天地俱生，万物以荣。"}
        ],
    },
    "yin_yang": {
        "answer": "阴阳是相互依存、不断转化的两类属性，而不是“好与坏”的对立。夜晚属阴，但夜晚带来休息与生长；没有阴，也就没有阳。",
        "concept_updates": {"yin_yang": 20},
        "sources": [
            {"title": "黄帝内经·素问·阴阳应象大论", "authority": "primary", "citation": "阴阳者，天地之道也。"}
        ],
    },
}

# 常见误解规则（MVP 桩）：命中关键词时用苏格拉底式追问引导，而非直接贴标签。
_MISCONCEPTION_RULES: list[tuple[tuple[str, ...], str, str, dict[str, int], list[str]]] = [
    (
        ("阴", "坏"),
        "yin_yang",
        "你似乎把“阴”理解成了“坏”。夜晚通常归为“阴”——夜晚一定是坏的吗？如果没有夜晚，休息和生长会发生吗？所以阴阳更接近相互依存、不断变化的两类属性，而不是好与坏的对立。",
        {"yin_yang": 25},
        ["yin_is_bad"],
    ),
    (
        ("阴", "负面"),
        "yin_yang",
        "把“阴”直接等同于“负面”是一种常见误读。阴阳描述的是相互补充的属性：山的北面为阴、南面为阳，两者共同构成一座山，并无褒贬。你能想到生活里哪些“阴”的属性其实是必要的吗？",
        {"yin_yang": 25},
        ["yin_is_negative"],
    ),
    (
        ("明白",),
        "yin_yang",
        "很好，你能把阴阳理解为相互依存、变化的属性，说明已经跳出了“好坏对立”的框架。可以再想想：一天之中，什么时候阳气最盛、什么时候阴气最盛？",
        {"yin_yang": 10},
        [],
    ),
]


def _reply(message: str) -> tuple[str, dict[str, int], list[str], list[dict[str, Any]]]:
    for keywords, concept, answer, updates, tags in _MISCONCEPTION_RULES:
        if all(k in message for k in keywords):
            sources = _CONCEPT_KNOWLEDGE.get(concept, {}).get("sources", [])
            return answer, updates, tags, sources

    entry = _CONCEPT_KNOWLEDGE["yin_yang"]
    return entry["answer"], entry["concept_updates"], [], entry["sources"]


def build_culture_graph():
    """构建文化导师子图。被 learning_graph 作为参数注入，对外保持 .invoke(...) 接口。"""

    def tutor(state: CultureGraphState) -> dict[str, Any]:
        message = (state.get("message") or "").strip()
        answer, updates, tags, sources = _reply(message)
        return {
            "tutor_turn": {
                "answer": answer,
                "concept_updates": updates,
                "misconception_tags": tags,
            },
            "sources": sources,
        }

    graph = StateGraph(CultureGraphState)
    graph.add_node("tutor", tutor)
    graph.add_edge(START, "tutor")
    graph.add_edge("tutor", END)
    return graph.compile()
