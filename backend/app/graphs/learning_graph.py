from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.repository import SessionRepository
from app.services.audio_analysis import AudioAnalysisPort


class LearningGraphState(TypedDict, total=False):
    session: dict[str, Any]
    action: str
    payload: dict[str, Any]
    response: dict[str, Any]
    error: str


ALLOWED_ACTIONS: dict[str, set[str]] = {
    "course_selection": {"course_selected"},
    "course_experience": {"begin_practice"},
    "pinyin_choice": {"pinyin_decision"},
    "pinyin_training": {"pinyin_attempt"},
    "singing": {"recording_submitted"},
    "analysis_complete": {"open_culture"},
    "culture": {"culture_message", "complete_culture"},
    "report": {"restart"},
}


def _set_phase(session: dict, phase: str, step: int) -> dict:
    session["phase"] = phase
    session["current_step"] = step
    return session


def build_learning_graph(repository: SessionRepository, analyzer: AudioAnalysisPort, culture_graph):
    def validate(state: LearningGraphState) -> dict:
        phase = state["session"]["phase"]
        action = state["action"]
        if action not in ALLOWED_ACTIONS.get(phase, set()):
            return {"error": f"动作 {action} 不允许在 {phase} 阶段执行。"}
        return {}

    def route(state: LearningGraphState) -> Literal["course", "practice", "decision", "coach", "audio", "culture_open", "culture_chat", "report", "restart", "invalid"]:
        if state.get("error"):
            return "invalid"
        return {
            "course_selected": "course", "begin_practice": "practice", "pinyin_decision": "decision",
            "pinyin_attempt": "coach", "recording_submitted": "audio", "open_culture": "culture_open",
            "culture_message": "culture_chat", "complete_culture": "report", "restart": "restart",
        }[state["action"]]

    def course_selected(state: LearningGraphState) -> dict:
        session = _set_phase(deepcopy(state["session"]), "course_experience", 1)
        return {"session": session, "response": {"phase": session["phase"], "course": session["course_id"], "next_action": "begin_practice"}}

    def begin_practice(state: LearningGraphState) -> dict:
        session = _set_phase(deepcopy(state["session"]), "pinyin_choice", 2)
        return {"session": session, "response": {"phase": session["phase"], "next_action": "pinyin_decision", "options": ["practice", "skip"]}}

    def pinyin_decision(state: LearningGraphState) -> dict:
        mode = state["payload"].get("mode")
        if mode not in {"practice", "skip"}:
            return {"error": "pinyin_decision 需要 payload.mode 为 practice 或 skip。"}
        session = deepcopy(state["session"])
        session["pinyin_mode"] = mode
        if mode == "practice":
            _set_phase(session, "pinyin_training", 2)
            response = {"phase": "pinyin_training", "focus_tokens": ["生 shēng", "荣 róng", "春 chūn", "缓 huǎn"], "next_action": "pinyin_attempt"}
        else:
            _set_phase(session, "singing", 3)
            response = {"phase": "singing", "next_action": "recording_submitted"}
        return {"session": session, "response": response}

    def pinyin_coach(state: LearningGraphState) -> dict:
        token = state["payload"].get("token", "生 shēng")
        feedback = {"token": token, "score": 78, "issue": "韵尾收束不足", "advice": f"练习 {token.split()[0]}、{token.split()[0]}、{token.split()[0]}，再回到完整歌词。"}
        session = _set_phase(deepcopy(state["session"]), "singing", 3)
        session.setdefault("pronunciation_history", []).append(feedback)
        return {"session": session, "response": {"feedback": feedback, "phase": "singing", "next_action": "recording_submitted"}}

    def analyze_audio(state: LearningGraphState) -> dict:
        payload = state["payload"]
        analysis = analyzer.analyze(payload["audio_ref"], int(payload["duration_ms"]), state["session"]["course_id"])
        session = _set_phase(deepcopy(state["session"]), "analysis_complete", 4)
        session["analysis"] = analysis
        return {"session": session, "response": {"analysis": analysis, "phase": "analysis_complete", "next_action": "open_culture"}}

    def open_culture(state: LearningGraphState) -> dict:
        session = _set_phase(deepcopy(state["session"]), "culture", 5)
        return {"session": session, "response": {"phase": "culture", "focus_concept": "spring_renewal", "next_action": "culture_message"}}

    def culture_chat(state: LearningGraphState) -> dict:
        message = state["payload"].get("message", "")
        if not message.strip():
            return {"error": "culture_message 需要 payload.message。"}
        result = culture_graph.invoke({"course_id": state["session"]["course_id"], "message": message})
        turn = result["tutor_turn"]
        session = deepcopy(state["session"])
        session.setdefault("culture_dialogue", []).append({"user": message, "assistant": turn["answer"], "sources": result["sources"]})
        mastery = session.setdefault("concept_mastery", {})
        for concept, delta in turn["concept_updates"].items():
            mastery[concept] = min(100, mastery.get(concept, 0) + delta)
        session.setdefault("misconception_tags", []).extend(turn["misconception_tags"])
        return {"session": session, "response": {"turn": turn, "sources": result["sources"], "phase": "culture"}}

    def report_builder(state: LearningGraphState) -> dict:
        session = _set_phase(deepcopy(state["session"]), "report", 6)
        analysis = session.get("analysis", {})
        scores = analysis.get("scores", {})
        report = {
            "pronunciation_score": scores.get("pronunciation", 0), "rhythm_score": scores.get("rhythm", 0),
            "pitch_score": scores.get("pitch", 0), "prosody_score": scores.get("prosody", 0),
            "culture_mastery": session.get("concept_mastery", {}),
            "common_errors": [item["token"] for item in analysis.get("pronunciation_feedback", [])],
        }
        session["report"] = report
        return {"session": session, "response": {"report": report, "phase": "report"}}

    def recommend(state: LearningGraphState) -> dict:
        session = deepcopy(state["session"])
        recommendation = {"review_tokens": ["生 shēng", "荣 róng", "缓 huǎn"], "review_line": "天地俱生，万物以荣", "next_course": None}
        session["recommendation"] = recommendation
        response = dict(state["response"])
        response["recommendation"] = recommendation
        response["learning_loop"] = "已保存错误、掌握度和下一次复习任务。"
        return {"session": session, "response": response}

    def restart(state: LearningGraphState) -> dict:
        old = state["session"]
        session = {**old, "phase": "course_selection", "current_step": 1, "pinyin_mode": None, "analysis": None, "culture_dialogue": [], "concept_mastery": {}, "report": None, "recommendation": None}
        return {"session": session, "response": {"phase": "course_selection", "next_action": "course_selected"}}

    def persist(state: LearningGraphState) -> dict:
        repository.persist(state["session"], state["action"], state["payload"], state.get("response", {}))
        return {}

    def invalid(state: LearningGraphState) -> dict:
        return {"response": {"error": state["error"]}}

    graph = StateGraph(LearningGraphState)
    graph.add_node("validate", validate)
    graph.add_node("course_selected", course_selected)
    graph.add_node("begin_practice", begin_practice)
    graph.add_node("pinyin_decision", pinyin_decision)
    graph.add_node("pinyin_coach", pinyin_coach)
    graph.add_node("analyze_audio", analyze_audio)
    graph.add_node("open_culture", open_culture)
    graph.add_node("culture_chat", culture_chat)
    graph.add_node("report_builder", report_builder)
    graph.add_node("recommend", recommend)
    graph.add_node("restart", restart)
    graph.add_node("persist", persist)
    graph.add_node("invalid", invalid)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", route, {
        "course": "course_selected", "practice": "begin_practice", "decision": "pinyin_decision", "coach": "pinyin_coach", "audio": "analyze_audio", "culture_open": "open_culture", "culture_chat": "culture_chat", "report": "report_builder", "restart": "restart", "invalid": "invalid",
    })
    for node in ["course_selected", "begin_practice", "pinyin_decision", "pinyin_coach", "analyze_audio", "open_culture", "culture_chat", "restart"]:
        graph.add_edge(node, "persist")
    graph.add_edge("report_builder", "recommend")
    graph.add_edge("recommend", "persist")
    graph.add_edge("persist", END)
    graph.add_edge("invalid", END)
    return graph.compile()
