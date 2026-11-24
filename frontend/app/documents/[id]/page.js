"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { API, STATUS_CLASS, api } from "../../../lib/api";

const SCALARS = [["document_number", "Document number"], ["document_date", "Date (YYYY-MM-DD)"], ["supplier_name", "Supplier"],
  ["customer_name", "Customer"], ["currency", "Currency (ISO)"], ["subtotal", "Subtotal"], ["discount", "Discount"], ["tax", "Tax"], ["total", "Total"]];
const DOC_TYPES = [["invoice", "Invoice"], ["receipt", "Receipt"], ["purchase_order", "Purchase order"], ["unknown", "Unknown"]];
const ITEM_COLS = [["description", "Description"], ["quantity", "Qty"], ["unit_price", "Unit price"], ["amount", "Amount"]];
const LOW = 70;

export default function Review({ params }) {
  const { id } = use(params);
  const [doc, setDoc] = useState(null);
  const [form, setForm] = useState(null);
  const [events, setEvents] = useState([]);
  const [acks, setAcks] = useState({});
  const [note, setNote] = useState("");
  const [actor, setActor] = useState("reviewer");
  const [docType, setDocType] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (resetForm = true) => {
    const [d, ev] = await Promise.all([api(`/documents/${id}`), api(`/documents/${id}/audit`)]);
    setDoc(d); setEvents(ev);
    setDocType(d.doc_type ?? "unknown");
    if (resetForm) setForm(structuredClone(d.data));
    return d;
  }, [id]);

  useEffect(() => { load().catch((e) => setMsg({ kind: "err", text: e.message })); }, [load]);
  useEffect(() => { // poll while the document is still being processed
    if (!doc || !["Uploaded", "Queued", "Processing"].includes(doc.status)) return;
    const t = setInterval(() => load().catch(() => {}), 2000); return () => clearInterval(t);
  }, [doc, load]);

  async function act(fn, okText) {
    setBusy(true); setMsg(null);
    try { await fn(); await load(); if (okText) setMsg({ kind: "ok", text: okText }); }
    catch (e) {
      const un = e.detail?.unresolved;
      setMsg({ kind: "err", text: un ? `${e.message}: ${un.map((u) => u.code + (u.field ? ` (${u.field})` : "")).join(", ")}` : e.message });
    } finally { setBusy(false); }
  }

  if (!doc) return <div className="card">{msg ? <div className="msg err">{msg.text}</div> : "Loading…"}</div>;
  const editable = ["Needs Review", "Ready for Approval"].includes(doc.status);
  const orig = doc.extracted || {};
  const conf = doc.confidence || {};
  const open = doc.issues.filter((i) => !i.acknowledged);
  const changed = JSON.stringify(form) !== JSON.stringify(doc.data) || docType !== (doc.doc_type ?? "unknown");
  const setScalar = (k, v) => setForm({ ...form, [k]: v === "" ? null : v });
  const setItem = (i, k, v) => { const items = structuredClone(form.line_items); items[i][k] = v === "" ? null : v; setForm({ ...form, line_items: items }); };
  const addRow = () => setForm({ ...form, line_items: [...(form.line_items || []), { description: null, quantity: null, unit_price: null, amount: null }] });
  const delRow = (i) => setForm({ ...form, line_items: form.line_items.filter((_, j) => j !== i) });
  const Conf = ({ path }) => path in conf ? <span className={`conf ${conf[path] != null && conf[path] < LOW ? "low" : ""}`}>{conf[path] == null ? "confidence: unavailable" : `confidence ${conf[path].toFixed(0)}%`}</span> : null;

  const save = () => act(() => api(`/documents/${id}`, { method: "PATCH", body: JSON.stringify({ fields: form, doc_type: docType, actor }) }), "Corrections saved and revalidated.");
  const approve = () => act(() => api(`/documents/${id}/approve`, { method: "POST", body: JSON.stringify({ actor, note: note || null, acknowledged_issue_ids: Object.keys(acks).filter((k) => acks[k]).map(Number) }) }), "Document approved.");

  return (<>
    <p><Link href="/">← Dashboard</Link></p>
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div><h1>{doc.filename}</h1>
          <span className={`badge ${STATUS_CLASS[doc.status]}`}>{doc.status}</span>{" "}
          <span className="conf">type: {doc.doc_type ?? "–"} {doc.classification_confidence != null && `(${Math.round(doc.classification_confidence * 100)}%)`} · extractor: {doc.extractor ?? "–"} · OCR: {doc.ocr_method ?? "–"}
            {doc.ocr_mean_confidence != null && ` (mean ${doc.ocr_mean_confidence}%)`} · retries: {doc.retry_count}</span><br /><small className="mono">sha256 {doc.sha256}</small></div>
        <div className="row">
          <a className="btn secondary" href={`${API}/api/v1/documents/${id}/file`} target="_blank" rel="noreferrer">Original file</a>
          {doc.status === "Approved" && <><a className="btn" href={`${API}/api/v1/documents/${id}/export?format=json`}>Export JSON</a>
            <a className="btn" href={`${API}/api/v1/documents/${id}/export?format=csv`}>Export CSV</a></>}
          {["Failed", "Uploaded"].includes(doc.status) && <button disabled={busy} onClick={() => act(() => api(`/documents/${id}/retry`, { method: "POST" }), "Retry queued.")}>Retry processing</button>}
        </div>
      </div>
      {doc.error_message && <div className="msg err" style={{ marginTop: 12 }}>Error: {doc.error_message}</div>}
      {msg && <div className={`msg ${msg.kind}`} style={{ marginTop: 12 }}>{msg.text}</div>}
    </div>

    {doc.issues.length > 0 && <div className="card"><h2>Validation issues ({open.length} open)</h2>
      {doc.issues.map((i) => <div key={i.id} className={`issue ${i.severity} ${i.acknowledged ? "ack" : ""}`}>
        <div className="row">
          {editable && !i.acknowledged && <input type="checkbox" style={{ width: 16 }} checked={!!acks[i.id]} onChange={(e) => setAcks({ ...acks, [i.id]: e.target.checked })} title="Acknowledge (accept as-is)" />}
          <b>{i.code}</b><span className="conf">{i.severity}{i.field ? ` · ${i.field}` : ""}</span>
          {i.acknowledged && <span className="conf">acknowledged by {i.acknowledged_by}: {i.acknowledged_note}</span>}
        </div>{i.message}</div>)}
      {editable && open.length > 0 && <p className="conf">Correct the fields below, or tick an issue to accept it as-is (a note is then required to approve).</p>}
    </div>}

    {form && <div className="card"><h2>Extracted fields</h2>
      {editable && <div style={{ maxWidth: 320, marginBottom: 12 }}><label>Document type</label><select value={docType ?? "unknown"} onChange={(e) => setDocType(e.target.value)}>{DOC_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>}
      <div className="two">{SCALARS.map(([k, label]) => <div key={k}>
        <label>{label} <Conf path={k} /></label>
        <input disabled={!editable} value={form[k] ?? ""} placeholder="(not found)"
          className={`${form[k] !== doc.data[k] ? "changed" : ""} ${conf[k] != null && conf[k] < LOW ? "low" : ""}`} onChange={(e) => setScalar(k, e.target.value)} />
        {orig[k] !== doc.data[k] && <div className="orig">original: {orig[k] ?? "(empty)"}</div>}</div>)}</div>
      <h2 style={{ marginTop: 16 }}>Line items</h2>
      <table><thead><tr>{ITEM_COLS.map(([, l]) => <th key={l}>{l}</th>)}<th /></tr></thead><tbody>
        {(form.line_items || []).map((it, i) => <tr key={i}>
          {ITEM_COLS.map(([k]) => <td key={k}><input disabled={!editable} value={it[k] ?? ""}
            className={`${it[k] !== doc.data.line_items?.[i]?.[k] ? "changed" : ""} ${conf[`line_items.${i}.${k}`] != null && conf[`line_items.${i}.${k}`] < LOW ? "low" : ""}`} onChange={(e) => setItem(i, k, e.target.value)} />
            <Conf path={`line_items.${i}.${k}`} />{orig.line_items?.[i]?.[k] !== doc.data.line_items?.[i]?.[k] && <div className="orig">original: {orig.line_items?.[i]?.[k] ?? "(empty)"}</div>}</td>)}
          <td>{editable && <button className="secondary" onClick={() => delRow(i)}>✕</button>}</td></tr>)}
        {!form.line_items?.length && <tr><td colSpan={5} className="conf">No line items found.</td></tr>}
      </tbody></table>
      {editable && <div className="row" style={{ marginTop: 12 }}>
        <button className="secondary" onClick={addRow}>+ Add line</button>
        <input style={{ width: 160 }} value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Your name" aria-label="Reviewer name" />
        <button disabled={busy || !changed} onClick={save}>Save corrections</button>
        <button className="secondary" disabled={!changed} onClick={() => { setForm(structuredClone(doc.data)); setDocType(doc.doc_type ?? "unknown"); }}>Discard</button>
      </div>}
    </div>}

    {editable && <div className="card"><h2>Approval</h2>
      <div className="row">
        <input placeholder="Note (required when accepting issues as-is)" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} />
        <button disabled={busy || changed} onClick={approve}>Approve</button></div>
      {changed && <p className="conf">Save your corrections before approving.</p>}
    </div>}

    {doc.ocr_text && <details className="card"><summary><b>Raw OCR / extracted text</b></summary><pre style={{ whiteSpace: "pre-wrap" }}>{doc.ocr_text}</pre></details>}

    <div className="card"><h2>Audit trail ({events.length})</h2>
      <table><thead><tr><th>Time</th><th>Event</th><th>Field</th><th>Original → New</th><th>Actor</th><th>Details</th></tr></thead><tbody>
        {events.map((e) => <tr key={e.id}><td>{new Date(e.created_at).toLocaleString()}</td><td>{e.event_type}</td><td>{e.field ?? ""}</td>
          <td>{(e.old_value != null || e.new_value != null) && `${JSON.stringify(e.old_value)} → ${JSON.stringify(e.new_value)}`}</td>
          <td>{e.actor}</td><td className="conf">{e.details ? JSON.stringify(e.details).slice(0, 160) : ""}</td></tr>)}
      </tbody></table>
    </div>
  </>);
}
