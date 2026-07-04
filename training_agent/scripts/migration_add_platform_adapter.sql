-- Platform adapter support tables

CREATE TABLE IF NOT EXISTS platform_users (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id UUID NOT NULL REFERENCES users(id),
  platform VARCHAR(50) NOT NULL,
  platform_user_id VARCHAR(255) NOT NULL,
  display_name VARCHAR(255),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_platform_user UNIQUE (platform, platform_user_id)
);

CREATE TABLE IF NOT EXISTS platform_conversations (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id UUID NOT NULL REFERENCES users(id),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  platform VARCHAR(50) NOT NULL,
  platform_conversation_id VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_platform_conversation UNIQUE (platform, platform_conversation_id)
);

CREATE TABLE IF NOT EXISTS platform_message_receipts (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id UUID NOT NULL REFERENCES users(id),
  platform VARCHAR(50) NOT NULL,
  platform_message_id VARCHAR(255) NOT NULL,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_platform_message UNIQUE (platform, platform_message_id)
);
