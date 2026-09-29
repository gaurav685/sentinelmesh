import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { uploadNslKddDataset } = vi.hoisted(() => ({ uploadNslKddDataset: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { uploadNslKddDataset },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "test-csrf" }) }));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import DatasetsPage from "./page";

afterEach(() => vi.clearAllMocks());

function selectFile(input: HTMLElement, name: string, content: string) {
  const file = new File([content], name, { type: "text/plain" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("DatasetsPage", () => {
  it("uploads the selected file and renders the real (non-simulated) result", async () => {
    uploadNslKddDataset.mockResolvedValue({
      dataset: "nsl-kdd",
      rows_read: 200,
      accepted: 200,
      rejected: 0,
      ground_truth_labels: { normal: 85, neptune: 54 },
      sensor_id: "s1",
    });
    render(<DatasetsPage />);
    selectFile(screen.getByLabelText(/NSL-KDD file/i), "KDDTest+.txt", "0,tcp,private,REJ,0,0");
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(screen.getByText("neptune")).toBeInTheDocument());
    expect(uploadNslKddDataset).toHaveBeenCalledWith(expect.any(File), "test-csrf");
    expect(screen.getByText("s1", { exact: false })).toBeInTheDocument();
  });

  it("shows an error state when the upload is refused", async () => {
    const { ApiError } = await import("@/lib/api");
    uploadNslKddDataset.mockRejectedValue(new ApiError(422, "not a well-formed NSL-KDD file"));
    render(<DatasetsPage />);
    selectFile(screen.getByLabelText(/NSL-KDD file/i), "bad.txt", "not,a,valid,row");
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not a well-formed"));
  });
});
