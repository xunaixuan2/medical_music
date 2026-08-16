"""本地关键词检索 + 可选 DashScope 兼容 LLM + 稳定降级的文化问答。"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

try:
    import httpx
except ImportError:  # 允许未安装可选依赖时继续使用本地知识卡降级回答。
    httpx = None

from app.knowledge_base import KNOWLEDGE_CARDS

_MEDICAL_TERMS = ("怎么治", "治疗", "吃什么药", "开药", "处方", "诊断", "病情", "疾病", "失眠怎么办", "发烧", "疼", "用药", "剂量")
_DEFAULT_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def retrieve(question: str, top_k: int = 3) -> list[dict[str, Any]]:
    """显式关键词加权检索，便于比赛现场解释命中原因。"""
    normalized = "".join(question.lower().split())
    scored = []
    for card in KNOWLEDGE_CARDS:
        score = sum(len(keyword) for keyword in card["keywords"] if keyword.lower() in normalized)
        if score:
            scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in scored[:top_k]]


def _sources(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for card in cards:
        source = card["source"]
        unique.setdefault(f"{source['title']}::{source['citation']}", source)
    return list(unique.values())


def _fallback(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "当前课程资料暂未覆盖这个问题。你可以围绕歌词中的“发陈、万物以荣、蕃秀、华实”等关键词继续提问。"
    card = cards[0]
    return f"{card['content']}\n\n想一想：{card['follow_up']}"


def _context(cards: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"【{card['title']}】\n解释：{card['content']}\n出处：{card['source']['title']}：{card['source']['citation']}\n引导问题：{card['follow_up']}" for card in cards)


def _call_llm(question: str, cards: list[dict[str, Any]]) -> str | None:
    api_key = os.getenv("CULTURE_LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key or not cards or httpx is None:
        return None
    body = {"model": os.getenv("CULTURE_LLM_MODEL", "qwen-plus"), "messages": [{"role": "system", "content": "你是《黄帝内经·AI传唱》的文化学习导师，不是医生。只依据给定知识卡回答；先用一句启发性问题引导，再用简明中文解释。不得给出诊疗、处方、用药或个体健康建议；不确定时说课程资料不足。不要虚构出处，也不要重复来源列表。"}, {"role": "user", "content": f"【用户问题】\n{question}\n\n【可用知识卡】\n{_context(cards)}"}], "temperature": 0.3}
    try:
        response = httpx.post(os.getenv("CULTURE_LLM_BASE_URL", _DEFAULT_CHAT_URL), headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=15)
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip() or None
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None


def answer_culture_question(question: str) -> dict[str, Any]:
    question = question.strip()
    if any(term in question for term in _MEDICAL_TERMS):
        return {"answer": "这个问题涉及个人健康或诊疗。该产品仅用于古籍与文化学习，不能提供诊断、处方或用药建议；如有健康困扰，请咨询合格的医疗专业人员。", "sources": [], "concept_updates": {}, "misconception_tags": ["medical_request"], "retrieved_cards": [], "mode": "safety"}
    cards = retrieve(question)
    answer = _call_llm(question, cards)
    updates: dict[str, int] = defaultdict(int)
    for card in cards:
        updates[card["concept"]] += 10
    return {"answer": answer or _fallback(cards), "sources": _sources(cards), "concept_updates": dict(updates), "misconception_tags": [], "retrieved_cards": [{"id": card["id"], "title": card["title"]} for card in cards], "mode": "llm" if answer else "local_fallback"}
