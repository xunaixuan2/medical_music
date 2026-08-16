# 声入华夏 · 唱古籍学中文

> 通过演唱《黄帝内经》等古籍经典，学习中文发音、领悟传统文化内涵的交互式学习应用。
> 首发课程《黄帝内经·素问·四气调神大论（选段）》。

## 项目简介

「声入华夏」面向中文学习者与传统文化爱好者，把「学发音」这件事做成一门可唱、可听、可练的古籍吟唱课。学习者依次完成：

```
选择课程 → 拼音跟读 → 跟唱学习 → 演唱分析 → 文化导师 → 学习报告
```

- **拼音跟读**：逐句领读（浏览器 TTS）＋ 录音上传 ＋ 离线语音识别（ASR）＋ 逐字发音反馈。
- **跟唱学习**：播放原唱，用户录制自己的跟唱并上传。
- **演唱分析**：语音识别转写歌词，与原文逐字比对，给出「发音 / 歌词 / 节奏」得分与易错字反馈。
- **文化导师**：围绕歌词做苏格拉底式问答，纠正「阴＝坏」之类的常见误解。
- **学习报告**：汇总得分、文化掌握度、易错字与复习推荐，支持随时返回前序步骤重练。

## 核心功能

| 模块 | 说明 |
| --- | --- |
| 选课 | 内置两门课：`四气调神大论（选段）`（可学）、`阴阳应象大论`（敬请期待占位） |
| 拼音跟读 | 10 个句子逐句跟读，先听领读再录音，返回识别文本、准确度与逐字建议 |
| 跟唱学习 | 播放原唱 `yuanchang.mp3`，用浏览器 `MediaRecorder` 录音并上传 |
| 演唱分析 | Vosk 离线 ASR 转写 → 与原文字符级比对 → 发音/歌词/节奏得分 |
| 文化导师 | 基于规则的误解识别 + 引导式追问（MVP 桩，后续接 RAG/LLM） |
| 学习报告 | 汇总演唱得分、文化掌握度、易错字、复习推荐，支持返回任意步骤 |

## 技术栈

- **后端**：Python 3.10+ / FastAPI / Pydantic v2 / Uvicorn
- **状态机**：LangGraph（`learning_graph` + `culture_graph` 两张子图）
- **语音识别**：Vosk（离线中文小模型，CPU 可跑，无需 GPU / torch）
- **拼音**：pypinyin（带声调）
- **音频处理**：ffmpeg（webm → 16k 单声道 wav）
- **前端**：原生 HTML/CSS/JS 单页应用（中医风格 UI），Web Speech API 领读 + MediaRecorder 录音
- **数据持久化**：MVP 内存态 + JSONL 追加写（`backend/data/sessions.jsonl`），后续可替换为 PostgreSQL

## 目录结构

```
shengruhuaxia-demo/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI 入口 + 全部路由
│   │   ├── course_content.py           # 课程内容（歌词/拼音/句子）
│   │   ├── repository.py               # 会话持久化（JSONL）
│   │   ├── graphs/
│   │   │   ├── learning_graph.py       # 学习流程状态机
│   │   │   └── culture_graph.py        # 文化导师子图
│   │   ├── services/
│   │   │   └── audio_analysis.py       # Vosk 语音识别 + 发音比对
│   │   └── static/
│   │       ├── index.html              # 前端单页应用
│   │       └── audio/yuanchang.mp3     # 原唱音频
│   ├── data/                           # 运行时生成（录音 + sessions.jsonl）
│   ├── models/                         # Vosk 模型（需自行下载，不入库）
│   ├── demo.py                         # 端到端演示脚本
│   └── requirements.txt                # Python 依赖
├── 项目计划书.docx                      # 原始项目计划（参考）
└── 黄帝内经·四时调神大论_43秒至1分43秒.mp3  # 原唱素材
```

## 环境要求

- **Python** 3.10+（开发验证环境为 3.11.5）
- **ffmpeg**（需在系统 PATH 中，用于音频解码）
  - Windows：`winget install ffmpeg` 或到 <https://www.gyan.dev/ffmpeg/builds/> 下载
  - macOS：`brew install ffmpeg`
  - Linux：`sudo apt install ffmpeg`
- **Vosk 中文模型**（单独下载，约 40MB，见下文）

## 快速开始

### 1. 克隆并进入项目

```bash
git clone <你的仓库地址>
cd shengruhuaxia-demo/backend
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 下载 Vosk 中文模型（必需）

语音识别需要一个离线中文模型，放到**用户主目录**（ASCII 路径）下，命名须为 `vosk-model-small-cn-0.22`：

```bash
# macOS / Linux
curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
unzip model.zip -d ~/
```

```powershell
# Windows（PowerShell）
Invoke-WebRequest -Uri https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip -OutFile model.zip
Expand-Archive model.zip -DestinationPath $HOME
```

完成后应得到 `~/vosk-model-small-cn-0.22/`（`am/final.mdl`、`conf/model.conf` 等文件）。

> **模型路径说明**：程序默认从 `~/vosk-model-small-cn-0.22` 加载模型；也可用环境变量覆盖：
>
> ```bash
> # Windows PowerShell
> $env:VOSK_MODEL_PATH = "D:\models\vosk-model-small-cn-0.22"
> # macOS / Linux
> export VOSK_MODEL_PATH=/path/to/vosk-model-small-cn-0.22
> ```
>
> **重要**：Vosk 的 C++ 库**无法从含中文等非 ASCII 字符的路径加载模型**。因此若你的项目路径含中文（如 `E:\作业\...`），务必把模型放到纯英文路径（默认的用户主目录通常满足），否则启动会报 `does not contain model files`。

### 4. 启动后端服务

```bash
uvicorn app.main:app --reload
```

浏览器打开 <http://127.0.0.1:8000> 即可开始学习。

- 交互式 API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

> **提示**：录音功能需要浏览器麦克风权限，请使用 `localhost`/`127.0.0.1` 访问（`file://` 或非安全上下文会禁用麦克风）。

## API 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 前端单页应用（index.html） |
| GET | `/health` | 健康检查（会话数 / 记录数） |
| POST | `/v1/sessions` | 创建学习会话（传 `course_id`） |
| POST | `/v1/sessions/{id}/action` | 推进状态机一步（传 `action` + `payload`） |
| POST | `/v1/recordings` | 上传录音（multipart `file` + `duration_ms`），返回 `audio_ref` |
| POST | `/v1/pinyin/analyze` | 单句跟读分析（`audio_ref` + `target_hanzi` + `target_pinyin`） |

## 端到端演示脚本

无需浏览器即可驱动状态机走完整条学习闭环（选课→跟读→跟唱→分析→文化→报告→重开）：

```bash
cd backend
python demo.py
```

## 已知限制

- **语音识别精度**：Vosk 小模型对古汉语、演唱（带旋律/哼唱）场景识别率有限，静音或纯哼唱会识别为空、准确度偏低。这是模型能力边界，可通过换更大的中文模型（如 `vosk-model-cn-0.22`）或接入音准/节奏专用分析来提升。
- **音准 / 韵律**：当前 `pitch`、`prosody` 两项评分暂未实现（返回 `null`），属于第二阶段能力。
- **文化导师**：目前是基于规则的「误解识别 + 引导式追问」桩，后续可替换为 RAG（检索知识库 + LLM 生成分层解释）。
- **会话态**：MVP 使用内存字典 + JSONL 落盘，重启服务后内存会话丢失（历史记录仍在 `data/sessions.jsonl`），后续可迁移到 PostgreSQL / Redis。

## 后续规划

- [ ] 接入更大的中文 ASR 模型 / 云端语音服务，提升识别率
- [ ] 增加音准（pitch）、韵律（prosody）分析
- [ ] 文化导师升级为 RAG + LLM 真实对话
- [ ] 课程内容后台 / 数据库承接，支持多课程
- [ ] 会话与用户体系（登录、进度、错题本）
