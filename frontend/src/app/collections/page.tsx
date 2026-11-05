import { EmptyState, PageTitle } from "@/components/ui";

export default function CollectionsPage() {
  return (
    <div>
      <PageTitle
        title="Collections"
        subtitle="Overdue reminders, inbox replies, and Needs attention"
      />
      <EmptyState message="Coming in a later phase (Part B)." />
    </div>
  );
}
