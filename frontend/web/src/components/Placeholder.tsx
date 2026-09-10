import { EmptyState } from "./states";

/** A view that is scaffolded but whose data wiring lands in a later iteration.
 * It shows an honest empty state — it never renders fabricated activity. */
export function Placeholder({ title }: { title: string }) {
  return (
    <div className="grid">
      <h1>{title}</h1>
      <div className="panel">
        <EmptyState
          title="This view is being built"
          hint="The data wiring for this section lands in the next iteration. Nothing here is demo or placeholder activity."
        />
      </div>
    </div>
  );
}
