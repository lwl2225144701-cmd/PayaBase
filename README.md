# PayaBase · 个人 AI 知识库助手

把你的个人知识变成「可检索、可对话、可分发」的能力 —— 基于 RAG 检索增强问答、自治 Agent 编排与多源知识接入的通用 AI 知识库平台。

## 核心能力

- **知识库管理**:支持本地 / 飞书 / Google Drive 文档导入,个人专属知识沉淀
- **RAG 检索问答**:pgvector 向量检索 + BM25 关键词检索 + RRF 融合 + 重排序,chunk 预置摘要与 HyDE 假设问题增强召回
- **自治 Agent**:单一 Agent 统一编排,通过显式 `current_step` / `next_step` / `plan_snapshot` 解决长链路遗忘问题
- **多模态**:图片 Vision 解析、PPT / PDF 产物异步生成
- **多平台接入**:飞书 / 微信 / QQ 回调,Adapter 模式统一消息处理
- **Web 搜索增强**:集成 OpenSERP 搜索引擎抓取聚合,支持 Agent 联网检索

## 系统架构

```
浏览器 / 平台回调
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  web (Next.js 14)  前端 · 对话 / 知识库管理 / 数据统计  │
└──────────────────────┬──────────────────────────────┘
                       │ SSE · REST
                       ▼
┌─────────────────────────────────────────────────────┐
│  training_agent (FastAPI)  核心后端                    │
│  ┌──────────┬──────────┬───────────┬──────────────┐  │
│  │ API 路由  │ RAG 检索  │ Agent 编排 │ Celery 异步  │  │
│  └──────────┴──────────┴───────────┴──────────────┘  │
└───┬──────────────┬──────────────┬───────────────┬───┘
    │              │              │               │
    ▼              ▼              ▼               ▼
┌────────┐   ┌─────────┐   ┌──────────┐   ┌────────────┐
│ vectord│   │ rerankd │   │ searchd  │   │ PostgreSQL │
│ 向量化  │   │ 重排序   │   │ 搜索封装  │   │ + pgvector │
└────────┘   └─────────┘   └────┬─────┘   │ Redis      │
                                │         │ MinIO      │
                                ▼         └────────────┘
                         ┌────────────┐
                         │  openserp  │
                         │ SERP 抓取   │
                         └────────────┘
```

## 技术栈

| 层 | 技术 |
|---|---|
| **前端** | Next.js 14 (App Router) · React 18 · TypeScript · TanStack Query v5 · Tailwind CSS · shadcn/Radix UI · recharts · mermaid |
| **后端** | Python 3.12 · FastAPI · SQLAlchemy 2.x (async) · Celery · LangChain |
| **数据库** | PostgreSQL + pgvector(向量检索) · Redis(broker + 缓存) · MinIO(对象存储) |
| **AI 服务** | LLM(OpenAI 兼容接口,按用途拆分 classify/chat/vision) · Embedding(all-MiniLM-L6-v2) · Rerank(BAAI/bge-reranker-base) |
| **搜索** | OpenSERP(Go,go-rod 驱动 Chromium 抓取) · searchd(封装熔断/缓存/回退) |
| **部署** | Docker Compose · Nginx |

## 目录结构

```
ai_dify_light/
├── training_agent/          # 核心后端(Python)
│   ├── api/                 #   FastAPI 路由层
│   ├── core/                #   核心逻辑层
│   │   ├── rag/             #     解析 / 清洗 / 分块 / 检索 / 重排 / 图片绑定
│   │   ├── agent/           #     自治 Agent 编排(orchestrator/planner/runner)
│   │   ├── tasks/           #     Celery 异步任务(索引 / PPT / PDF)
│   │   ├── adapters/        #     平台消息适配器(飞书/微信/QQ)
│   │   ├── sources/         #     文档源抽象(本地/飞书/Drive)
│   │   ├── embedding/       #     向量化客户端
│   │   └── llm/             #     LLM 客户端
│   ├── models/              #   SQLAlchemy ORM 模型
│   ├── services/            #   业务服务层
│   ├── scripts/             #   初始化与迁移脚本
│   └── infra/               #   docker-compose 编排
├── web/                     # 前端(Next.js)
│   └── src/
│       ├── app/             #   App Router 路由(chat/kb/stats/login)
│       ├── components/      #   业务组件 + 通用 UI
│       ├── hooks/           #   React Query hooks
│       └── lib/             #   API 客户端
├── openserp-main/           # SERP 搜索引擎抓取服务(Go,第三方开源)
└── docs/                    # 项目文档(可观测性设计等)
```

## 快速开始

### 前置条件

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose
- uv(Python 包管理)
- Ollama(本地分类模型,可选)

### 1. 启动基础依赖

```bash
cd training_agent
docker compose -f infra/docker-compose.yaml up -d
```

启动服务:PostgreSQL(pgvector)、Redis、MinIO、vectord、rerankd、openserp、searchd、celery-worker。

### 2. 配置环境变量

```bash
cd training_agent
cp .env.example .env
# 编辑 .env,填写 LLM API Key、数据库连接等
```

### 3. 初始化数据库

```bash
python scripts/init_db.py
```

### 4. 启动后端

```bash
cd training_agent
source .venv/bin/activate    # 激活虚拟环境

# 终端 A:API 服务
uvicorn api.main:app --reload --host 0.0.0.0 --port 8123

# 终端 B:Celery Worker(文档索引 / PPT / PDF)
celery -A core.tasks worker -l info
```

健康检查:`curl http://127.0.0.1:8123/health`

### 5. 启动前端

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

### 端口一览

| 服务 | 端口 | 说明 |
|---|---|---|
| 前端 | 3000 | Next.js dev server |
| 后端 API | 8123 | FastAPI |
| PostgreSQL | 5432 | training / training123 |
| Redis | 6379 | broker + 缓存 |
| MinIO | 9000 / 9001 | API / 控制台 |
| vectord | 8001 | Embedding 服务 |
| rerankd | 8003 | 重排序服务 |
| searchd | 8004 | 搜索封装服务 |
| openserp | 7070 | SERP 抓取服务 |

## LLM 模型配置

系统按用途拆分三类模型,各自可独立配置供应商、API Key、Base URL:

| 用途 | 环境变量 | 说明 |
|---|---|---|
| 意图分类 | `LLM_CLASSIFY_*` | 轻量快速,推荐本地 Ollama |
| 对话生成 | `LLM_CHAT_*` | 高质量,用于最终回答 |
| 图像理解 | `LLM_VISION_*` | Vision 模型,图片解析 |
| 默认 fallback | `LLM_*` | 上述未配置时回退到此 |

详见 `.env.example`。

## 主要 API

| 分组 | 路径 |
|---|---|
| 认证 | `/api/auth/*` |
| 知识库 | `/api/kb/*` |
| 文档 | `/api/kb/{kb_id}/docs/*` |
| 对话 | `/api/conversations/*` |
| 外部来源 | `/api/sources/*` |
| 平台回调 | `/api/platform/{platform}/callback` |
| 产物 | `/api/ppt/*` · `/api/pdf/*` |
| 统计 | `/api/stats/*` |
| Agent | `/api/agent/runs/*` |

## 部署

### 后端生产部署

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8123 --workers 4
# 或 gunicorn + uvicorn workers
gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8123
```

建议:Nginx 反向代理(120m body + 300s 超时)、systemd 进程管理、API 与 Worker 独立服务。

### 前端生产部署

```bash
cd web
npm ci
npm run build
npm run start          # 默认 3000 端口
```

## License

本项目仅供学习交流使用。
