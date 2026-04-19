import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { AdminPageStub } from "@/components/admin/AdminPageStub";

export default function CommunityPage() {
  return (
    <>
      <Meta />
      <AdminShell
        active="community"
        title="Community"
        subtitle="Tes supporters, subs et rangs — tissés au veil."
      >
        <AdminPageStub mockup="analytics_community" note="Partage le mockup avec Analytics — split par onglets à suivre." />
      </AdminShell>
    </>
  );
}
