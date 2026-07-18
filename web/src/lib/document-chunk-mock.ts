import type { Chunk, ChunkVectorStatus, DocumentDetail } from "@/types";

export const MOCK_DOCUMENT_DETAIL: DocumentDetail = {
  id: "doc_color_scheme",
  knowledge_base_id: "kb_1",
  title: "色彩协调改造方案.md",
  file_type: "markdown",
  file_size: 7372,
  status: "ready",
  chunk_count: 11,
  strategy: "通用",
  created_at: "2026-07-17T15:24:00Z",
};

export const MOCK_DOCUMENT_CONTENT = `# 色彩协调改造方案

本文档旨在提出一套全面的色彩协调改造方案，以提升产品的视觉一致性、用户体验和品牌识别度。方案将从现状分析、设计原则、颜色体系、改造策略和实施计划五个方面展开。

## 1. 现状分析

当前产品存在色彩使用不统一、对比度不足、品牌色应用不充分等问题，导致界面层级不清晰，用户在使用过程中容易产生视觉疲劳，影响整体体验。

## 2. 设计原则

色彩协调改造应遵循以下原则：一致性、可访问性、简洁性、品牌一致性、情感化表达。通过科学的色彩搭配，建立清晰的信息层级，增强用户对产品的信任感与归属感。

## 3. 颜色体系

我们将建立以品牌色为核心的颜色体系，包括主色、辅助色、中性色和功能色。主色用于品牌识别，辅助色用于丰富界面层次，中性色保障文本与背景的可读性，功能色用于状态反馈（如成功、警告、错误等）。

## 4. 改造策略

分阶段推进改造：首先统一基础组件色彩规范；其次优化页面布局与层级；最后逐步替换老版本色彩，确保平滑过渡，降低对业务的影响。

## 5. 实施计划

第一阶段：完成色彩审计与规范制定；第二阶段：更新设计系统组件；第三阶段：推进产品页面改造；第四阶段：建立长效监控与迭代机制。
`;

export const MOCK_CHUNKS: Chunk[] = [
  {
    id: "1",
    chunk_id: "chunk_001",
    document_id: "doc_color_scheme",
    section_title: "色彩协调改造方案",
    page_number: 1,
    start_offset: 0,
    end_offset: 112,
    token_count: 84,
    character_count: 112,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "# 色彩协调改造方案\n\n本文档旨在提出一套全面的色彩协调改造方案，以提升产品的视觉一致性、用户体验和品牌识别度。",
  },
  {
    id: "2",
    chunk_id: "chunk_002",
    document_id: "doc_color_scheme",
    section_title: "色彩协调改造方案",
    page_number: 1,
    start_offset: 112,
    end_offset: 212,
    token_count: 76,
    character_count: 100,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "方案将从现状分析、设计原则、颜色体系、改造策略和实施计划五个方面展开。",
  },
  {
    id: "3",
    chunk_id: "chunk_003",
    document_id: "doc_color_scheme",
    section_title: "1. 现状分析",
    page_number: 1,
    start_offset: 212,
    end_offset: 482,
    token_count: 168,
    character_count: 270,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "## 1. 现状分析\n\n当前产品存在色彩使用不统一、对比度不足、品牌色应用不充分等问题，导致界面层级不清晰，用户在使用过程中容易产生视觉疲劳，影响整体体验。",
  },
  {
    id: "4",
    chunk_id: "chunk_004",
    document_id: "doc_color_scheme",
    section_title: "2. 设计原则",
    page_number: 1,
    start_offset: 482,
    end_offset: 856,
    token_count: 256,
    character_count: 374,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "## 2. 设计原则\n\n色彩协调改造应遵循以下原则：一致性、可访问性、简洁性、品牌一致性、情感化表达。通过科学的色彩搭配，建立清晰的信息层级，增强用户对产品的信任感与归属感。",
  },
  {
    id: "5",
    chunk_id: "chunk_005",
    document_id: "doc_color_scheme",
    section_title: "3. 颜色体系",
    page_number: 2,
    start_offset: 856,
    end_offset: 1046,
    token_count: 148,
    character_count: 190,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "## 3. 颜色体系\n\n我们将建立以品牌色为核心的颜色体系，包括主色、辅助色、中性色和功能色。",
  },
  {
    id: "6",
    chunk_id: "chunk_006",
    document_id: "doc_color_scheme",
    section_title: "3. 颜色体系",
    page_number: 2,
    start_offset: 1046,
    end_offset: 1262,
    token_count: 158,
    character_count: 216,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "主色用于品牌识别，辅助色用于丰富界面层次，中性色保障文本与背景的可读性，功能色用于状态反馈（如成功、警告、错误等）。",
  },
  {
    id: "7",
    chunk_id: "chunk_007",
    document_id: "doc_color_scheme",
    section_title: "4. 改造策略",
    page_number: 2,
    start_offset: 1262,
    end_offset: 1514,
    token_count: 178,
    character_count: 252,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "## 4. 改造策略\n\n分阶段推进改造：首先统一基础组件色彩规范；其次优化页面布局与层级；最后逐步替换老版本色彩，确保平滑过渡，降低对业务的影响。",
  },
  {
    id: "8",
    chunk_id: "chunk_008",
    document_id: "doc_color_scheme",
    section_title: "5. 实施计划",
    page_number: 3,
    start_offset: 1514,
    end_offset: 1648,
    token_count: 96,
    character_count: 134,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "## 5. 实施计划\n\n第一阶段：完成色彩审计与规范制定；第二阶段：更新设计系统组件。",
  },
  {
    id: "9",
    chunk_id: "chunk_009",
    document_id: "doc_color_scheme",
    section_title: "5. 实施计划",
    page_number: 3,
    start_offset: 1648,
    end_offset: 1804,
    token_count: 114,
    character_count: 156,
    vector_status: "indexed",
    embedding_model: "bge-m3",
    created_at: "2026-07-17T15:24:00Z",
    content: "第三阶段：推进产品页面改造；第四阶段：建立长效监控与迭代机制。",
  },
  {
    id: "10",
    chunk_id: "chunk_010",
    document_id: "doc_color_scheme",
    section_title: "总结",
    page_number: 3,
    start_offset: 1804,
    end_offset: 1980,
    token_count: 132,
    character_count: 176,
    vector_status: "error",
    embedding_model: null,
    created_at: "2026-07-17T15:24:00Z",
    content: "通过本次色彩协调改造，产品将获得更加统一的视觉语言，提升用户操作效率与品牌认知。",
  },
  {
    id: "11",
    chunk_id: "chunk_011",
    document_id: "doc_color_scheme",
    section_title: "附录",
    page_number: 3,
    start_offset: 1980,
    end_offset: 2164,
    token_count: 146,
    character_count: 184,
    vector_status: "pending",
    embedding_model: null,
    created_at: "2026-07-17T15:24:00Z",
    content: "附录包含色彩对比度检测工具推荐、WCAG 可访问性标准链接以及品牌色扩展色板。",
  },
];

export function mockDocumentChunks(
  params: { page: number; pageSize: number; keyword?: string; status?: string }
) {
  const { page, pageSize, keyword, status } = params;
  let items = [...MOCK_CHUNKS];

  if (status && status !== "all") {
    const map: Record<string, ChunkVectorStatus> = {
      indexed: "indexed",
      error: "error",
      pending: "pending",
    };
    const target = map[status];
    if (target) {
      items = items.filter((c) => c.vector_status === target);
    }
  }

  if (keyword && keyword.trim()) {
    const q = keyword.trim().toLowerCase();
    items = items.filter(
      (c) =>
        c.content.toLowerCase().includes(q) ||
        c.chunk_id.toLowerCase().includes(q) ||
        (c.section_title && c.section_title.toLowerCase().includes(q))
    );
  }

  const total = items.length;
  const start = (page - 1) * pageSize;
  const paged = items.slice(start, start + pageSize);

  return {
    items: paged,
    total,
    page,
    page_size: pageSize,
  };
}
