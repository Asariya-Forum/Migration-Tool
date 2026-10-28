
"use client";

import { useEffect, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000/api/v1";

type Metadata = {
  title?: string;
  author?: string;
  publisher?: string;
  category?: string;
  [key: string]: any;
};

type Job = {
  id: string;
  filename: string;
  size_bytes: number;
  status: string;
  stage: string;
  message: string;
  metadata: Metadata;
  output_available: boolean;
  created_at: string | null;
};

type MetadataForm = {
  title: string;
  author: string;
  publisher: string;
  category: string;
};

const emptyMetadata: MetadataForm = {
  title: "",
  author: "",
  publisher: "",
  category: "",
};

function metadataFormFromJob(job: Job): MetadataForm {
  return {
    title: job.metadata?.title || "",
    author: job.metadata?.author || "",
    publisher: job.metadata?.publisher || "",
    category: job.metadata?.category || "",
  };
}

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [savingId, setSavingId] = useState("");
  const [editingId, setEditingId] = useState("");
  const [metadataForm, setMetadataForm] =
    useState<MetadataForm>(emptyMetadata);
  const [note, setNote] = useState("");

  async function refresh() {
    try {
      const response = await fetch(`${API}/jobs`);

      if (!response.ok) {
        throw new Error(await response.text());
      }

      setJobs(await response.json());
    } catch {
      setNote(
        "API connection failed. Start the FastAPI backend and check .env.local."
      );
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function upload() {
    if (!files?.length) return;

    setBusy(true);
    setNote("Uploading PDFs…");

    try {
      const form = new FormData();
      Array.from(files).forEach((file) =>
        form.append("files", file)
      );

      const response = await fetch(`${API}/jobs/upload`, {
        method: "POST",
        body: form,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed");
      }

      setNote(`Uploaded ${data.jobs.length} PDF(s).`);
      setFiles(null);

      const fileInput = document.getElementById(
        "pdf-upload"
      ) as HTMLInputElement | null;

      if (fileInput) fileInput.value = "";

      await refresh();
    } catch (error: any) {
      setNote(error.message || "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function process(id: string) {
    setBusy(true);
    setNote(
      "Processing started. Large PDFs may hit the configured 20-second limit."
    );

    try {
      const response = await fetch(`${API}/jobs/${id}/process`, {
        method: "POST",
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Processing failed");
      }

      setNote(
        `${data.filename}: ${data.status} — ${data.message}`
      );

      await refresh();
    } catch (error: any) {
      setNote(error.message || "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  function startEditing(job: Job) {
    setEditingId(job.id);
    setMetadataForm(metadataFormFromJob(job));
    setNote("");
  }

  function cancelEditing() {
    setEditingId("");
    setMetadataForm(emptyMetadata);
  }

  function updateField(
    field: keyof MetadataForm,
    value: string
  ) {
    setMetadataForm((previous) => ({
      ...previous,
      [field]: value,
    }));
  }

  async function saveMetadata(id: string) {
    setSavingId(id);
    setNote("Saving metadata…");

    try {
      const response = await fetch(
        `${API}/jobs/${id}/metadata`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(metadataForm),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Metadata save failed. Check the backend endpoint."
        );
      }

      setJobs((previous) =>
        previous.map((job) =>
          job.id === id ? data : job
        )
      );

      setEditingId("");
      setMetadataForm(emptyMetadata);
      setNote(`Metadata saved for ${data.filename}.`);
    } catch (error: any) {
      setNote(error.message || "Metadata save failed");
    } finally {
      setSavingId("");
    }
  }

  return (
    <main>
      <aside>
        <div className="brand">
          ◈ AsariyaForum
          <span>Digital Library</span>
        </div>

        <nav>
          <b>▣ Bulk Migration Utility</b>
          <span>Metadata Inspector</span>
          <span>PDF Sanitizer</span>
          <span>Processing Queue</span>
          <span>Logs & Reports</span>
          <span>Settings</span>
        </nav>

        <footer>
          KNOWLEDGE • FAITH • SERVICE
          <br />
          Local workspace
        </footer>
      </aside>

      <section className="main">
        <header>
          <div>
            <small>ADMIN WORKSPACE / DIGITAL LIBRARY</small>
            <h1>Bulk Migration Utility</h1>
            <p>
              Upload, inspect, process and review PDF books locally.
            </p>
          </div>

          <div className="pill">● Local storage</div>
        </header>

        <div className="stats">
          <article>
            <small>Total jobs</small>
            <strong>{jobs.length}</strong>
          </article>

          <article>
            <small>Needs review</small>
            <strong>
              {jobs.filter((job) => job.status === "needs_review").length}
            </strong>
          </article>

          <article>
            <small>Completed</small>
            <strong>
              {jobs.filter((job) => job.status === "completed").length}
            </strong>
          </article>

          <article>
            <small>Failed / timeout</small>
            <strong>
              {
                jobs.filter((job) =>
                  ["failed", "timeout"].includes(job.status)
                ).length
              }
            </strong>
          </article>
        </div>

        <div className="panel">
          <h2>Upload PDF books</h2>
          <p className="muted">
            Select multiple PDFs. Originals remain in staging;
            processed copies are written to output.
          </p>

          <input
            id="pdf-upload"
            type="file"
            accept="application/pdf,.pdf"
            multiple
            onChange={(event) =>
              setFiles(event.target.files)
            }
          />

          <button
            disabled={busy || !files?.length}
            onClick={upload}
          >
            {busy
              ? "Please wait…"
              : `Upload ${files?.length || 0} file(s)`}
          </button>

          <button
            className="secondary"
            disabled={busy}
            onClick={refresh}
          >
            Refresh queue
          </button>

          {note && <p className="notice">{note}</p>}
        </div>

        <div className="panel">
          <div className="panelhead">
            <div>
              <h2>Migration Queue</h2>
              <p className="muted">
                Review metadata before processing and publication.
              </p>
            </div>

            <span>{jobs.length} jobs</span>
          </div>

          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Metadata clues</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <b>{job.filename}</b>
                      <small>
                        {(job.size_bytes / 1048576).toFixed(1)} MB
                      </small>
                    </td>

                    <td>
                      <span className={`status ${job.status}`}>
                        {job.status.replace("_", " ")}
                      </span>
                    </td>

                    <td>{job.stage}</td>

                    <td>
                      {job.metadata?.title || "Title unknown"}
                      <small>
                        Author: {job.metadata?.author || "Needs review"}
                      </small>
                      <small>
                        Publisher: {job.metadata?.publisher || "Not set"}
                      </small>
                      <small>
                        Category: {job.metadata?.category || "Not set"}
                      </small>
                    </td>

                    <td>
                      <button
                        className="small"
                        disabled={busy || !!savingId}
                        onClick={() => startEditing(job)}
                      >
                        Edit Metadata
                      </button>

                      <br />

                      <button
                        className="small"
                        disabled={busy || !!savingId}
                        onClick={() => process(job.id)}
                      >
                        Process copy
                      </button>

                      {job.output_available && (
                        <>
                          <br />
                          <a
                            className="download"
                            href={`${API}/jobs/${job.id}/download`}
                          >
                            Download
                          </a>
                        </>
                      )}
                    </td>
                  </tr>
                ))}

                {!jobs.length && (
                  <tr>
                    <td colSpan={5}>
                      <p className="empty">
                        No PDFs uploaded yet.
                      </p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {editingId && (
          <div className="panel">
            <div className="panelhead">
              <div>
                <h2>Edit Book Metadata</h2>
                <p className="muted">
                  Values are editable. Save to store them in the database.
                </p>
              </div>

              <button
                className="secondary"
                disabled={!!savingId}
                onClick={cancelEditing}
              >
                Cancel
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "16px",
              }}
            >
              <label>
                Title
                <input
                  type="text"
                  value={metadataForm.title}
                  onChange={(event) =>
                    updateField("title", event.target.value)
                  }
                  placeholder="Book title"
                />
              </label>

              <label>
                Author
                <input
                  type="text"
                  value={metadataForm.author}
                  onChange={(event) =>
                    updateField("author", event.target.value)
                  }
                  placeholder="Author name"
                />
              </label>

              <label>
                Publisher
                <input
                  type="text"
                  value={metadataForm.publisher}
                  onChange={(event) =>
                    updateField("publisher", event.target.value)
                  }
                  placeholder="Publisher name"
                />
              </label>

              <label>
                Category
                <input
                  type="text"
                  value={metadataForm.category}
                  onChange={(event) =>
                    updateField("category", event.target.value)
                  }
                  placeholder="e.g. Hadith, Fiqh, Tafsir"
                />
              </label>
            </div>

            <p className="muted">
              Metadata is saved for the selected job. This does not
              overwrite the original PDF.
            </p>

            <button
              disabled={!!savingId}
              onClick={() => saveMetadata(editingId)}
            >
              {savingId === editingId
                ? "Saving…"
                : "Save Metadata"}
            </button>
          </div>
        )}

        <div className="footnote">
          Safety: scanned-page branding cannot be reliably removed
          automatically. Review every output before publication.
          The app will not label a job completed when processing
          needs review.
        </div>
      </section>
    </main>
  );
}
