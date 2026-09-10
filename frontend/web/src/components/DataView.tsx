"use client";

import type { ReactNode } from "react";
import type { Resource } from "@/lib/useResource";
import { EmptyState, ErrorState, Loading } from "./states";

/** Render the loading / error / empty / ready branches of a resource once,
 * consistently, so no view forgets one of them. */
export function DataView<T>({
  resource,
  isEmpty,
  emptyTitle,
  emptyHint,
  children,
}: {
  resource: Resource<T>;
  isEmpty: (data: T) => boolean;
  emptyTitle: string;
  emptyHint?: string;
  children: (data: T) => ReactNode;
}) {
  if (resource.loading && resource.data === null) return <Loading />;
  if (resource.error) return <ErrorState error={resource.error} onRetry={resource.reload} />;
  if (resource.data === null || isEmpty(resource.data)) {
    return <EmptyState title={emptyTitle} hint={emptyHint} />;
  }
  return <>{children(resource.data)}</>;
}
