import ChatPage from "@/components/chat/chat-page";
import DashboardLayout from "@/app/dashboard-layout";

export default function Page({
  searchParams,
}: {
  searchParams?: { kb_id?: string; q?: string; auto_send?: string };
}) {
  return (
    <DashboardLayout>
      <ChatPage
        initialKbId={searchParams?.kb_id || ""}
        initialQuery={searchParams?.q || ""}
        autoSend={searchParams?.auto_send === "1"}
      />
    </DashboardLayout>
  );
}
