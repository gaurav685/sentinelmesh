"use client";

import Link from "next/link";
import { type FormEvent, useRef, useState } from "react";
import type { DatasetUploadResult } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ErrorState, Loading } from "@/components/states";

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

export default function DatasetsPage() {
  const { csrfToken } = useAuth();
  const fileRef = useRef<HTMLInputElement>(null);
  const [upload, setUpload] = useState<Async<DatasetUploadResult>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUpload({ status: "loading" });
    try {
      const data = await api.uploadNslKddDataset(file, csrfToken);
      setUpload({ status: "done", data });
    } catch (err) {
      setUpload({ status: "error", error: err instanceof Error ? err : new Error(String(err)) });
    }
  }

  return (
    <div className="grid">
      <h1>Datasets</h1>
      <p className="state__hint">
        Upload a real, public dataset and replay it through the real ingestion pipeline (Kafka →
        normalization → detection) — distinct from <Link href="/simulation">Simulation</Link>&apos;s
        synthetic scenarios. Only the <strong>NSL-KDD</strong> network-connection format is
        understood today (comma-separated, 43 columns per row, e.g.{" "}
        <code>KDDTest+.txt</code> / <code>KDDTrain+.txt</code>); an unrecognized format is
        refused, not guessed at.
      </p>

      <div className="panel">
        <form onSubmit={onSubmit} className="grid" style={{ marginTop: 8 }}>
          <label className="field">
            <span>NSL-KDD file (.txt, comma-separated)</span>
            <input ref={fileRef} type="file" accept=".txt,.csv" />
          </label>
          <button type="submit" className="btn" disabled={upload.status === "loading"}>
            {upload.status === "loading" ? "Uploading…" : "Upload & replay"}
          </button>
        </form>

        {upload.status === "loading" ? <Loading label="Parsing and replaying…" /> : null}
        {upload.status === "error" ? <ErrorState error={upload.error} /> : null}
        {upload.status === "done" ? <UploadResult result={upload.data} /> : null}
      </div>
    </div>
  );
}

function UploadResult({ result }: { result: DatasetUploadResult }) {
  const labels = Object.entries(result.ground_truth_labels ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <p>
        Read <strong>{result.rows_read}</strong> real rows — <strong>{result.accepted}</strong>{" "}
        accepted into the pipeline, <strong>{result.rejected}</strong> rejected. Attributed to
        sensor <code>{result.sensor_id}</code>.
      </p>
      <p className="state__hint">
        The dataset&apos;s own labels below were <strong>not</strong> sent to the pipeline — only
        printed here so you can compare them against whatever the real detection pipeline decides
        on its own. Check <Link href="/detections">Detections</Link> in a few seconds.
      </p>
      <table className="data">
        <thead>
          <tr>
            <th>Dataset label</th>
            <th>Rows</th>
          </tr>
        </thead>
        <tbody>
          {labels.map(([label, count]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
