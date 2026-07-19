"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { MarkdownRenderer } from "@/components/ui/markdown";
import { api } from "@/lib/api";
import AttachmentUpload, { AttachmentState } from "./attachment-upload";
import { ArtifactProgressCard } from "./artifact-progress-card";
import { Copy, Send, Share2, Star } from "lucide-react";

interface ArtifactInfo {
  type: "ppt" | "pdf";
  taskId: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Array<Record<string, any>>;
  attachments?: { name: string; type: string }[];
  artifacts?: ArtifactInfo[];
  agent?: {
    run_id?: string;
    run_db_id?: string;
    status?: string;
    current_step?: string;
    next_step?: string | null;
    completed_steps_summary?: string;
    route?: string;
    decision_source?: string;
    reason?: string;
    confidence?: number;
    citations?: Array<Record<string, any>>;
    chunks_count?: number;
    citations_count?: number;
    timings?: Record<string, any>;
  };
}

interface AgentRunDetail {
  id: string;
  status: string;
  route?: string;
  current_step?: string;
  next_step?: string | null;
  completed_steps_summary?: string;
  last_error?: string | null;
}

interface AgentStepDetail {
  id: string;
  step_key: string;
  step_type: string;
  step_goal: string;
  status: string;
  output?: string;
  error?: string;
  tool_trace?: Array<Record<string, any>>;
}

type ChatPageProps = {
  initialKbId?: string;
  initialQuery?: string;
  autoSend?: boolean; // 预留：当前不自动发送，由用户手动点击发送
};

export default function ChatPage({
  initialKbId = "",
  initialQuery = "",
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(initialQuery || "");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string>("");
  const [attachments, setAttachments] = useState<AttachmentState[]>([]);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState<Record<string, boolean>>({});
  const [runDetails, setRunDetails] = useState<Record<string, AgentRunDetail>>({});
  const [runSteps, setRunSteps] = useState<Record<string, AgentStepDetail[]>>({});
  const [webSearchMode, setWebSearchMode] = useState<"off" | "on">("off");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load history
  const [currentKBId, setCurrentKBId] = useState<string>("");
  const [knowledgeBases, setKnowledgeBases] = useState<Array<{ id: string; name: string }>>([]);
  useEffect(() => {
    async function loadHistory() {
      try {
        const kbList: any[] = await api.getKnowledgeBases();
        const kbs = (kbList || []).map((kb: any) => ({ id: kb.id, name: kb.name }));
        setKnowledgeBases(kbs);

        const convs: any = await api.getConversations();

        // 从召回测试等入口带 kb_id 进来时优先选中该知识库，不加载旧会话消息
        const initialKbExists =
          initialKbId && kbs.some((kb: any) => kb.id === initialKbId);

        if (initialKbExists) {
          setCurrentKBId(initialKbId);
        } else if (convs && convs.length > 0) {
          const convWithKB = convs.find((c: any) => c.knowledge_base_id);
          const latestConv = convWithKB || convs[0];
          setConversationId(latestConv.id);
          setCurrentKBId(latestConv.knowledge_base_id || "");

          const msgs: any = await api.getConversation(latestConv.id);
          if (msgs && msgs.length > 0) {
            const history = msgs.map((m: any) => ({
              role: m.role,
              content: m.content,
              citations: m.citations || [],
              agent: m.context?.agent,
            }));
            setMessages(history);
          }
        } else if (kbs.length > 0) {
          setCurrentKBId(kbs[0].id);
        }
      } catch (e) {
        console.error("加载历史失败:", e);
      }
    }
    loadHistory();
  }, [initialKbId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const loadRunDetails = async (runId: string) => {
    if (runDetails[runId] && runSteps[runId]) return;
    setRunLoading((prev) => ({ ...prev, [runId]: true }));
    try {
      const [run, steps] = await Promise.all([
        api.getAgentRun(runId),
        api.getAgentRunSteps(runId),
      ]);
      setRunDetails((prev) => ({ ...prev, [runId]: run }));
      setRunSteps((prev) => ({ ...prev, [runId]: steps || [] }));
    } catch (e) {
      console.error("加载Agent明细失败:", e);
    } finally {
      setRunLoading((prev) => ({ ...prev, [runId]: false }));
    }
  };

  const toggleRun = async (runId: string) => {
    const next = expandedRunId === runId ? null : runId;
    setExpandedRunId(next);
    if (next) {
      await loadRunDetails(next);
    }
  };

  const renderToolTraceItem = (item: Record<string, any>, idx: number) => {
    const t = item?.type || "trace";
    if (t === "route") {
      return (
        <div key={idx} className="rounded border border-border/50 p-2">
          <div>route: {item.route || "-"}</div>
          <div>source: {item.decision_source || "-"}</div>
          <div>reason: {item.reason || "-"}</div>
          <div>confidence: {typeof item.confidence === "number" ? item.confidence.toFixed(2) : "-"}</div>
        </div>
      );
    }
    if (t === "retrieval") {
      return (
        <div key={idx} className="rounded border border-border/50 p-2">
          <div>retrieval chunks: {item.chunks_count ?? "-"}</div>
          <div>citations: {item.citations_count ?? "-"}</div>
          <div>rerank: {item.timings?.retrieval_rerank_decision || "off"}</div>
          <div>retrieval_ms: {item.timings?.retrieval_total_ms ?? item.timings?.retrieval_ms ?? "-"}</div>
        </div>
      );
    }
    if (t === "artifacts") {
      return (
        <div key={idx} className="rounded border border-border/50 p-2">
          <div>artifacts:</div>
          <div className="opacity-80 break-all">{JSON.stringify(item.items || [], null, 0)}</div>
        </div>
      );
    }
    if (t === "error") {
      return (
        <div key={idx} className="rounded border border-red-300 p-2 text-red-500">
          error: {item.message || "-"}
        </div>
      );
    }
    return (
      <div key={idx} className="rounded border border-border/50 p-2 opacity-80 break-all">
        {JSON.stringify(item)}
      </div>
    );
  };

  const RetrievalProcessCard = ({ agent }: { agent?: Record<string, any> }) => {
    const [open, setOpen] = useState(false);
    if (!agent) return null;
    const t = agent.timings || {};

    // 仅在真正发生过 RAG 检索时才展示,避免非检索场景出现空调试区
    const hasRag =
      (typeof t.embedding_ms === "number" && t.embedding_ms > 0) ||
      (typeof t.retrieval_ms === "number" && t.retrieval_ms > 0) ||
      (agent.chunks_count ?? 0) > 0 ||
      (agent.citations_count ?? 0) > 0 ||
      !!t.retrieval_rerank_decision;
    if (!hasRag) return null;

    const ms = (v: any) => (typeof v === "number" && v > 0 ? `${v} ms` : null);
    const rows: Array<{ label: string; value: string }> = [];
    if (agent.route) {
      rows.push({
        label: "路由",
        value: agent.decision_source ? `${agent.route} · ${agent.decision_source}` : `${agent.route}`,
      });
      if (agent.reason) rows.push({ label: "决策理由", value: String(agent.reason) });
    }
    if (typeof agent.chunks_count === "number") rows.push({ label: "召回分块", value: `${agent.chunks_count}` });
    if (typeof agent.citations_count === "number") rows.push({ label: "引用数量", value: `${agent.citations_count}` });
    const rerankDecision = t.retrieval_rerank_decision;
    if (rerankDecision) rows.push({ label: "重排序", value: String(rerankDecision) });
    const rerankReason = t.retrieval_rerank_reason;
    if (rerankReason && rerankReason !== "not_evaluated") rows.push({ label: "重排序理由", value: String(rerankReason) });
    const retrievalMs = ms(t.retrieval_ms) || ms(t.retrieval_total_ms);
    if (retrievalMs) rows.push({ label: "检索耗时", value: retrievalMs });
    const emb = ms(t.embedding_ms);
    if (emb) rows.push({ label: "向量化", value: emb });
    const vsql = ms(t.retrieval_vector_sql_ms);
    if (vsql) rows.push({ label: "向量SQL", value: vsql });
    const bm25 = ms(t.retrieval_bm25_ms);
    if (bm25) rows.push({ label: "BM25", value: bm25 });
    const rrf = ms(t.retrieval_rrf_ms);
    if (rrf) rows.push({ label: "RRF", value: rrf });
    const rms = ms(t.retrieval_rerank_ms);
    if (rms) rows.push({ label: "重排序耗时", value: rms });

    if (rows.length === 0) return null;

    return (
      <div className="mt-3 rounded-md border border-border/60 bg-muted/30">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />
            检索过程
          </span>
          <span>{open ? "收起" : "展开"}</span>
        </button>
        {open && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-border/50 px-3 py-2 text-xs sm:grid-cols-3">
            {rows.map((r, i) => (
              <div key={i} className="min-w-0">
                <div className="text-[10px] text-muted-foreground">{r.label}</div>
                <div className="truncate font-medium text-foreground" title={r.value}>
                  {r.value}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderCitationTitle = (citation: Record<string, any>) => {
    return (
      citation.document_title ||
      citation.title ||
      citation.source ||
      citation.filename ||
      citation.doc_title ||
      citation.doc_id ||
      citation.chunk_id ||
      "来源文档"
    );
  };

  const renderCitations = (citations?: Array<Record<string, any>>) => {
    if (!citations?.length) return null;
    const normalized = citations.slice(0, 6);
    return (
      <div className="mt-3 rounded-md border border-border/70 bg-background/60 p-3">
        <div className="mb-2 text-xs font-medium text-muted-foreground">参考来源</div>
        <div className="flex flex-wrap gap-2">
          {normalized.map((citation, index) => (
            <span
              key={index}
              className="inline-flex max-w-[280px] flex-col gap-0.5 rounded-md border bg-background/70 px-2.5 py-1.5 text-xs shadow-sm"
              title={JSON.stringify(citation)}
            >
              <span className="flex items-center gap-1.5">
                <span className="font-medium text-primary">[{index + 1}]</span>
                <span className="truncate font-medium text-foreground">{renderCitationTitle(citation)}</span>
              </span>
              <span className="flex flex-wrap items-center gap-x-2 text-[10px] text-muted-foreground">
                {citation.chunk_id && (
                  <span className="font-mono truncate">chunk: {citation.chunk_id}</span>
                )}
                {typeof citation.score === "number" && (
                  citation.score_type === "rerank" ? (
                    <span>相关度: {(citation.score * 100).toFixed(1)}%</span>
                  ) : (
                    <span title="RRF 融合分仅用于排序，不代表相关度">RRF: {citation.score.toFixed(4)}</span>
                  )
                )}
              </span>
            </span>
          ))}
        </div>
      </div>
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const readyFiles = attachments.filter((a) => a.status === "ready").map((a) => a.file);
    if ((!input.trim() && readyFiles.length === 0) || loading) return;

    const userMessage = input.trim();
    setInput("");

    // Build message with attachment info
    const msgAttachments = attachments
      .filter((a) => a.status === "ready")
      .map((a) => ({ name: a.file.name, type: a.file.type }));

    setMessages((prev) => [
      ...prev,
      {
        role: "user",
        content: userMessage,
        attachments: msgAttachments.length > 0 ? msgAttachments : undefined,
      },
    ]);

    const filesToSend = readyFiles;
    setAttachments([]);
    setLoading(true);

    try {
      let convId = conversationId;
      if (!convId) {
        const title =
          userMessage.slice(0, 50) ||
          filesToSend[0]?.name.slice(0, 50) ||
          "新对话";
        const conv: any = await api.createConversation({
          title,
          knowledge_base_id: currentKBId || undefined,
        });
        convId = conv.id;
        setConversationId(convId);
      }

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      const stream =
        filesToSend.length > 0
          ? api.chatStreamWithFiles(convId, userMessage, filesToSend, currentKBId, webSearchMode === "on")
          : api.chatStream(convId, userMessage, currentKBId, webSearchMode === "on");

      for await (const chunk of stream) {
        // Detect artifact events (new unified protocol)
        if (chunk.artifact) {
          const artifact: ArtifactInfo = {
            type: chunk.artifact.type,
            taskId: chunk.artifact.task_id,
          };
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              const existing = last.artifacts || [];
              return [...prev.slice(0, -1), { ...last, artifacts: [...existing, artifact] }];
            }
            return prev;
          });
          continue;
        }
        if (chunk.agent) {
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              const next = { ...last, agent: chunk.agent };
              if (chunk.agent.citations?.length) {
                next.citations = chunk.agent.citations;
              }
              return [...prev.slice(0, -1), next];
            }
            return prev;
          });
          continue;
        }
        if (chunk.citations && chunk.citations.length > 0) {
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, citations: chunk.citations }];
            }
            return prev;
          });
        }
        // Legacy: detect individual task_id fields
        if (chunk.ppt_task_id) {
          const artifact: ArtifactInfo = { type: "ppt", taskId: chunk.ppt_task_id };
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              const existing = last.artifacts || [];
              return [...prev.slice(0, -1), { ...last, artifacts: [...existing, artifact] }];
            }
            return prev;
          });
          continue;
        }
        if (chunk.pdf_task_id) {
          const artifact: ArtifactInfo = { type: "pdf", taskId: chunk.pdf_task_id };
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              const existing = last.artifacts || [];
              return [...prev.slice(0, -1), { ...last, artifacts: [...existing, artifact] }];
            }
            return prev;
          });
          continue;
        }
        if (chunk.web_search_mode) {
          setWebSearchMode(chunk.web_search_mode === "on" ? "on" : "off");
        }
        if (!chunk.content) continue;
        for (const char of chunk.content) {
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              return [
                ...prev.slice(0, -1),
                { ...last, content: last.content + char },
              ];
            }
            return prev;
          });
          await new Promise((resolve) => setTimeout(resolve, 30));
        }
      }
    } catch (error) {
      console.error(error);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "抱歉，发生错误" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const headerTitle = (() => {
    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user" && m.content?.trim());
    if (lastUserMsg?.content) {
      return lastUserMsg.content.length > 28
        ? lastUserMsg.content.slice(0, 28) + "..."
        : lastUserMsg.content;
    }
    return "新对话";
  })();

  return (
    <div className="flex flex-1 h-full min-h-0 flex-col">
      <div className="shrink-0 flex items-center justify-between gap-3 border-b bg-background/40 px-6 py-4">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-foreground">{headerTitle}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">PayaBase · AI</div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={currentKBId}
            onChange={(e) => setCurrentKBId(e.target.value)}
            disabled={loading || knowledgeBases.length === 0}
            className="h-9 max-w-[260px] rounded-md border border-input bg-background/70 px-3 text-sm shadow-sm"
            title="选择知识库"
          >
            {knowledgeBases.length === 0 ? (
              <option value="">暂无可用知识库</option>
            ) : (
              knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))
            )}
          </select>
          <Button variant="outline" size="icon" className="h-9 w-9 bg-background/70 shadow-sm" disabled title="收藏">
            <Star className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" className="h-9 w-9 bg-background/70 shadow-sm" disabled title="分享">
            <Share2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto bg-[radial-gradient(900px_circle_at_50%_0%,rgba(99,102,241,0.10),transparent_60%)] px-6 py-6"
      >
          <div className="mx-auto max-w-[920px] space-y-6">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "assistant" && (
                  <Avatar className="mt-0.5 h-8 w-8 border bg-background">
                    <AvatarFallback className="bg-[linear-gradient(135deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white">
                      AI
                    </AvatarFallback>
                  </Avatar>
                )}

                <div className="max-w-[860px] flex-1">
                  {msg.role === "assistant" && (
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">PayaBase</span>
                        <span>AI</span>
                        <span className="opacity-70">·</span>
                        <span className="opacity-70">刚刚</span>
                      </div>
	                      <Button
	                        variant="ghost"
	                        size="icon"
	                        className="h-7 w-7 text-muted-foreground hover:text-foreground"
	                        disabled
	                        title="复制"
	                      >
	                        <Copy className="h-4 w-4" />
	                      </Button>
	                    </div>
                  )}

                  <div
                    className={[
                      "rounded-lg border px-5 py-4 text-sm shadow-sm",
                      msg.role === "user"
                        ? "border-transparent bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white"
                        : "border-border/70 bg-background/75 backdrop-blur supports-[backdrop-filter]:bg-background/60",
                    ].join(" ")}
                  >
	                    {msg.attachments && msg.attachments.length > 0 && (
	                      <div className="text-xs opacity-85 mb-2 flex items-center gap-2">
	                        <span className="inline-block h-2 w-2 rounded-full bg-white/60" />
	                        {msg.attachments.length === 1 ? (
	                          <span className="break-all">{msg.attachments[0].name}</span>
	                        ) : (
	                          <span>{msg.attachments.length} 个附件</span>
	                        )}
	                      </div>
	                    )}
                    {msg.role === "assistant" ? (
	                      msg.content || (msg.artifacts && msg.artifacts.length > 0) ? (
	                        <>
                          {msg.content && <MarkdownRenderer content={msg.content} />}
                          {renderCitations(msg.citations || (msg.agent?.citations as any))}
                          {msg.role === "assistant" && <RetrievalProcessCard agent={msg.agent} />}
                          {msg.artifacts?.map((a, j) => (
	                            <div key={j} className="mt-3">
	                              <ArtifactProgressCard type={a.type} taskId={a.taskId} />
	                            </div>
	                          ))}
	                          {msg.agent && (
	                            <div className="mt-3 rounded-md border border-border/70 bg-background/60 p-3 text-xs text-muted-foreground space-y-1">
	                              <div>Agent状态: {msg.agent.status || "-"}</div>
	                              <div>当前步骤: {msg.agent.current_step || "-"}</div>
	                              <div>下一步: {msg.agent.next_step || "-"}</div>
	                              {msg.agent.run_db_id && (
	                                <div>
	                                  RunID:
	                                  <button
	                                    type="button"
	                                    className="ml-1 underline underline-offset-2 hover:text-foreground"
	                                    onClick={() => toggleRun(msg.agent!.run_db_id!)}
	                                  >
	                                    {msg.agent.run_db_id}
	                                  </button>
	                                </div>
	                              )}
	                              {msg.agent.run_db_id && expandedRunId === msg.agent.run_db_id && (
	                                <div className="mt-2 rounded border border-border/70 bg-background/70 p-2 space-y-2">
	                                  {runLoading[msg.agent.run_db_id] ? (
	                                    <div>加载执行明细中...</div>
	                                  ) : (
	                                    <>
	                                      {runDetails[msg.agent.run_db_id] && (
	                                        <div className="space-y-1">
	                                          <div>路由: {runDetails[msg.agent.run_db_id].route || "-"}</div>
	                                          <div>运行状态: {runDetails[msg.agent.run_db_id].status || "-"}</div>
	                                          {runDetails[msg.agent.run_db_id].last_error && (
	                                            <div className="text-red-500">
	                                              错误: {runDetails[msg.agent.run_db_id].last_error}
	                                            </div>
	                                          )}
	                                        </div>
	                                      )}
	                                      <div className="space-y-1">
	                                        {(runSteps[msg.agent.run_db_id] || []).map((step) => (
	                                          <div key={step.id} className="rounded border border-border/60 p-2">
	                                            <div>
	                                              {step.step_key} · {step.step_type} · {step.status}
	                                            </div>
	                                            <div className="opacity-80">{step.step_goal}</div>
	                                            {step.error ? (
	                                              <div className="text-red-500 mt-1">{step.error}</div>
	                                            ) : (
	                                              step.output && (
	                                                <div className="mt-1 line-clamp-3 opacity-80">{step.output}</div>
	                                              )
	                                            )}
	                                            {step.tool_trace && step.tool_trace.length > 0 && (
	                                              <div className="mt-2 space-y-1">
	                                                <div className="opacity-80">执行轨迹</div>
	                                                {step.tool_trace.map((item, traceIndex) =>
	                                                  renderToolTraceItem(item, traceIndex)
	                                                )}
	                                              </div>
	                                            )}
	                                          </div>
	                                        ))}
	                                        {!runSteps[msg.agent.run_db_id]?.length && <div>暂无步骤明细</div>}
	                                      </div>
	                                    </>
	                                  )}
	                                </div>
	                              )}
	                            </div>
	                          )}
	                        </>
	                      ) : (
	                        <div className="flex items-center gap-1 py-1">
	                          <span className="w-2 h-2 bg-muted-foreground/40 rounded-full animate-bounce [animation-delay:0ms]" />
	                          <span className="w-2 h-2 bg-muted-foreground/40 rounded-full animate-bounce [animation-delay:150ms]" />
	                          <span className="w-2 h-2 bg-muted-foreground/40 rounded-full animate-bounce [animation-delay:300ms]" />
	                        </div>
	                      )
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>

	                {msg.role === "user" && (
	                  <Avatar className="mt-0.5 h-8 w-8 border bg-background">
	                    <AvatarFallback className="bg-muted text-foreground">U</AvatarFallback>
	                  </Avatar>
                )}
              </div>
            ))}
          </div>
      </div>

      <div className="shrink-0 border-t bg-background/40 px-6 py-5">
        <div className="mx-auto max-w-[920px]">
          <div className="mb-3 flex flex-wrap gap-2">
            <button type="button" className="h-8 rounded-full border bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:text-foreground" disabled>
              如何设计培训体系？
            </button>
            <button type="button" className="h-8 rounded-full border bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:text-foreground" disabled>
              如何评估培训效果？
            </button>
            <button type="button" className="h-8 rounded-full border bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:text-foreground" disabled>
              给我一份落地计划
            </button>
          </div>

          <form onSubmit={handleSubmit} className="rounded-2xl border border-border/70 bg-background/75 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm px-4 py-3">
            <div className="flex gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={attachments.length > 0 ? "请输入关于附件的问题..." : "请输入你的问题...（Enter 发送，Shift + Enter 换行）"}
              disabled={loading}
              rows={2}
              className="min-h-[44px] w-full resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <Button
              type="submit"
              disabled={loading}
              size="icon"
              className="h-10 w-10 shrink-0 rounded-xl bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white hover:opacity-95 shadow-sm"
              title="发送"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
            <AttachmentUpload attachments={attachments} onChange={setAttachments} kbId={currentKBId} disabled={loading} />
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <button
                type="button"
                onClick={() => setWebSearchMode(webSearchMode === "on" ? "off" : "on")}
                disabled={loading}
                className={`rounded-md border px-2 py-1 shadow-sm transition-colors ${
                  webSearchMode === "on"
                    ? "border-primary/50 bg-primary/10 text-primary"
                    : "bg-background/70 text-muted-foreground"
                }`}
                title={webSearchMode === "on" ? "联网搜索已开启" : "点击开启联网搜索"}
              >
                联网搜索
              </button>
            </div>
          </div>
          </form>
        </div>
      </div>
    </div>
  );
}
