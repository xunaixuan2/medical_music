from __future__ import annotations

import difflib
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Protocol

import vosk
from pypinyin import Style
from pypinyin import pinyin as to_pinyin

from app.course_content import get_course

vosk.SetLogLevel(-1)

_PUNCT = "，。；、：！？\"'“”‘’（）《》【】,.;:!? \t\n\r"


class AudioAnalysisPort(Protocol):
    """音频分析端口（接口）。真实实现见 VoskAudioAnalyzer。"""

    def analyze(self, audio_ref: str, duration_ms: int, course_id: str) -> dict[str, Any]:
        ...


def _strip_punct(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def _pinyin_tones(text: str) -> list[str]:
    """逐字转拼音（带声调）。异读字（如「被」pī）以 pypinyin 默认读音为准，仅作辅助展示。"""
    return [syl[0] for syl in to_pinyin(text, style=Style.TONE)]


class VoskAudioAnalyzer:
    """基于 Vosk 的真实音频分析器。

    流程：录音文件 → ffmpeg 转 16k 单声道 wav → Vosk 中文 ASR 转写
         → 与目标文本字符级对比 → 输出歌词准确度 + 逐字发音反馈。
    局限：Vosk 小模型对古汉语/演唱场景识别率有限；节奏/音准/韵律为第二阶段能力。
    """

    def __init__(self, model_path: str | Path, recordings_dir: str | Path) -> None:
        self._model = vosk.Model(str(model_path))
        self._recordings_dir = Path(recordings_dir)

    def _resolve(self, audio_ref: str) -> str:
        if audio_ref.startswith("recordings/"):
            return str(self._recordings_dir / Path(audio_ref).name)
        return audio_ref

    def _transcribe(self, audio_path: str) -> str:
        if not os.path.exists(audio_path):
            return ""
        wav_path = None
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            subprocess.run(
                ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                check=True, capture_output=True,
            )
            wf = wave.open(wav_path, "rb")
            rec = vosk.KaldiRecognizer(self._model, 16000)
            parts: list[str] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    parts.append(json.loads(rec.Result()).get("text", ""))
            parts.append(json.loads(rec.FinalResult()).get("text", ""))
            wf.close()
            return "".join(parts).strip()
        except Exception:
            return ""
        finally:
            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)

    def _compare(self, target: str, recognized: str) -> tuple[int, list[dict[str, Any]]]:
        """字符级对比，返回 (准确度 0-100, 未识别目标字列表)。"""
        if not target:
            return 0, []
        sm = difflib.SequenceMatcher(None, target, recognized)
        matched = 0
        mismatches: list[dict[str, Any]] = []
        t_tones = _pinyin_tones(target)
        for op, i1, i2, _j1, _j2 in sm.get_opcodes():
            if op == "equal":
                matched += i2 - i1
            else:
                for k in range(i1, i2):
                    token = target[k]
                    tp = t_tones[k] if k < len(t_tones) else ""
                    mismatches.append({
                        "token": token,
                        "target_pinyin": tp,
                        "recognized_pinyin": "",
                        "type": "misrecognized",
                        "advice": f"「{token}」未被听清，请放慢重读（{tp}）。",
                    })
        score = round(matched / len(target) * 100)
        return score, mismatches

    def _rhythm_score(self, duration_ms: int, expected_ms: int) -> int:
        if not duration_ms or not expected_ms:
            return 70
        ratio = duration_ms / expected_ms
        if 0.8 <= ratio <= 1.2:
            return 85
        if 0.6 <= ratio <= 1.5:
            return 70
        return 55

    def analyze(self, audio_ref: str, duration_ms: int, course_id: str) -> dict[str, Any]:
        course = get_course(course_id) or {}
        target = _strip_punct(course.get("lyrics", ""))
        recognized = self._transcribe(self._resolve(audio_ref))
        recognized_clean = _strip_punct(recognized)
        char_score, mismatches = self._compare(target, recognized_clean)

        return {
            "audio_ref": audio_ref,
            "duration_ms": duration_ms,
            "course_id": course_id,
            "recognized": recognized,
            "scores": {
                "pronunciation": char_score,
                "lyrics_accuracy": char_score,
                "rhythm": self._rhythm_score(int(duration_ms), int(course.get("expected_duration_ms", 0))),
                "pitch": None,
                "prosody": None,
            },
            "pronunciation_feedback": mismatches[:6],
        }

    def analyze_sentence(self, audio_ref: str, target_hanzi: str, target_pinyin: str) -> dict[str, Any]:
        """单句跟读分析，返回识别文本、准确度与逐字反馈。"""
        recognized = self._transcribe(self._resolve(audio_ref))
        target = _strip_punct(target_hanzi)
        recognized_clean = _strip_punct(recognized)
        score, mismatches = self._compare(target, recognized_clean)
        advice = "发音标准，继续保持。" if score >= 80 else "部分字音未听清，请对照拼音再跟读一次。"
        return {
            "recognized": recognized,
            "accuracy": score,
            "mismatches": mismatches,
            "advice": advice,
        }
