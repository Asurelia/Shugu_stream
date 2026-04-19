import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { AdminPageStub } from "@/components/admin/AdminPageStub";

export default function AssetsPage() {
  return (
    <>
      <Meta />
      <AdminShell
        active="assets"
        title="Harmonized Asset Vault"
        subtitle="Modèles 3D, wardrobe, props et intégrations."
      >
        <AdminPageStub mockup="assets_schedule" />
      </AdminShell>
    </>
  );
}
