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


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """明确报告 PostgreSQL 集成测试(pg_integration marker)的实际执行情况。

    防静默证明通过: 若本地 PG 不可用导致全部 skip, 必须醒目提示, 不得把
    普通单测通过描述成 PG 集成已通过。
    """
    marker = "pg_integration"
    outcomes = ("passed", "failed", "skipped", "error", "xfailed", "xpassed")
    statuses = []
    for outcome in outcomes:
        for rep in terminalreporter.stats.get(outcome, []):
            if marker in getattr(rep, "keywords", {}):
                statuses.append(outcome)
    if not statuses:
        return
    total = len(statuses)
    passed = statuses.count("passed")
    failed = statuses.count("failed") + statuses.count("error")
    skipped = statuses.count("skipped")
    terminalreporter.write_sep("=", "PostgreSQL 集成测试报告 (marker: pg_integration)", bold=True)
    terminalreporter.write_line(
        f"收集 {total} 项 | 实际执行通过 {passed} | 失败 {failed} | 跳过 {skipped}"
    )
    if skipped and passed == 0:
        terminalreporter.write_line(
            "⚠️ 所有 PG 集成测试均被 SKIP(本地 PostgreSQL 不可用), 未真正执行, "
            "不得视为 PG 集成已通过!",
            red=True,
        )
    elif skipped:
        terminalreporter.write_line(
            f"⚠️ 有 {skipped} 项 PG 集成测试被 SKIP(本地 PG 不可用), 仅 {passed} 项真实执行。",
            yellow=True,
        )

