"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { API, STATUS_CLASS, api } from "../lib/api";

const STATUSES = ["Uploaded", "Queued", "Processing", "Needs Review", "Ready for Approval", "Approved", "Failed"];

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [docs, setDocs] = useState({ items: [], total: 0 });
  const [filter, setFilter] = useState("");
  const [msgs, setMsgs] = useState([]);
  const [over, setOver] = useState(false);
  const input = useRef();

  const load = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([api("/stats"), api(`/documents?limit=100${filter ? `&status=${encodeURIComponent(filter)}` : ""}`)]);
      setStats(s); setDocs(d);
    } catch (e) { setMsgs((m) => (m[0]?.text === e.message ? m : [{ kind: "err", text: `Cannot reach API: ${e.message}` }])); }
  }, [filter]);

  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);

  async function upload(files) {
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      try {
        const r = await api("/documents", { method: "POST", body: fd });
        setMsgs((m) => [{ kind: r.duplicate ? "err" : "ok", text: r.duplicate ? `${f.name}: duplicate of existing document (no new job created)` : `${f.name}: accepted` }, ...m].slice(0, 5));
      } catch (e) { setMsgs((m) => [{ kind: "err", text: `${f.name}: ${e.message}` }, ...m].slice(0, 5)); }
    }
    load();
  }

  return (<>
    <div className="card">
      <h1>Dashboard</h1>
      {stats && <div className="grid">
        <div className="stat"><b>{stats.total_documents}</b>Total documents</div>
        {STATUSES.map((s) => <div className="stat" key={s}><b>{stats.by_status[s]}</b><span className={`badge ${STATUS_CLASS[s]}`}>{s}</span></div>)}
        <div className="stat"><b>{stats.duplicates_detected}</b>Duplicates blocked</div>
        <div className="stat"><b>{stats.avg_processing_seconds ?? "–"}{stats.avg_processing_seconds != null && "s"}</b>Avg processing</div>
        <div className="stat"><b>{stats.approval_rate != null ? Math.round(stats.approval_rate * 100) + "%" : "–"}</b>Approval rate</div>
      </div>}
      {stats && Object.keys(stats.issues_by_code).length > 0 && <p className="conf" style={{ marginTop: 12 }}>
        Validation issues: {Object.entries(stats.issues_by_code).map(([c, n]) => `${c} ×${n}`).join(" · ")}</p>}
      {stats?.recent_failures.length > 0 && <div className="msg err" style={{ marginTop: 8 }}>
        Recent failures: {stats.recent_failures.map((f) => <div key={f.id}><Link href={`/documents/${f.id}`}>{f.filename}</Link>: {f.error}</div>)}</div>}
    </div>

    <div className="card">
      <h2>Upload documents (PDF, JPG, PNG)</h2>
      {msgs.map((m, i) => <div key={i} className={`msg ${m.kind}`}>{m.text}</div>)}
      <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload([...e.dataTransfer.files]); }}>
        Drag &amp; drop files here or <button onClick={() => input.current.click()}>Choose files</button>
        <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => { upload([...e.target.files]); e.target.value = ""; }} />
      </div>
    </div>

    <div className="card">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Documents ({docs.total})</h2>
        <div className="row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 190 }}>
            <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <a className="btn secondary" href={`${API}/api/v1/export?format=csv`}>Export approved CSV</a>
          <a className="btn secondary" href={`${API}/api/v1/export?format=json`}>JSON</a>
        </div>
      </div>
      <table><thead><tr><th>File</th><th>Type</th><th>Status</th><th>Error / note</th><th>Uploaded</th></tr></thead><tbody>
        {docs.items.map((d) => <tr key={d.id}>
          <td><Link href={`/documents/${d.id}`}>{d.filename}</Link></td>
          <td>{d.doc_type ?? "–"}</td>
          <td><span className={`badge ${STATUS_CLASS[d.status]}`}>{d.status}</span>{d.retry_count > 0 && <span className="conf"> (retry {d.retry_count})</span>}</td>
          <td>{d.error_message ?? ""}</td><td>{new Date(d.created_at).toLocaleString()}</td></tr>)}
        {docs.items.length === 0 && <tr><td colSpan={5} className="conf">No documents yet.</td></tr>}
      </tbody></table>
    </div>
  </>);
}
