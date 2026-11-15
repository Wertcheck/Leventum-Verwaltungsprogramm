import { Card, EmptyState, PageHeader } from "../components/ui";

export default function Placeholder({ title, phase }: { title: string; phase: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card><EmptyState title="Noch nicht implementiert">Dieser Bereich ist für Phase {phase} geplant.</EmptyState></Card>
    </>
  );
}
