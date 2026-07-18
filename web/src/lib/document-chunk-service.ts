import { api } from "./api";
import type { DocumentDetail, ChunkListResponse } from "@/types";

export interface ChunkQueryParams {
  page: number;
  pageSize: number;
  keyword?: string;
  status?: string;
}

export async function getDocumentDetail(
  kbId: string,
  docId: string
): Promise<DocumentDetail> {
  return api.getDocumentDetail(kbId, docId);
}

export async function getDocumentContent(
  kbId: string,
  docId: string
): Promise<string> {
  return api.getDocumentContent(kbId, docId);
}

export async function getDocumentChunks(
  kbId: string,
  docId: string,
  params: ChunkQueryParams
): Promise<ChunkListResponse> {
  return api.getDocumentChunks(kbId, docId, params);
}
