"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { Loading } from "@/components/states";
import { useAuth } from "@/lib/auth";

/** The authenticated shell. `middleware.ts` already redirects a cookie-less
 * browser here; this also handles the case where the cookie exists but the
 * session is dead (the `/me` call 401s). */
export default function SocLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <div className="login">
        <Loading label="Checking your session…" />
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
