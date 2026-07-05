const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === "true";

const MOCK_KBS = [
  { id: "1", name: "公司规章制度", description: "员工手册、考勤制度、报销流程", doc_count: 12, department_name: "公共", can_manage: true },
  { id: "2", name: "产品培训资料", description: "产品功能介绍、销售话术", doc_count: 8, department_name: "销售部", can_manage: true },
  { id: "3", name: "技术文档", description: "API文档、部署指南", doc_count: 5, department_name: "技术部", can_manage: false },
];

const MOCK_DEPARTMENTS = [
  { id: "sales", name: "销售部", code: "SALES" },
  { id: "tech", name: "技术部", code: "TECH" },
];

const MOCK_STATS = {
  total_conversations: 156,
  total_messages: 1234,
  total_queries: 2345,
  avg_latency_ms: 1234,
};

const MOCK_TOP_QUERIES = [
  { query: "如何报销差旅费", count: 45, avg_latency_ms: 1100 },
  { query: "年假申请流程", count: 38, avg_latency_ms: 980 },
  { query: "产品价格", count: 32, avg_latency_ms: 1200 },
  { query: "试用期考核", count: 28, avg_latency_ms: 1050 },
  { query: "社保缴纳", count: 25, avg_latency_ms: 1300 },
];

interface ApiResponse<T> {
  code: number;
  data: T;
  msg: string;
}

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== "undefined") {
      localStorage.setItem("token", token);
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== "undefined") {
      return localStorage.getItem("token");
    }
    return null;
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('token');
      localStorage.removeItem('userRole');
      localStorage.removeItem('currentUser');
    }
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    };

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ msg: "请求失败" }));
      throw new Error(error.msg || "请求失败");
    }

    return response.json();
  }

  async login(code: string) {
    const res = await this.request<ApiResponse<{ access_token: string; token_type: string; expires_in: number }>>(
      `/api/auth/sso?code=${code}`
    );
    this.setToken(res.data.access_token);
    
    // 登录成功后获取并缓存用户信息
    try {
      const userRes = await this.getCurrentUser();
      if (typeof window !== 'undefined') {
        localStorage.setItem('userRole', userRes.role || 'user');
      }
    } catch (e) {
      console.error('获取用户信息失败', e);
    }
    
    return res.data;
  }

  async getMe() {
    return this.request<any>("/api/auth/me");
  }

  // Knowledge Bases
  async getKnowledgeBases() {
    if (MOCK_MODE) return MOCK_KBS;
    const res = await this.request<{ code: number; data: any[] }>("/api/kb");
    return res.data;
  }

  async getDepartments() {
    if (MOCK_MODE) return MOCK_DEPARTMENTS;
    const res = await this.request<{ code: number; data: any[] }>("/api/departments");
    return res.data;
  }

  async getKnowledgeBase(id: string) {
    if (MOCK_MODE) return MOCK_KBS.find((k) => k.id === id);
    const res = await this.request<{ code: number; data: any }>(`/api/kb/${id}`);
    return res.data;
  }

  async createKnowledgeBase(data: {
    name: string;
    description: string;
    department_id?: string;
  }) {
    if (MOCK_MODE) return { id: String(Date.now()), ...data };
    return this.request("/api/kb", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateKnowledgeBase(
    id: string,
    data: { name?: string; description?: string }
  ) {
    if (MOCK_MODE) return { id, ...data };
    return this.request(`/api/kb/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async deleteKnowledgeBase(id: string) {
    if (MOCK_MODE) return { id };
    return this.request(`/api/kb/${id}`, { method: "DELETE" });
  }

  // Documents
  async getDocuments(kbId: string) {
    if (MOCK_MODE)
      return [
        { id: "1", title: "员工手册.pdf", status: "ready" },
        { id: "2", title: "考勤制度.docx", status: "ready" },
      ];
    const res = await this.request<{ code: number; data: any[] }>(`/api/kb/${kbId}/docs`);
    return res.data;
  }

  /**
   * 文档分页查询 (服务端分页)
   * @param kbId 知识库 ID
   * @param params { page, pageSize, q?, status?, sort? }
   * @returns DocumentPageResponse { items, total, page, page_size, counts? }
   */
  async getDocumentsPage(
    kbId: string,
    params: { page: number; pageSize: number; q?: string; status?: string; sort?: string }
  ) {
    if (MOCK_MODE) {
      // MOCK 模式: 模拟一页 5 条, 让前端能正常跑分页逻辑
      const all = [
        { id: "1", title: "员工手册.pdf", file_type: "pdf", file_size: 102400, status: "ready", chunk_count: 0, created_at: "2026-07-01T10:00:00Z" },
        { id: "2", title: "考勤制度.docx", file_type: "docx", file_size: 51200, status: "ready", chunk_count: 0, created_at: "2026-07-02T10:00:00Z" },
        { id: "3", title: "产品白皮书.md", file_type: "md", file_size: 25600, status: "indexing", chunk_count: 0, created_at: "2026-07-03T10:00:00Z" },
        { id: "4", title: "销售话术.txt", file_type: "txt", file_size: 8192, status: "pending", chunk_count: 0, created_at: "2026-07-04T10:00:00Z" },
        { id: "5", title: "财务手册.pdf", file_type: "pdf", file_size: 204800, status: "error", chunk_count: 0, created_at: "2026-07-05T10:00:00Z" },
      ];
      const page = Math.max(1, params.page);
      const pageSize = params.pageSize;
      const start = (page - 1) * pageSize;
      const items = all.slice(start, start + pageSize);
      return {
        items,
        total: all.length,
        page,
        page_size: pageSize,
        counts: { all: all.length, ready: 2, indexing: 2, error: 1 },
      };
    }
    const query = new URLSearchParams();
    query.set("with_total", "true");
    query.set("page", String(params.page));
    query.set("page_size", String(params.pageSize));
    if (params.q) query.set("q", params.q);
    if (params.status) query.set("status", params.status);
    if (params.sort) query.set("sort", params.sort);
    const res = await this.request<{
      code: number;
      data: {
        items: any[];
        total: number;
        page: number;
        page_size: number;
        counts?: { all: number; ready: number; indexing: number; error: number };
      };
    }>(`/api/kb/${kbId}/docs?${query.toString()}`);
    return res.data;
  }

  async uploadDocument(kbId: string, file: File) {
    if (MOCK_MODE) {
      return { id: String(Date.now()), title: file.name, status: "pending" };
    }
    const token = this.getToken();
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_BASE}/api/kb/${kbId}/docs`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });

    const result = await response.json().catch(() => ({ msg: "请求失败" }));
    if (!response.ok || result.code !== 0) {
      throw new Error(result.msg || "上传失败");
    }
    return result.data;
  }

  async deleteDocument(kbId: string, docId: string) {
    return this.request(`/api/kb/${kbId}/docs/${docId}`, {
      method: "DELETE",
    });
  }

  async reindexDocument(kbId: string, docId: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/kb/${kbId}/docs/${docId}/reindex`, {
      method: "POST",
    });
    return res;
  }

  async getIndexingStatus(kbId: string, docId: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/kb/${kbId}/docs/${docId}/indexing-status`);
    return res.data;
  }

  // Sources
  async getFeishuLoginUrl(redirectUri?: string) {
    const query = new URLSearchParams();
    if (redirectUri) query.set("redirect_uri", redirectUri);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const res = await this.request<{ code: number; data: { auth_url: string } }>(`/api/sources/feishu/login${suffix}`);
    return res.data;
  }

  async previewGoogleDrive(url: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/sources/google-drive/preview`, {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    return res.data;
  }

  async getFeishuFiles(accessToken: string, pageSize = 50) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/sources/feishu/files`, {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken, page_size: pageSize }),
    });
    return res.data;
  }

  async uploadSourceToKb(data: {
    kb_id: string;
    source_type: "feishu" | "google_drive";
    source_data: Record<string, any>;
    title?: string;
  }) {
    const res = await this.request<{ code: number; data: any; msg: string }>(`/api/sources/upload-to-kb`, {
      method: "POST",
      body: JSON.stringify(data),
    });
    return res.data;
  }

  // User
  async getCurrentUser() {
    const res = await this.request<{ code: number; data: any }>("/api/auth/me");
    return res.data;
  }

  async getConversations() {
    const res = await this.request<{ code: number; data: any[] }>("/api/conversations");
    return res.data;
  }

  async createConversation(data: { title?: string; knowledge_base_id?: string }) {
    const res = await this.request<{ code: number; data: { id: string } }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return res.data;
  }

  async getConversation(id: string) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/conversations/${id}`);
    return res.data;
  }

  async getAgentRun(runId: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/agent/runs/${runId}`);
    return res.data;
  }

  async getAgentRunSteps(runId: string) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/agent/runs/${runId}/steps`);
    return res.data;
  }

  // Streaming Chat (SSE)
  async *chatStream(conversationId: string, query: string, knowledgeBaseId?: string, webSearch?: boolean) {
    const token = this.getToken();
    const body: any = { message: query };
    if (knowledgeBaseId) {
      body.knowledge_base_id = knowledgeBaseId;
    }
    if (webSearch !== undefined) {
      body.web_search = webSearch;
    }
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/chat`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      }
    );

    const reader = response.body?.getReader();
    if (!reader) throw new Error("无法读取响应");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6);
          if (data === "[DONE]") return;
          try {
            yield JSON.parse(data);
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  }

  // Streaming Chat with file attachments (SSE via multipart/form-data)
  async *chatStreamWithFiles(
    conversationId: string,
    message: string,
    files: File[],
    knowledgeBaseId?: string,
    webSearch?: boolean
  ) {
    const token = this.getToken();
    const formData = new FormData();
    formData.append("message", message);
    if (knowledgeBaseId) {
      formData.append("knowledge_base_id", knowledgeBaseId);
    }
    if (webSearch !== undefined) {
      formData.append("web_search", webSearch ? "true" : "false");
    }
    for (const file of files) {
      formData.append("files", file);
    }

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/chat/upload`,
      {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({ msg: "请求失败" }));
      throw new Error(error.msg || "请求失败");
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("无法读取响应");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6);
          if (data === "[DONE]") return;
          try {
            yield JSON.parse(data);
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  }

// PPT
  async getPptStatus(taskId: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/ppt/${taskId}/status`);
    return res.data;
  }

  async downloadPpt(taskId: string, filename: string) {
    const token = this.getToken();
    const response = await fetch(`${API_BASE}/api/ppt/${taskId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error("下载失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

// PDF
  async getPdfStatus(taskId: string) {
    const res = await this.request<{ code: number; data: any }>(`/api/pdf/${taskId}/status`);
    return res.data;
  }

  async downloadPdf(taskId: string, filename: string) {
    const token = this.getToken();
    const response = await fetch(`${API_BASE}/api/pdf/${taskId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error("下载失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

// Stats
  async getStats() {
    const res = await this.request<{ code: number; data: any }>("/api/stats/usage");
    return res.data;
  }

  async getTopQueries() {
    const res = await this.request<{ code: number; data: any[] }>("/api/stats/queries");
    return res.data;
  }

  async getQueryTrend(days: number = 7) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/stats/trend?days=${days}`);
    return res.data;
  }

  async getAgentMetrics(days: number = 7) {
    const res = await this.request<{ code: number; data: any }>(`/api/stats/agent?days=${days}`);
    return res.data;
  }

  async getAgentTrend(days: number = 7) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/stats/agent/trend?days=${days}`);
    return res.data;
  }

  async getSearchMetrics() {
    const res = await this.request<{ code: number; data: any }>(`/api/stats/search`);
    return res.data;
  }

  async getSearchTrend(days: number = 7) {
    const res = await this.request<{ code: number; data: any[] }>(`/api/stats/search/trend?days=${days}`);
    return res.data;
  }
}

export const api = new ApiClient();
