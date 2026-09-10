"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";

const NAV: { href: string; label: string; perm: string }[] = [
  { href: "/", label: "Dashboard", perm: "detections:read" },
  { href: "/alerts", label: "Alerts", perm: "detections:read" },
  { href: "/incidents", label: "Incidents", perm: "detections:read" },
  { href: "/chains", label: "Attack chains", perm: "detections:read" },
  { href: "/mitre", label: "MITRE ATT&CK", perm: "detections:read" },
  { href: "/heatmap", label: "Risk heatmap", perm: "detections:read" },
  { href: "/entities", label: "Entity explorer", perm: "hunt:query" },
  { href: "/graph", label: "Attack graph", perm: "hunt:query" },
  { href: "/hunt", label: "Threat hunting", perm: "hunt:query" },
  { href: "/intel", label: "Threat intel", perm: "detections:read" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { me, hasPermission, logout } = useAuth();

  return (
    <div className="shell">
      <header className="shell__topbar">
        <div className="shell__brand">
          SentinelMesh
          {me ? <span className="shell__tenant">{me.tenant.name}</span> : null}
        </div>
        <div className="shell__user">
          {me ? <span>{me.user.email}</span> : null}
          <button type="button" className="btn btn--ghost" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </header>
      <div className="shell__body">
        <nav className="shell__nav" aria-label="Primary">
          <ul>
            {NAV.filter((item) => hasPermission(item.perm)).map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link href={item.href} aria-current={active ? "page" : undefined}>
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main className="shell__main" id="main">
          {children}
        </main>
      </div>
    </div>
  );
}
