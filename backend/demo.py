"""端到端演示：驱动 learning_graph 走完一次完整学习闭环。

覆盖：选课 → 试听 → 拼音跟读 → 演唱录制分析 → 文化导师对话 → 学习报告 → 重开。
在 backend 目录下运行：python demo.py
"""
from __future__ import annotations

import os
from pathlib import Path

from app.graphs.culture_graph import build_culture_graph
from app.graphs.learning_graph import build_learning_graph
from app.repository import SessionRepository
from app.services.audio_analysis import QwenAudioAnalyzer


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    base = Path(__file__).resolve().parent
    _load_dotenv(base / ".env")
    analyzer = QwenAudioAnalyzer(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        recordings_dir=base / "data" / "recordings",
        model=os.environ.get("QWEN_ASR_MODEL", "qwen-audio-3.0-asr-flash"),
    )
    graph = build_learning_graph(SessionRepository(), analyzer, build_culture_graph())

    session = {"phase": "course_selection", "course_id": "siqi_tiaoshen_01"}

    steps = [
        ("course_selected", {}),
        ("begin_practice", {}),
        ("pinyin_decision", {"mode": "practice"}),
        ("pinyin_attempt", {"token": "生 shēng"}),
        ("recording_submitted", {"audio_ref": "s3://demo/user1_rec.wav", "duration_ms": 180000}),
        ("open_culture", {}),
        ("culture_message", {"message": "阴是不是代表坏的东西？"}),
        ("culture_message", {"message": "我明白了，阴阳是相互依存、变化的属性。"}),
        ("complete_culture", {}),
    ]

    for action, payload in steps:
        result = graph.invoke({"session": session, "action": action, "payload": payload})
        if result.get("error"):
            print(f"[{action}] ERROR: {result['error']}")
            return
        session = result["session"]
        resp = result.get("response", {})
        print(f"[{action}] phase={session.get('phase')}")

        if action == "pinyin_attempt":
            print(f"    feedback={resp.get('feedback')}")
        elif action == "recording_submitted":
            print(f"    scores={resp.get('analysis', {}).get('scores')}")
        elif action == "culture_message":
            turn = resp.get("turn", {})
            print(f"    tutor={turn.get('answer', '')}")
            print(f"    misconception_tags={turn.get('misconception_tags')}")
        elif action == "complete_culture":
            print(f"    report={resp.get('report')}")

    print("\n=== 学习闭环走通 ===")
    print("concept_mastery:", session.get("concept_mastery"))
    print("recommendation:", session.get("recommendation"))

    # 演示重开：回到选课阶段，为下一首歌做准备
    result = graph.invoke({"session": session, "action": "restart", "payload": {}})
    session = result["session"]
    print(f"[restart] phase={session.get('phase')}")


if __name__ == "__main__":
    main()
