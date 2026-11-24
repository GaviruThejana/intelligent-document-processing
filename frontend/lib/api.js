export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function api(path, opts = {}) {
  const res = await fetch(`${API}/api/v1${path}`, {
    ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json", ...opts.headers } : opts.headers,
  });
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch {}
    const d = body?.detail;
    const err = new Error(typeof d === "string" ? d : d?.message || res.statusText);
    err.status = res.status; err.detail = d;
    throw err;
  }
  return res.json();
}

export const STATUS_CLASS = {
  "Uploaded": "gray", "Queued": "gray", "Processing": "blue", "Needs Review": "amber",
  "Ready for Approval": "green", "Approved": "dark", "Failed": "red",
};
