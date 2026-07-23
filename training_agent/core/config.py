from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL (vector search)
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "training"
    postgres_password: str = "xxx"
    postgres_db: str = "training_agent"

    # MySQL (user registration, document metadata)
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_user: str = "training"
    mysql_password: str = "xxx"
    mysql_db: str = "training_agent"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "xxx"
    minio_secret_key: str = "xxx"
    minio_bucket: str = "training-docs"

    # SSO
    sso_client_id: str = "xxx"
    sso_client_secret: str = "xxx"
    sso_redirect_uri: str = "xxx"

    # Feishu/Lark
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_oauth_scope: str = "authen:read_user_info"
    feishu_oauth_redirect_uri: str = ""

    # HR API
    hr_api_url: str = "http://hr-api:8080"
    hr_api_key: str = "xxx"

    # JWT
    jwt_secret: str = "xxx"
    jwt_expire_minutes: int = 1440

    # Vector Service
    vector_service_url: str = "http://localhost:8001"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM
    llm_provider: str = "openai"
    llm_api_key: str = "xxx"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4"

    # Rerank
    rerank_service_url: str = "http://rerank-service:8003"
    rerank_override: str = "auto"  # auto|on|off
    rerank_candidate_k: int = 20  # Rerank 仅处理 RRF TopN(从 RRF 候选 Top30 中取前 20)
    rerank_cache_ttl_sec: int = 120
    rerank_policy_version: str = "v1"
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_gap_threshold: float = 0.03
    rerank_query_len_threshold: int = 8

    # RRF 融合 (标准 Reciprocal Rank Fusion: RRF = sum(1/(k+rank)), 仅用排名)
    rrf_k: int = 60

    # 词法索引(第三阶段: 独立全库 BM25 召回)
    lexical_index_version: str = "v1"
    lexical_max_terms_per_chunk: int = 2000
    lexical_max_text_length: int = 200000

    # 标准 BM25 全库 SQL 召回
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    bm25_max_query_terms: int = 32
    vector_recall_top_k: int = 40
    bm25_recall_top_k: int = 40
    rrf_candidate_top_k: int = 30

    # 检索结果后处理
    # 同文档结果数量上限: 每个 document_id 在最终结果中最多保留 N 条; 0 = 不限制。
    # 默认 3(候选仅含一个有效 document_id 时自动跳过限制, 见 retriever._post_process_results)。
    max_results_per_doc: int = 3
    # 内容去重的最小正文长度: 正文长度 < 该值时只按 chunk_id 去重, 避免短噪声误并。
    dedup_min_content_length: int = 50

    # Search (OpenSERP)
    search_service_url: str = "http://localhost:8004"
    search_default_engine: str = "baidu"
    search_default_limit: int = 5
    search_timeout_sec: int = 20
    search_cache_ttl_sec: int = 180
    search_failure_threshold: int = 3
    search_failure_cooldown_sec: int = 60
    search_fallback_engine: str = "bing"

    # PPT Generation
    ppt_minio_bucket: str = "ppt-files"

    # PDF Generation
    pdf_minio_bucket: str = "pdf-files"

    # Agent 请求路由关键词（注入领域层 RequestRoutingService，支持配置化/热更新）
    # 否定词：命中后整体抑制「生成类」路由（如「不要生成 PDF」不应路由到 pdf_generation）
    route_pdf_keywords: tuple[str, ...] = (
        "pdf", "PDF", "导出pdf", "导出 PDF", "生成pdf", "生成 PDF",
        "输出pdf", "输出 PDF", "下载pdf", "下载 PDF",
    )
    route_ppt_keywords: tuple[str, ...] = (
        "ppt", "PPT", "课件", "演示文稿", "汇报页", "幻灯片",
    )
    route_summary_keywords: tuple[str, ...] = (
        "总结", "概括", "摘要", "提炼", "梳理", "归纳", "总结一下", "概述",
    )
    route_generation_keywords: tuple[str, ...] = (
        "生成", "起草", "撰写", "写一份", "帮我写", "输出一份", "拟一份", "草案", "方案",
    )
    route_rag_hint_keywords: tuple[str, ...] = (
        "什么是", "如何", "怎么", "流程", "制度", "规范", "文档", "资料",
        "知识库", "附件", "在哪", "谁", "多久", "要求", "规则", "说明",
    )
    route_fallback_keywords: tuple[str, ...] = (
        "你好", "hi", "hello", "早上好", "晚上好", "谢谢", "thank", "在吗",
    )
    route_negation_keywords: tuple[str, ...] = (
        "不要生成", "不需要生成", "不要输出", "别生成", "不要做PPT",
        "不要做pdf", "无需生成", "不需要PDF", "不需要PPT",
    )

    # Indexing
    index_md_chunk_size: int = 800
    index_image_chunk_size: int = 500
    index_word_chunk_size: int = 700
    index_chunk_overlap: int = 100
    index_enable_image_vision: bool = True

    # HyDE (查询时假设性文档嵌入)
    # 索引期不再逐 chunk 调 LLM;改为查询时对用户 query 生成假设文档再检索,
    # 把 LLM 成本从「每 chunk」降到「每查询」。
    hyde_enabled: bool = True
    hyde_alpha: float = 0.5  # query 向量与 hyde 向量的混合权重 (1=纯query, 0=纯hyde)
    hyde_timeout: float = 30.0

    # Phase 4: 父子块上下文 + 相邻 Chunk 扩展
    context_expansion_enabled: bool = True
    context_parent_enabled: bool = True
    context_adjacent_window: int = 1
    context_parent_target_tokens: int = 1400
    context_parent_max_tokens: int = 1800
    context_parent_min_children: int = 4
    context_parent_max_children: int = 8
    context_max_chars_per_result: int = 6000
    context_total_max_chars: int = 24000
    context_version: str = "v1"

    # Agent
    max_iterations: int = 5
    memory_limit: int = 10
    chat_request_concurrency: int = 4
    attachment_parse_concurrency: int = 2

    # Attachment
    max_attachment_size: int = 10 * 1024 * 1024  # 10MB
    llm_vision_model: str = ""  # Vision 模型,必须显式配置,不自动复用 llm_model
    llm_vision_api_key: str = ""  # vision model API key (fallback to llm_api_key)
    llm_vision_base_url: str = ""  # vision model base URL (fallback to llm_base_url)
    temp_attachment_prefix: str = "temp_attachments"

    # Intent classification model (lightweight, fast)
    llm_classify_model: str = ""  # fallback to llm_model
    llm_classify_api_key: str = ""  # fallback to llm_api_key
    llm_classify_base_url: str = ""  # fallback to llm_base_url

    # Chat generation model (high quality)
    llm_chat_model: str = ""  # fallback to llm_model
    llm_chat_api_key: str = ""  # fallback to llm_api_key
    llm_chat_base_url: str = ""  # fallback to llm_base_url
    llm_chat_api_header_name: str = ""
    llm_chat_api_header_prefix: str = "Bearer "

    # === Provider 维度的扩展(配置化生成模型) ===
    # 默认 provider 仍沿用 llm_provider,这里仅按用途覆盖;留空 = 跟随 llm_provider
    llm_classify_provider: str = ""
    llm_chat_provider: str = ""
    llm_vision_provider: str = ""

    # === 各用途超时(秒) ===
    llm_default_timeout: float = 30.0
    llm_chat_timeout: float = 90.0
    llm_classify_timeout: int = 30
    llm_vision_timeout: float = 90.0

    # SQLAlchemy pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def sync_database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def mysql_url(self) -> str:
        return f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"

    @property
    def sync_mysql_url(self) -> str:
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"


settings = Settings()
