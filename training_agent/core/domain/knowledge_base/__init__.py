"""KnowledgeBase 上下文：知识库、文档与分块。

Chunk 是 KnowledgeBase ↔ Retrieval 的共享内核（Shared Kernel）：
Indexing 写、Retrieval 读，统一经 ChunkRepository 端口。
"""
