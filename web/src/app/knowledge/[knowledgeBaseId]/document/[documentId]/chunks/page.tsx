import { DocumentChunkDetail } from "@/components/kb/document-chunk-detail";

export default function ChunkDetailPage({
  params,
  searchParams,
}: {
  params: { knowledgeBaseId: string; documentId: string };
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  return (
    <div className="h-screen overflow-hidden bg-[radial-gradient(1200px_circle_at_0%_0%,rgba(99,102,241,0.14),transparent_55%),radial-gradient(900px_circle_at_100%_0%,rgba(147,51,234,0.12),transparent_55%),linear-gradient(to_bottom,rgba(248,250,252,1),rgba(245,247,255,1))]">
      <div className="mx-auto flex h-full min-h-0 max-w-[1440px] gap-4 px-4 py-4 md:px-6 md:py-6">
        <div className="min-w-0 flex-1 overflow-hidden rounded-lg border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm flex min-h-0">
          <div className="flex-1 min-h-0">
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
          </div>
        </div>
      </div>
    </div>
  );
}
