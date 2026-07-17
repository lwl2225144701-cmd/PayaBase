# PayaBase Web

个人 AI 知识库助手前端应用，负责会话交互、知识库选择、附件上传、飞书/Drive 文档导入，以及 PPT/PDF 任务进度展示。

## 这个系统做什么

这个前端是 PayaBase 的操作入口。

- 普通用户在这里发起对话、查看历史消息、上传附件。
- 管理员在这里选择知识库、导入飞书和 Google Drive 文档。
- 前端把用户操作整理成统一请求，交给后端完成检索、索引和生成。

## 架构是什么

```text
浏览器
  |
  v
Next.js 页面层
  |
  +--> 聊天页 / 知识库选择 / 附件上传
  +--> 飞书授权弹窗 / Drive 链接弹窗
  +--> PPT / PDF 任务状态展示
  |
  v
API 封装层（src/lib/api.ts）
  |
  v
后端 API（本地 http://127.0.0.1:8123，由 NEXT_PUBLIC_API_URL 配置）
```

## 业务逻辑是什么

1. 用户进入聊天页后，前端先拉会话列表和可用知识库。
2. 用户发送消息时，前端把文本、附件、知识库选择一并传给后端。
3. 如果用户要导入飞书或 Drive 文档，前端负责授权、预览和选择，真正的解析与索引由后端处理。
4. 后端返回流式回答或任务状态后，前端负责展示进度和结果。

## 先看这段（2分钟跑起来）

```bash
# 1) 进入前端目录
cd web

# 2) 安装依赖
npm install

# 3) 配置后端地址
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://127.0.0.1:8123
EOF

# 4) 启动开发服务
PORT=8080 npm run dev
```

访问：`http://127.0.0.1:8080`

## 面向场景

- 培训问答与知识检索对话
- 统一附件交互（本地文件 + 外部文档来源）
- 面向业务人员的低学习成本操作界面

## 核心技术栈

- Next.js（App Router）+ React + TypeScript
- Tailwind CSS + 组件化 UI
- Fetch API（封装在 `src/lib/api.ts`）

## 目录结构（核心模块）

- `src/components/chat/`：聊天页、附件上传、飞书授权弹窗、Drive 链接弹窗
- `src/lib/api.ts`：后端 API 统一调用封装
- `src/app/`：页面入口与路由

## 启动流程（本地开发）

1. 前置条件检查

```bash
node -v   # 建议 18+
npm -v
```

2. 安装依赖

```bash
npm install
```

3. 配置环境变量

```bash
cp .env.local .env.local.bak 2>/dev/null || true
```

确保 `.env.local` 至少有：

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8123
```

4. 启动开发服务

```bash
PORT=8080 npm run dev
```

默认访问地址：

- `http://localhost:8080`

## 已接入能力

- 对话会话列表与历史消息展示
- 知识库选择并绑定会话
- 本地附件上传（多类型）
- 飞书文档导入（授权 -> 选文档 -> 上传到知识库 -> 轮询索引）
- Google Drive 导入（链接预览 -> 上传到知识库 -> 轮询索引）
- Agent 产物事件（PPT/PDF）进度展示

## 与后端接口对应

- 对话：`/api/conversations/*`
- 知识库：`/api/kb/*`
- 外部来源：`/api/sources/feishu/*`、`/api/sources/google-drive/*`、`/api/sources/upload-to-kb`
- 任务状态：`/api/ppt/*`、`/api/pdf/*`

## 常见问题排查（新同学高频）

1. 页面能打开但接口全失败
- 基本是 `NEXT_PUBLIC_API_URL` 配错
- 检查后端是否已启动：`curl http://127.0.0.1:8123/health`

2. 浏览器报 CORS
- 后端没放开你的前端地址
- 优先保持本地同机：前端 `8080`，后端 `8123`

3. 飞书弹窗授权后没回填
- 检查后端 `feishu/callback` 地址配置
- 检查浏览器是否拦截弹窗

4. 导入后一直“索引中”
- 后端 Celery Worker 没启动或 Redis 不通

## 推荐实践（建议）

- 将 API 错误提示统一收敛到消息组件，减少 `alert` 的使用。
- 为来源导入流程增加可视化状态机（授权中、上传中、索引中、完成/失败）。
- 增加 E2E 用例覆盖：会话创建、附件上传、飞书/Drive 导入链路。

## 命名约定（避免混淆）

本仓库存在几种容易混淆的命名，实际含义如下：

- `training_agent`（下划线）：项目目录名、Postgres 数据库名（`POSTGRES_DB`）、Celery 应用名、对象存储中文档路径。这些是**运行时实体**，请勿随意改名，否则需要连带迁移数据库与所有路径。
- `payabase-api`：后端 Python 包名（见 `training_agent/pyproject.toml` 的 `[project] name`）。
- `payabase-web`：前端 npm 包名（见 `web/package.json` 的 `name`）。`web/package-lock.json` 中残留的 `training-agent-web` 是历史快照，执行一次 `npm install` 即会自动同步为 `payabase-web`，无需手动修改锁文件（手动改反而可能让 `npm ci` 报错）。

后端 API 地址通过 `NEXT_PUBLIC_API_URL` 配置（注意不是 `NEXT_PUBLIC_API_BASE_URL`）。本地开发时后端由 `uvicorn` 在 `127.0.0.1:8123` 启动，不在 docker-compose 网络内，因此**不可用 docker 服务名（如 `training_agent:8123`）访问后端**。
