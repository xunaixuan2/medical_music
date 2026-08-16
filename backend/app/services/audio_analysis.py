from __future__ import annotations

import base64
import difflib
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
from pypinyin import Style
from pypinyin import pinyin as to_pinyin

from app.course_content import get_course

_PUNCT = "，。；、：！？\"'“”‘’（）《》【】,.;:!? \t\n\r"

# 通义千问 ASR（DashScope 百炼）非实时语音识别接口
_DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


class AsrNoWordsError(Exception):
    """ASR 已成功处理音频但未识别到任何词（哼唱/旋律/伴奏混入麦克风）。"""


class AudioAnalysisPort(Protocol):
    """音频分析端口（接口）。真实实现见 QwenAudioAnalyzer。"""

    def analyze(self, audio_ref: str, duration_ms: int, course_id: str) -> dict[str, Any]:
        ...


def _strip_punct(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def _pinyin_tones(text: str) -> list[str]:
    """逐字转拼音（带声调）。异读字（如「被」pī）以 pypinyin 默认读音为准，仅作辅助展示。"""
    return [syl[0] for syl in to_pinyin(text, style=Style.TONE)]


class QwenAudioAnalyzer:
    """基于通义千问 ASR（qwen-audio-3.0-asr-flash）的真实音频分析器。

    流程：录音文件 → ffmpeg 转 16k 单声道 wav → base64 上传 DashScope ASR 转写
         → 与目标文本字符级对比 → 输出歌词准确度 + 逐字发音反馈。
    节奏/音准/韵律为第二阶段能力（pitch、prosody 暂返回 None）。
    """

    def __init__(
        self,
        api_key: str,
        recordings_dir: str | Path,
        model: str = "qwen-audio-3.0-asr-flash",
        sample_rate: int = 16000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._sample_rate = sample_rate
        self._recordings_dir = Path(recordings_dir)

    def _resolve(self, audio_ref: str) -> str:
        if audio_ref.startswith("recordings/"):
            return str(self._recordings_dir / Path(audio_ref).name)
        return audio_ref

    def _to_wav(self, audio_path: str) -> str | None:
        """ffmpeg 转 16k 单声道 wav（临时文件），失败返回 None。"""
        if not os.path.exists(audio_path):
            return None
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                check=True, capture_output=True,
            )
            return wav_path
        except Exception:
            if os.path.exists(wav_path):
                os.remove(wav_path)
            return None

    def _transcribe_wav(self, wav_path: str) -> str:
        """对已转好的 wav 做 base64 上传 DashScope ASR，返回识别文本。

        演唱音频对语音 ASR 而言处于边界状态，偶发返回空或 ASR_RESPONSE_HAVE_NO_WORDS；
        这里做有限重试，显著提升「唱了整段」时的成功率。
        """
        audio_b64 = base64.b64encode(Path(wav_path).read_bytes()).decode()
        body = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": f"data:audio/wav;base64,{audio_b64}"},
                            }
                        ],
                    }
                ]
            },
            "parameters": {"format": "wav", "sample_rate": self._sample_rate},
        }
        no_words = False
        for _ in range(3):
            resp = httpx.post(
                _DASHSCOPE_URL,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}", "X-DashScope-SSE": "disable"},
                timeout=120,
            )
            if resp.status_code >= 400:
                try:
                    self._raise_asr_error(resp)
                except AsrNoWordsError:
                    no_words = True
                    continue
            text = self._extract_text(resp.json())
            if text.strip():
                return text
        if no_words:
            raise AsrNoWordsError("ASR 多次尝试均未识别到词")
        return ""

    @staticmethod
    def _raise_asr_error(resp: httpx.Response) -> None:
        """把「未识别到词」与其他 API 错误区分开：前者抛 AsrNoWordsError。"""
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return
        message = str(data.get("message", ""))
        if "NO_WORDS" in message:
            raise AsrNoWordsError(message)
        resp.raise_for_status()

    def _transcribe(self, audio_path: str) -> str:
        """ffmpeg 转 wav → DashScope ASR → 识别文本（单句跟读等场景复用）。"""
        wav_path = self._to_wav(audio_path)
        if not wav_path:
            return ""
        try:
            return self._transcribe_wav(wav_path)
        except Exception:
            return ""
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)

    @staticmethod
    def _read_wav_mono(wav_path: str) -> tuple[Any, int]:
        """读取 16k 单声道 wav，返回归一化 float32 样本与采样率。"""
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, sr

    def _audio_stats(self, wav_path: str) -> tuple[float, float]:
        """返回 (时长秒, 均值 RMS)，用于诊断空识别（录音太短/太安静）。"""
        samples, sr = self._read_wav_mono(wav_path)
        if samples.size == 0:
            return 0.0, 0.0
        duration = samples.size / sr
        rms = float(np.sqrt(np.mean(samples * samples)))
        return duration, rms

    @staticmethod
    def _detect_f0(frame: Any, sr: int, fmin: int = 70, fmax: int = 500):
        """单帧自相关基频检测，返回 (f0 或 None, 周期性强弱 0~1)。"""
        frame = frame - np.mean(frame)
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 0.02:
            return None, 0.0
        corr = np.correlate(frame, frame, mode="full")
        corr = corr[len(corr) // 2:]
        if corr[0] <= 0:
            return None, 0.0
        corr = corr / corr[0]
        min_lag = int(sr / fmax)
        max_lag = min(int(sr / fmin), len(corr) - 1)
        if min_lag >= max_lag:
            return None, 0.0
        seg = corr[min_lag:max_lag + 1]
        idx = int(np.argmax(seg))
        strength = float(seg[idx])
        if strength < 0.35:
            return None, strength
        return float(sr / (min_lag + idx)), strength

    def _analyze_melody(self, wav_path: str) -> tuple[int, int]:
        """启发式音准/韵律评分：F0 音高 + 能量包络。返回 (pitch, prosody) 0~100。"""
        samples, sr = self._read_wav_mono(wav_path)
        if samples.size == 0:
            return 0, 0
        frame_len = int(0.04 * sr)
        hop = int(0.02 * sr)
        strengths: list[float] = []
        energies: list[float] = []
        voiced = 0
        total = 0
        for start in range(0, len(samples) - frame_len, hop):
            frame = samples[start:start + frame_len]
            total += 1
            energies.append(float(np.sqrt(np.mean(frame * frame))))
            f0, strength = self._detect_f0(frame, sr)
            if f0 is not None:
                voiced += 1
                strengths.append(strength)
        if total == 0:
            return 0, 0
        voicing_ratio = voiced / total
        clarity = float(np.mean(strengths)) if strengths else 0.0
        # 音准 ≈ 有效发声占比 × 音高清晰度
        pitch = int(round(100 * voicing_ratio * (0.35 + 0.65 * clarity)))

        energies_np = np.asarray(energies, dtype=np.float32)
        dynamics = 0.0
        tempo_reg = 0.0
        if energies_np.size > 4:
            mean_e = float(np.mean(energies_np))
            std_e = float(np.std(energies_np))
            dynamics = min(1.0, std_e / (mean_e + 1e-6))
            e = energies_np - mean_e
            if float(np.max(np.abs(e))) > 1e-6:
                ac = np.correlate(e, e, mode="full")
                ac = ac[len(ac) // 2:]
                if ac[0] > 0:
                    ac = ac / ac[0]
                    # 音节/节奏周期约 0.2~1.2s（hop=20ms → 10~60 帧）
                    lo, hi = 10, min(60, len(ac) - 1)
                    if lo < hi:
                        tempo_reg = float(np.max(ac[lo:hi + 1]))
        # 韵律 ≈ 能量动态 × 节奏规律
        prosody = int(round(100 * (0.55 * dynamics + 0.45 * tempo_reg)))

        return max(0, min(100, pitch)), max(0, min(100, prosody))

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        output = data.get("output") or {}
        text = output.get("text")
        if text:
            return str(text).strip()
        inner = output.get("output") or {}
        sentence = inner.get("sentence") or {}
        return str(sentence.get("text") or "").strip()

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

    @staticmethod
    def _best_target(recognized: str, course: dict[str, Any], full_lyrics: str) -> str:
        """「唱哪段评哪段」：在课程各句子（段）中挑出与识别文本最匹配的一段作为评判标准。"""
        candidates = [_strip_punct(s["hanzi"]) for s in course.get("sentences", [])]
        candidates = [c for c in candidates if c]
        if full_lyrics and full_lyrics not in candidates:
            candidates.append(full_lyrics)
        best = full_lyrics
        best_score = -1.0
        for cand in candidates:
            ratio = difflib.SequenceMatcher(None, cand, recognized).ratio()
            if ratio > best_score:
                best_score = ratio
                best = cand
        return best

    @staticmethod
    def _empty_note(duration_s: float, rms: float, asr_no_words: bool = False) -> str:
        if duration_s < 2.0:
            return f"录音太短（约 {duration_s:.0f} 秒），请唱完整一句再点停止。"
        if rms < 0.02:
            return "录音音量太小，请靠近麦克风或提高音量后再试。"
        if asr_no_words:
            return (
                "检测到声音，但未能识别出清晰歌词——通常是演唱旋律、或伴奏音乐混入了麦克风。"
                "建议：① 佩戴耳机播放伴奏，避免伴奏声被麦克风收录；② 放慢语速、吐字清晰地跟唱。"
            )
        return "未能识别歌词，可能为哼唱或旋律片段；已根据音准与韵律给出反馈。"

    def analyze(self, audio_ref: str, duration_ms: int, course_id: str) -> dict[str, Any]:
        course = get_course(course_id) or {}
        full_lyrics = _strip_punct(course.get("lyrics", ""))

        recognized = ""
        asr_no_words = False
        pitch = 0
        prosody = 0
        duration_s = 0.0
        rms = 0.0
        wav_path = self._to_wav(self._resolve(audio_ref))
        if wav_path:
            try:
                try:
                    recognized = self._transcribe_wav(wav_path)
                except AsrNoWordsError:
                    asr_no_words = True
                except Exception:
                    pass
                pitch, prosody = self._analyze_melody(wav_path)
                duration_s, rms = self._audio_stats(wav_path)
            finally:
                if os.path.exists(wav_path):
                    os.remove(wav_path)

        recognized_clean = _strip_punct(recognized)

        if recognized_clean:
            target = self._best_target(recognized_clean, course, full_lyrics)
            char_score, mismatches = self._compare(target, recognized_clean)
            pronunciation: int | None = char_score
            lyrics_accuracy: int | None = char_score
            coverage = min(100, round(len(recognized_clean) / len(target) * 100)) if target else 0
            note = None
        else:
            # 未识别到歌词（哼唱/静音/过短）：不把每个字都标为“未听清”，改为优雅降级并给出具体原因
            pronunciation = None
            lyrics_accuracy = None
            mismatches = []
            coverage = 0
            note = self._empty_note(duration_s, rms, asr_no_words=asr_no_words)

        return {
            "audio_ref": audio_ref,
            "duration_ms": duration_ms,
            "course_id": course_id,
            "recognized": recognized,
            "coverage": coverage,
            "note": note,
            "scores": {
                "pronunciation": pronunciation,
                "lyrics_accuracy": lyrics_accuracy,
                "rhythm": self._rhythm_score(int(duration_ms), int(course.get("expected_duration_ms", 0))),
                "pitch": pitch,
                "prosody": prosody,
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
