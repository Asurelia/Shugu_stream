import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { AdminPageStub } from "@/components/admin/AdminPageStub";

export default function AnalyticsPage() {
  return (
    <>
      <Meta />
      <AdminShell
        active="analytics"
        title="Harmonized Stream Pulse"
        subtitle="Stream metrics &amp; community heartbeat."
      >
        <AdminPageStub mockup="analytics_community" />
      </AdminShell>
    </>
  );
}
