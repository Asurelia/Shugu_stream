import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { AdminPageStub } from "@/components/admin/AdminPageStub";

export default function SchedulePage() {
  return (
    <>
      <Meta />
      <AdminShell
        active="schedule"
        title="Schedule"
        subtitle="Calendrier des streams et rituels récurrents."
      >
        <AdminPageStub mockup="assets_schedule" note="Partage le mockup avec Assets — split par onglets à suivre." />
      </AdminShell>
    </>
  );
}
