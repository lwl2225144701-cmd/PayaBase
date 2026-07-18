import DashboardLayout from "@/app/dashboard-layout";
import { DocumentChunkDetail } from "@/components/kb/document-chunk-detail";

export default function ChunkDetailPage({
  params,
  searchParams,
}: {
  params: { knowledgeBaseId: string; documentId: string };
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  return (
    <DashboardLayout>
      <DocumentChunkDetail
        kbId={params.knowledgeBaseId}
        documentId={params.documentId}
        listParams={{
          page: typeof searchParams.page === "string" ? searchParams.page : undefined,
          q: typeof searchParams.q === "string" ? searchParams.q : undefined,
          status: typeof searchParams.status === "string" ? searchParams.status : undefined,
          sort: typeof searchParams.sort === "string" ? searchParams.sort : undefined,
        }}
      />
    </DashboardLayout>
  );
}
