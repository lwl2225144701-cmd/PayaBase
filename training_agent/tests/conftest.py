"""PayaBase 测试基础设施（Phase 0 起步）。

当前仅搭建 pytest 运行骨架；后续 DDD 阶段在此注入：
- Fake/内存版 Repository 与端口实现（MinIO/Redis/LLM 等），使领域测试不依赖真服务；
- 测试用 AsyncSession（内存 SQLite 或事务回滚夹具），支撑 Repository 单测；
- 组合根覆盖（override api/deps 的装配），支撑接口层集成测试。
"""

import pytest


@pytest.fixture
def anyio_backend():
    """pytest-asyncio 的 auto 模式下无需显式声明；此夹具预留给未来 anyio 场景。"""
    return "asyncio"
