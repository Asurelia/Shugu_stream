import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { AdminPageStub } from "@/components/admin/AdminPageStub";

export default function ModerationPage() {
  return (
    <>
      <Meta />
      <AdminShell
        active="moderation"
        title="Moderation Hub"
        subtitle="Gestion viewers, accès, règles et activité du stream."
      >
        <AdminPageStub mockup="admin_moderation" />
      </AdminShell>
    </>
  );
}
