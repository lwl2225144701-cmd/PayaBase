-- Align chunks.vector with vector-service bge-small-zh-v1.5 output (512 dims).
-- Existing vectors with another dimension are cleared and should be rebuilt by reindexing documents.

CREATE EXTENSION IF NOT EXISTS vector;

DROP INDEX IF EXISTS idx_chunks_vector;

ALTER TABLE chunks
    ALTER COLUMN vector TYPE vector(512)
    USING NULL;

UPDATE documents
SET status = 'pending',
    progress = 0,
    chunk_count = 0,
    indexed_at = NULL
WHERE id IN (
    SELECT DISTINCT document_id
    FROM chunks
);

DELETE FROM chunks;

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_kb_status ON documents(knowledge_base_id, status);
CREATE INDEX IF NOT EXISTS idx_chunks_vector ON chunks USING hnsw (vector vector_cosine_ops);
