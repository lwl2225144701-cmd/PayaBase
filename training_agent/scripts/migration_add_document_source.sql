-- Add source_type and source_url columns to documents table
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) DEFAULT 'local';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2000);

-- Create oauth_tokens table for storing external service tokens
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID REFERENCES users(id),
    provider VARCHAR(50) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    token_meta JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_tokens_tenant_provider ON oauth_tokens(tenant_id, provider);
