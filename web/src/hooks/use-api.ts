import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Knowledge Bases
export function useKnowledgeBases() {
  return useQuery({
    queryKey: ["knowledgeBases"],
    queryFn: () => api.getKnowledgeBases(),
  });
}

export function useKnowledgeBase(id: string) {
  return useQuery({
    queryKey: ["knowledgeBase", id],
    queryFn: () => api.getKnowledgeBase(id),
    enabled: !!id,
  });
}

export function useDepartments(enabled = true) {
  return useQuery({
    queryKey: ["departments"],
    queryFn: () => api.getDepartments(),
    enabled,
  });
}

export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description: string; department_id?: string }) =>
      api.createKnowledgeBase(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledgeBases"] });
    },
  });
}

export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledgeBases"] });
    },
  });
}

// Documents
export function useDocuments(kbId: string, options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["documents", kbId],
    queryFn: () => api.getDocuments(kbId),
    enabled: !!kbId,
    refetchInterval: options?.refetchInterval,
  });
}

/**
 * 文档分页查询 (服务端分页)
 * @param kbId 知识库 ID
 * @param params { page, pageSize, q?, status?, sort? }
 * @returns DocumentPageResponse { items, total, page, page_size, counts? }
 */
export function useDocumentsPage(
  kbId: string,
  params: { page: number; pageSize: number; q?: string; status?: string; sort?: string },
  options?: { refetchInterval?: number }
) {
  return useQuery({
    queryKey: ["documentsPage", kbId, params],
    queryFn: () => api.getDocumentsPage(kbId, params),
    enabled: !!kbId,
    refetchInterval: options?.refetchInterval,
  });
}

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, file }: { kbId: string; file: File }) =>
      api.uploadDocument(kbId, file),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
      queryClient.invalidateQueries({ queryKey: ["documentsPage", kbId] });
      queryClient.invalidateQueries({ queryKey: ["knowledgeBases"] });
    },
  });
}

export function useUploadDocuments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ kbId, files }: { kbId: string; files: File[] }) => {
      const results = [];
      for (const file of files) {
        try {
          await api.uploadDocument(kbId, file);
          results.push({ success: true, file: file.name });
        } catch (e) {
          results.push({ success: false, file: file.name, error: e });
        }
      }
      return results;
    },
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
      queryClient.invalidateQueries({ queryKey: ["documentsPage", kbId] });
      queryClient.invalidateQueries({ queryKey: ["knowledgeBases"] });
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, docId }: { kbId: string; docId: string }) =>
      api.deleteDocument(kbId, docId),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
      queryClient.invalidateQueries({ queryKey: ["documentsPage", kbId] });
      queryClient.invalidateQueries({ queryKey: ["knowledgeBases"] });
    },
  });
}

export function useReindexDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, docId }: { kbId: string; docId: string }) =>
      api.reindexDocument(kbId, docId),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
      queryClient.invalidateQueries({ queryKey: ["documentsPage", kbId] });
    },
  });
}

/**
 * 召回测试 (MVP)
 * @param kbId 知识库 ID
 * @param body { query, top_k, threshold, use_rerank }
 * @returns RetrievalTestResult { query, items, timings }
 */
export function useRetrievalTest() {
  return useMutation({
    mutationFn: ({
      kbId,
      body,
    }: {
      kbId: string;
      body: { query: string; top_k: number; threshold: number; use_rerank: boolean };
    }) => api.retrievalTest(kbId, body),
  });
}

export function useIndexingStatus(
  kbId: string, 
  docId: string, 
  enabled: boolean = false,
  onComplete?: () => void
) {
  const queryClient = useQueryClient();
  
  return useQuery({
    queryKey: ["indexingStatus", kbId, docId],
    queryFn: () => api.getIndexingStatus(kbId, docId),
    enabled: enabled && !!kbId && !!docId,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const progress = query.state.data?.progress;
      console.log("[useIndexingStatus]", docId, "status:", status, "progress:", progress);
      if (status === "pending" || status === "indexing") {
        return 2000;
      }
      if ((status === "ready" || status === "error") && onComplete) {
        onComplete();
      }
      return false;
    },
  });
}

// PPT Status Polling
export function usePptStatus(taskId: string | null, onComplete?: () => void) {
  return useQuery({
    queryKey: ["pptStatus", taskId],
    queryFn: () => api.getPptStatus(taskId!),
    enabled: !!taskId,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "pending" || status === "generating" || status === "uploading") {
        return 2000;
      }
      if (status === "ready" && onComplete) {
        onComplete();
      }
      return false;
    },
  });
}

// PDF Status Polling
export function usePdfStatus(taskId: string | null, onComplete?: () => void) {
  return useQuery({
    queryKey: ["pdfStatus", taskId],
    queryFn: () => api.getPdfStatus(taskId!),
    enabled: !!taskId,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "pending" || status === "generating" || status === "uploading") {
        return 2000;
      }
      if (status === "ready" && onComplete) {
        onComplete();
      }
      return false;
    },
  });
}

// Conversations
export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.getConversations(),
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { title?: string; knowledge_base_id?: string }) =>
      api.createConversation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

// Stats
export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => api.getStats(),
    refetchInterval: 30000,
  });
}

export function useTopQueries() {
  return useQuery({
    queryKey: ["topQueries"],
    queryFn: () => api.getTopQueries(),
    refetchInterval: 30000,
  });
}

export function useQueryTrend() {
  return useQuery({
    queryKey: ["queryTrend"],
    queryFn: () => api.getQueryTrend(),
    refetchInterval: 30000,
  });
}

export function useAgentMetrics(days: number = 7) {
  return useQuery({
    queryKey: ["agentMetrics", days],
    queryFn: () => api.getAgentMetrics(days),
    refetchInterval: 30000,
  });
}

export function useAgentTrend(days: number = 7) {
  return useQuery({
    queryKey: ["agentTrend", days],
    queryFn: () => api.getAgentTrend(days),
    refetchInterval: 30000,
  });
}

export function useSearchMetrics() {
  return useQuery({
    queryKey: ["searchMetrics"],
    queryFn: () => api.getSearchMetrics(),
    refetchInterval: 30000,
  });
}

export function useSearchTrend(days: number = 7) {
  return useQuery({
    queryKey: ["searchTrend", days],
    queryFn: () => api.getSearchTrend(days),
    refetchInterval: 30000,
  });
}
