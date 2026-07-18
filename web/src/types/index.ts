export interface User {
  id: string;
  name: string;
  email: string;
  tenant_id: string;
  department_id?: string;
  department_name?: string;
  role: "admin" | "training_admin" | "user" | string;
  is_super_admin?: boolean;
  is_training_admin?: boolean;
  can_manage_knowledge_bases?: boolean;
}

export interface Department {
  id: string;
  name: string;
  code: string;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description?: string;
  department_id?: string;
  department_name?: string;
  doc_count: number;
  can_manage?: boolean;
  created_at: string;
}

export interface Document {
  id: string;
  knowledge_base_id: string;
  title: string;
  file_type: string;
  file_size: number;
  status: "pending" | "indexing" | "ready" | "error";
  indexed_at?: string;
  created_at: string;
  chunk_count?: number;
  strategy?: string;
}

export interface DocumentDetail extends Document {
  chunk_count: number;
  strategy: string;
}

export type ChunkVectorStatus = "indexed" | "error" | "pending";

export interface Chunk {
  id: string;
  chunk_id: string;
  document_id: string;
  section_title?: string | null;
  page_number?: number | null;
  start_offset?: number | null;
  end_offset?: number | null;
  token_count?: number | null;
  character_count?: number | null;
  vector_status: ChunkVectorStatus;
  embedding_model?: string | null;
  created_at?: string;
  content: string;
}

export interface ChunkListResponse {
  items: Chunk[];
  total: number;
  page: number;
  page_size: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Array<{ doc_id: string; title: string }>;
  token_count?: number;
  latency_ms?: number;
  created_at: string;
  attachment?: { name: string; type: string };
}

export interface Conversation {
  id: string;
  title: string;
  knowledge_base_id?: string;
  message_count: number;
  created_at: string;
}

export interface Stats {
  total_conversations: number;
  total_messages: number;
  total_queries: number;
  avg_latency_ms: number;
}

export interface TopQuery {
  query: string;
  count: number;
  avg_latency_ms: number;
}
