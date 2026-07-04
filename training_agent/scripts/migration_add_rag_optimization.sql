-- 添加新字段支持优化后的RAG策略
-- summary: 摘要化处理
-- hypothetical_questions: HyDE假设性问题
-- chunk_type: 分块策略类型

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS summary VARCHAR(500);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS hypothetical_questions JSONB DEFAULT '[]';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(50) DEFAULT 'recursive';

-- 创建索引优化查询
CREATE INDEX IF NOT EXISTS idx_chunks_summary ON chunks(summary) WHERE summary IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type ON chunks(chunk_type);