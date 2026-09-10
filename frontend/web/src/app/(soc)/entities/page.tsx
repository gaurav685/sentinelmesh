"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

export default function EntitiesPage() {
  const router = useRouter();
  const [value, setValue] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const v = value.trim();
    if (v) router.push(`/entities/${encodeURIComponent(v)}`);
  }

  return (
    <div className="grid">
      <h1>Entity explorer</h1>
      <div className="panel">
        <p className="state__hint">
          Look up an identity, host, IP or domain to see its detection timeline and threat context.
        </p>
        <form onSubmit={onSubmit}>
          <label className="field" style={{ maxWidth: 420 }}>
            <span>Entity value (e.g. an identity or hostname)</span>
            <input value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
          </label>
          <button type="submit" className="btn">
            Open
          </button>
        </form>
      </div>
    </div>
  );
}
