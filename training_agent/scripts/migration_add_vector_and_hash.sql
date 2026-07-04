-- RAG索引系统数据库迁移脚本
-- 运行方式: psql -h localhost -U training -d training_agent -f migration_add_vector_and_hash.sql

-- 1. 添加file_hash字段到documents表
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;

-- 2. 创建file_hash索引（用于幂等性检查）
CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash) WHERE file_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

-- 3. 确保pgvector扩展已安装
CREATE EXTENSION IF NOT EXISTS vector;

-- 4. 修改chunks表的vector列为pgvector类型（如果有数据先迁移）
DO $$
BEGIN
    -- 检查vector列当前类型
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chunks' AND column_name = 'vector' 
        AND data_type = 'character varying'
    ) THEN
        -- 迁移TEXT格式向量到pgvector格式
        ALTER TABLE chunks ALTER COLUMN vector TYPE vector(512) USING vector::vector;
    END IF;
EXCEPTION WHEN undefined_column THEN
    -- 向量列不存在或已是正确类型
    NULL;
END
$$;

-- 5. 创建向量索引（用于相似度检索）
DROP INDEX IF EXISTS idx_chunks_vector;
CREATE INDEX idx_chunks_vector ON chunks USING hnsw (vector vector_cosine_ops);

-- 6. 创建chunk_count索引
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

-- 7. 添加状态索引（用于查询特定状态的文档）
CREATE INDEX IF NOT EXISTS idx_documents_kb_status ON documents(knowledge_base_id, status);

-- 8. 添加进度索引（用于显示索引进度）
CREATE INDEX IF NOT EXISTS idx_documents_progress ON documents(progress) WHERE progress IS NOT NULL;

-- 验证迁移结果
SELECT 
    'documents' as table_name,
    COUNT(*) as total_rows,
    SUM(CASE WHEN file_hash IS NOT NULL THEN 1 ELSE 0 END) as with_file_hash,
    SUM(CASE WHEN progress > 0 THEN 1 ELSE 0 END) as with_progress
FROM documents
UNION ALL
SELECT 
    'chunks' as table_name,
    COUNT(*) as total_rows,
    SUM(CASE WHEN vector IS NOT NULL THEN 1 ELSE 0 END) as with_vector,
    NULL as with_progress
FROM chunks;

-- 查看索引
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename IN ('documents', 'chunks');
