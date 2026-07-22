"""fix cascade foreign keys on documents.knowledge_base_id and chunks.document_id

旧库(早期代码)中 documents.knowledge_base_id → knowledge_bases.id 与
chunks.document_id → documents.id 的外键未带 ON DELETE CASCADE, 删除 KB / Document
时无法级联清理子表。

本 migration:
- 先探测现有外键(可能是 SQLAlchemy 自动生成的任意名称), 若存在则 DROP;
- 再以**显式命名**的约束重建为 ON DELETE CASCADE 外键。

upgrade / downgrade 均可执行: downgrade 还原为非级联外键(rollback 语义),
保证可重复运行(幂等)且可回滚。

依赖 0001_chunk_lexical(父表 documents / chunks / knowledge_bases 必须已存在,
由 create_all 或早期 migration 建好)。

Revision ID: 0002_fix_cascade_fks
Revises: 0001_chunk_lexical
Create Date: 2026-07-22
"""
from alembic import op
from sqlalchemy import text

revision = "0002_fix_cascade_fks"
down_revision = "0001_chunk_lexical"
branch_labels = None
depends_on = None

# (表, 列, 引用表, 引用列, 级联约束名, 非级联约束名)
# 表名/列名/约束名均为内部常量(非用户输入), 直接拼接到 ALTER 语句安全。
_FK_SPECS = [
    (
        "documents", "knowledge_base_id", "knowledge_bases", "id",
        "fk_documents_knowledge_base_id_cascade",
        "fk_documents_knowledge_base_id_nocascade",
    ),
    (
        "chunks", "document_id", "documents", "id",
        "fk_chunks_document_id_cascade",
        "fk_chunks_document_id_nocascade",
    ),
]


def _find_fk(bind, table, column, ref_table, ref_column):
    """返回 (约束名, delete_rule) 或 (None, None)。

    通过 information_schema 探测外键(不依赖已知约束名), 兼容旧库自动命名。
    """
    row = bind.execute(
        text(
            """
            SELECT tc.constraint_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
             AND rc.constraint_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = :table
              AND kcu.column_name = :column
              AND ccu.table_name = :ref_table
              AND ccu.column_name = :ref_column
            """
        ),
        {"table": table, "column": column, "ref_table": ref_table, "ref_column": ref_column},
    ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def _ensure_cascade_fk(bind, spec):
    table, column, ref_table, ref_column, cascade_name, _nocascade_name = spec
    name, rule = _find_fk(bind, table, column, ref_table, ref_column)
    if name == cascade_name and rule == "CASCADE":
        return  # 已是目标级联 FK, 幂等 no-op
    if name is not None:
        bind.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
    bind.execute(
        text(
            f'ALTER TABLE {table} ADD CONSTRAINT "{cascade_name}" '
            f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) ON DELETE CASCADE"
        )
    )


def _ensure_nocascade_fk(bind, spec):
    table, column, ref_table, ref_column, _cascade_name, nocascade_name = spec
    name, rule = _find_fk(bind, table, column, ref_table, ref_column)
    if name == nocascade_name and (rule is None or rule == "NO ACTION"):
        return  # 已是目标非级联 FK, 幂等 no-op
    if name is not None:
        bind.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
    bind.execute(
        text(
            f'ALTER TABLE {table} ADD CONSTRAINT "{nocascade_name}" '
            f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column})"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    for spec in _FK_SPECS:
        _ensure_cascade_fk(bind, spec)


def downgrade() -> None:
    bind = op.get_bind()
    for spec in _FK_SPECS:
        _ensure_nocascade_fk(bind, spec)
