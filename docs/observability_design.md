# 可观测性系统设计方案

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        可观测性架构                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │   API      │    │  Celery     │    │ Vector/     │              │
│  │   Server   │    │  Workers   │    │ Rerank     │              │
│  └─────┬─────┘    └─────┬─────┘    └─────┬─────┘              │
│        │                │               │                          │
│        ▼                ▼               ▼                          │
│  ┌─────────────────────────────────────────────┐                 │
│  │           Python logging (结构化)               │                 │
│  │      + prometheus-client (指标导出)            │                 │
│  └──────────────────┬──────────────────────┘                 │
│                     │                                           │
│                     ▼                                           │
│  ┌─────────────────────────────────────────────┐                 │
│  │           Prometheus (时序数据库)            │◄─── pull      │
│  └──────────────────┬──────────────────────┘                 │
│                     │                                           │
│                     ▼                                           │
│  ┌─────────────────────────────────────────────┐                 │
│  │           Grafana (可视化)                 │                 │
│  └──────────────────┬──────────────────────┘                 │
│                     │                                           │
│                     ▼                                           │
│  ┌─────────────────────────────────────────────┐                 │
│  │        AlertManager (告警通知)              │                 │
│  └─────────────────────────────────────────────┘                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 二、监控指标清单

| 模块 | 指标名称 | 类型 | 说明 |
|------|----------|------|------|
| **API** | `api_requests_total` | Counter | 请求总数 |
| | `api_requests_duration_seconds` | Histogram | 请求延迟 |
| | `api_requests_active` | Gauge | 活跃请求数 |
| | `api_errors_total` | Counter | 错误总数 |
| **Chat** | `chat_conversations_total` | Counter | 会话数 |
| | `chat_messages_total` | Counter | 消息数 |
| | `chat_stream_duration_seconds` | Histogram | 流式响应延迟 |
| | `chat_rag_retrieval_duration_seconds` | Histogram | RAG检索延迟 |
| | `chat_rag_chunks_retrieved` | Histogram | 检索chunk数 |
| **Docs** | `docs_upload_total` | Counter | 上传文档数 |
| | `docs_indexing_duration_seconds` | Histogram | 索引耗时 |
| | `docs_indexing_errors_total` | Counter | 索引失败数 |
| | `docs_upload_size_bytes` | Histogram | 文档大小 |
| **KB** | `kb_documents_total` | Gauge | 知识库文档数 |
| | `kb_chunks_total` | Gauge | 知识库chunk数 |
| | `kb_vector_storage_bytes` | Gauge | 向量存储大小 |
| **Celery** | `celery_workers_active` | Gauge | 活跃worker数 |
| | `celery_tasks_queued` | Gauge | 队列任务数 |
| | `celery_task_duration_seconds` | Histogram | 任务执行时间 |
| | `celery_task_retries_total` | Counter | 任务重试次数 |
| | `celery_task_failures_total` | Counter | 任务失败数 |
| **LLM** | `llm_api_calls_total` | Counter | API调用次数 |
| | `llm_api_duration_seconds` | Histogram | API调用延迟 |
| | `llm_api_errors_total` | Counter | API错误数 |
| | `llm_tokens_total` | Counter | token消耗数 |
| **Vector** | `vector_service_duration_seconds` | Histogram | 向量化耗时 |
| | `vector_service_errors_total` | Counter | 向量化错误数 |
| **Rerank** | `rerank_service_duration_seconds` | Histogram | 重排序耗时 |
| | `rerank_service_errors_total` | Counter | 重排序错误数 |

## 三、结构化日志设计

```python
# 日志格式 JSON
{
    "timestamp": "2026-04-23T12:00:00.000Z",
    "level": "INFO",
    "trace_id": "abc123",
    "span_id": "span_456",
    "service": "training-agent-api",
    "environment": "production",
    "version": "0.1.0",
    "module": "api.routers.chat",
    "function": "stream_chat",
    "message": "Chat request received",
    "context": {
        "user_id": "user_123",
        "tenant_id": "tenant_456",
        "conversation_id": "conv_789"
    },
    "metrics": {
        "retrieval_time_ms": 150,
        "llm_time_ms": 500
    }
}
```

## 四、代码实现设计

### 4.1 新增依赖

```toml
# pyproject.toml
dependencies = [
    # 日志
    "python-json-logger>=2.0.0",
    # Prometheus
    "prometheus-client>=0.19.0",
    # Celery监控
    "flower>=2.0.0",
]
```

### 4.2 目录结构

```
training_agent/
├── core/
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── base.py           # 指标定义基类
│   │   ├── api.py            # API指标
│   │   ├── chat.py           # Chat指标
│   │   ├── docs.py           # 文档指标
│   │   ├── celery.py         # Celery指标
│   │   └── llm.py           # LLM指标
│   └── logging/
│       ├── __init__.py
│       └── json.py           # JSON日志配置
├── api/
│   └── middleware/
│       └── metrics.py        # Prometheus中间件
├── workers/
│   └── celeryconfig.py       # Celery配置+监控
```

## 五、Grafana 仪表板设计

### 5.1 API 监控面板

| 图表 | 指标 | 类型 |
|------|------|------|
| 请求 QPS | `rate(api_requests_total[1m])` | Graph |
| 延迟 P50/P95/P99 | `histogram_quantile` | Graph |
| 错误率 | `api_errors_total / api_requests_total` | Graph |
| 各端点请求量 | `api_requests_total by (path)` | Table |

### 5.2 文档索引面板

| 图表 | 指标 | 类型 |
|------|------|------|
| 索引队列 | `celery_tasks_queued` | Stat |
| 平均索引时间 | `histogram_quantile(0.5, docs_indexing_duration_seconds)` | Graph |
| 索引成功率 | `(docs_upload_total - docs_indexing_errors_total) / docs_upload_total` | Gauge |
| 各文档耗时 | `docs_indexing_duration_seconds` | Heatmap |

### 5.3 系统面板

| 图表 | 指标 | 类型 |
|------|------|------|
| Worker 状态 | `celery_workers_active` | Stat |
| 队列深度 | `celery_tasks_queued` | Graph |
| CPU/内存 | `process_*` (系统指标) | Graph |
| LLM 延迟 | `llm_api_duration_seconds` | Graph |

## 六、AlertManager 告警规则

| 告警名 | 条件 | 级别 | 说明 |
|--------|------|------|------|
| `APIErrorRateHigh` | `error_rate > 5%` 持续5m | critical | API错误率过高 |
| `IndexingFailureHigh` | `failure_rate > 10%` 持续10m | critical | 索引失败率高 |
| `CeleryWorkerDown` | `workers_active == 0` 持续2m | critical | Worker掉线 |
| `CeleryQueueBacklog` | `queue_size > 100` 持续10m | warning | 队列积压 |
| `LLMLatencyHigh` | `p99_latency > 30s` 持续5m | warning | LLM延迟高 |
| `DiskSpaceLow` | `disk_free < 10%` | critical | 磁盘空间不足 |

## 七、实现优先级

| 阶段 | 模块 | 内容 |
|------|------|------|
| **Phase 1** | 核心指标 | API请求、Celery任务、LLM调用 |
| **Phase 2** | 日志 | 结构化日志 + trace_id |
| **Phase 3** | 扩展 | Chat、文档、知识库详细指标 |
| **Phase 4** | 告警 | AlertManager规则 + 通知渠道 |