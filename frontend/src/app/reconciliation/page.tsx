import { EmptyState, PageTitle } from "@/components/ui";

export default function ReconciliationPage() {
  return (
    <div>
      <PageTitle
        title="Reconciliation"
        subtitle="Bank statement upload and payment matching"
      />
      <EmptyState message="Coming in a later phase (Part C)." />
    </div>
  );
}
