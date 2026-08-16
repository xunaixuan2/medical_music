from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.graphs.culture_graph import build_culture_graph
from app.graphs.learning_graph import build_learning_graph
from app.repository import SessionRepository
from app.services.audio_analysis import VoskAudioAnalyzer


class StartSessionRequest(BaseModel):
    course_id: str = Field(..., description="课程 ID，例如 huangdi_neijing_01")


class ActionRequest(BaseModel):
    action: str = Field(..., description="当前阶段允许的动作，见 learning_graph.ALLOWED_ACTIONS")
    payload: dict[str, Any] = Field(default_factory=dict)


class PinyinAnalyzeRequest(BaseModel):
    audio_ref: str = Field(..., description="录音引用，来自 /v1/recordings 的 audio_ref")
    target_hanzi: str = Field(..., description="目标句子汉字")
    target_pinyin: str = Field(..., description="目标句子拼音")


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_RECORDINGS_DIR = _DATA_DIR / "recordings"


def _resolve_model_dir() -> Path:
    """定位 Vosk 中文模型目录。

    可通过环境变量 VOSK_MODEL_PATH 覆盖；默认放在用户主目录下（ASCII 路径）。
    注意：项目路径含中文（如「作业」）时，Vosk 的 C++ 库无法打开模型文件，
    故不能默认使用项目内相对路径。
    """
    env = os.environ.get("VOSK_MODEL_PATH")
    if env:
        return Path(env)
    return Path.home() / "vosk-model-small-cn-0.22"


_MODEL_DIR = _resolve_model_dir()

repository = SessionRepository()
analyzer = VoskAudioAnalyzer(model_path=_MODEL_DIR, recordings_dir=_RECORDINGS_DIR)
culture_graph = build_culture_graph()
learning_graph = build_learning_graph(repository, analyzer, culture_graph)

# 服务端会话态（MVP 内存态；后续由 PostgreSQL / Redis 承接）
_SESSIONS: dict[str, dict[str, Any]] = {}

app = FastAPI(title="声入华夏 API", version="0.1.0")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "sessions": len(_SESSIONS), "records": repository.count()}


@app.post("/v1/sessions")
def start_session(req: StartSessionRequest) -> dict[str, Any]:
    """创建一个学习会话（选择课程），返回会话态与下一步动作。"""
    session_id = uuid.uuid4().hex
    session = {"phase": "course_selection", "course_id": req.course_id}
    _SESSIONS[session_id] = session
    return {"session_id": session_id, "session": session, "next_action": "course_selected"}


@app.post("/v1/sessions/{session_id}/action")
def dispatch_action(session_id: str, req: ActionRequest) -> dict[str, Any]:
    """对会话执行一个动作，推进学习状态机一步。"""
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    result = learning_graph.invoke({"session": session, "action": req.action, "payload": req.payload})
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])

    _SESSIONS[session_id] = result["session"]
    return {"session": result["session"], "response": result["response"]}


@app.post("/v1/recordings")
async def upload_recording(file: UploadFile = File(...), duration_ms: int = Form(0)) -> dict[str, Any]:
    """接收用户录音，保存到本地，返回可引用的 audio_ref。"""
    _RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "recording.webm").suffix.lower() or ".webm"
    name = f"{uuid.uuid4().hex}{ext}"
    dest = _RECORDINGS_DIR / name
    dest.write_bytes(await file.read())
    return {"audio_ref": f"recordings/{name}", "duration_ms": duration_ms, "filename": name}


@app.post("/v1/pinyin/analyze")
def analyze_pinyin(req: PinyinAnalyzeRequest) -> dict[str, Any]:
    """对单句跟读录音做 ASR 转写与逐字发音分析。"""
    return analyzer.analyze_sentence(req.audio_ref, req.target_hanzi, req.target_pinyin)
