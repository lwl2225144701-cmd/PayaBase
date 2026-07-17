"""
批量重索引「旧向量空间」文档。

背景：
  索引架构重构前（索引期逐 chunk 调 LLM 生成 summary/HyDE），文档的向量是基于
  summary 嵌入的；重构后改为对「原文」嵌入。两者向量空间不同，查询用原文向量去
  匹配旧 summary 向量会导致检索效果参差。本脚本自动找出所有仍处旧向量空间的文档
  （chunks.summary 非空），逐个投递 index_document_task 进行重索引。

  index_document_task 在入库前会先 DELETE 该文档旧 chunk（见 core/tasks/indexing.py
  的 batch_insert_chunks），因此重索引是幂等替换，不会新旧 chunk 并存。

用法（需先确保 celery-worker 已用含本修复的新镜像重建）：
  cd training_agent
  .venv/bin/python scripts/bulk_reindex_old_docs.py

依赖：.env 中的 DATABASE_URL 与 CELERY_BROKER_URL（redis，默认 localhost:6379）。
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 让脚本能 import 项目模块与 celery 任务
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def find_old_vector_docs():
    """返回所有仍处旧向量空间的文档 (summary 非空的 chunk 数 > 0)。"""
    import asyncpg

    db_url = os.getenv("DATABASE_URL") or "postgresql://training:training123@localhost:5432/training_agent"
    conn = await asyncpg.connect(db_url)
    rows = await conn.fetch(
        """
        SELECT d.id AS doc_id, d.title, d.knowledge_base_id, d.status,
               COUNT(c.id) FILTER (WHERE c.summary IS NOT NULL AND c.summary <> '') AS old_chunks
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        GROUP BY d.id, d.title, d.knowledge_base_id, d.status
        HAVING COUNT(c.id) FILTER (WHERE c.summary IS NOT NULL AND c.summary <> '') > 0
        ORDER BY d.title
        """
    )
    await conn.close()
    return rows


def enqueue(doc_id: str):
    # 延迟导入：避免在未配置 broker 时 import 失败
    from core.tasks.indexing import index_document_task

    task = index_document_task.delay(doc_id)
    return task.id


async def main():
    docs = await find_old_vector_docs()
    if not docs:
        print("没有需要重索引的旧向量文档，全部已是最新架构。")
        return

    print(f"找到 {len(docs)} 个旧向量文档，开始投递重索引任务：\n")
    ok, fail = 0, 0
    for d in docs:
        title = d["title"]
        try:
            task_id = enqueue(str(d["doc_id"]))
            ok += 1
            print(f"  [OK]   {title}\n         doc_id={d['doc_id']}  task_id={task_id}")
        except Exception as e:
            fail += 1
            print(f"  [FAIL] {title}\n         doc_id={d['doc_id']}  error={e}")

    print(f"\n投递完成：成功 {ok}，失败 {fail}。")
    print("可在 celery-worker 日志观察 [Stage*] 进度；完成后用质量检查脚本确认 summary 已清空。")


if __name__ == "__main__":
    asyncio.run(main())
