"""Phase 0 冒烟测试：验证 pytest / pytest-asyncio 运行骨架可用。

真正的领域/仓储单测在 Phase 1+ 落地（届时经 Fake 客户端与测试用 AsyncSession，
不依赖真实数据库与外部服务）。本文件仅作为回归护栏的「点燃」测试。
"""


def test_harness_runs():
    assert 1 + 1 == 2


async def test_async_harness_runs():
    # 验证 pytest-asyncio（asyncio_mode=auto）能驱动异步用例
    assert True


def test_config_module_imports():
    # 验证核心配置模块可无错误导入（捕获 ImportError / 循环依赖等导入期断裂）
    from core.config import settings

    assert settings is not None
