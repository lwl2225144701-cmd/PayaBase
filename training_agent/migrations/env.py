"""Alembic 环境(同步 DDL; 词法索引 migration 仅用 op.execute, 无需 ORM 在线元数据)。

URL 注入顺序:
1. 环境变量 ALEMBIC_DB_URL(集成测试指向独立测试库);
2. 否则 core.config.settings.sync_database_url(来自 .env)。
"""
import contextlib
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import models.tables  # noqa: F401  确保 ORM 元数据已注册
from core.config import settings

config = context.config

# 注入数据库连接 URL(允许测试覆盖)
db_url = os.environ.get("ALEMBIC_DB_URL") or settings.sync_database_url
config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    with contextlib.suppress(Exception):
        fileConfig(config.config_file_name)

target_metadata = models.tables.Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
