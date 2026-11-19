import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, qs } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { Icon } from "../../components/Icon";
import { Badge, Modal } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { AI_OFFLINE } from "../alerts/Alerts";
import { tidyExplain } from "../../components/Explain";
import type { Prov } from "../markets/logic";

interface Citation { tool?: string; source?: string; kind?: string; age_sec?: number | null; as_of?: number | string | null; note?: string }
interface ChatOut {
  answer?: string; citations?: Citation[]; followups?: string[]; tools_used?: { name: string; args?: unknown }[];
  guarded?: boolean; stop_reason?: string; provider?: string | null; model?: string | null; available?: boolean; error?: string;
}
interface Msg { role: "user" | "ai"; text: string; steps?: string[]; citations?: Citation[]; followups?: string[]; via?: string; pending?: boolean }
interface AiStatus { provider?: string | null; model?: string | null; available?: boolean }

const SESSION_KEY = "hm.ai.session";
const sessionId = () => {
  try {
    let s = localStorage.getItem(SESSION_KEY);
    if (!s) { s = Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem(SESSION_KEY, s); }
    return s;
  } catch { return undefined; }
};

/** Minimal, safe markdown: **bold**, `code`, line breaks. Rendered as React nodes, never as HTML. */
function Rich({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, i) => (
        <div key={i} style={{ minHeight: 6 }}>
          {line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, j) =>
            part.startsWith("**") ? <b key={j}>{part.slice(2, -2)}</b>
              : part.startsWith("`") ? <code key={j} className="mono">{part.slice(1, -1)}</code>
                : <span key={j}>{part}</span>)}
        </div>
      ))}
    </>
  );
}

/** POST + text/event-stream (EventSource cannot POST): `tool` frames, then one `answer`, then `done`. */
async function streamChat(body: unknown, onTool: (name: string) => void): Promise<ChatOut> {
  const res = await fetch("/api/ai/chat/stream", {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", answer: ChatOut | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const ev = /^event: (.*)$/m.exec(frame)?.[1]?.trim();
      const data = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
      if (!data) continue;
      try {
        const d = JSON.parse(data);
        if (ev === "tool") onTool(String(d.name || "tool"));
        else if (ev === "answer") answer = d;
      } catch { /* partial or malformed frame */ }
    }
    if (done) break;
  }
  if (!answer) throw new Error("The stream ended without an answer");
  return answer;
}

const SpeechRec: any = typeof window !== "undefined" ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : undefined;

export function Copilot({ section }: { section: string }) {
  const { symbol, panel, setPanel, aiPrompt, clearAiPrompt, pageCtx } = useStore();
  const open = panel === "copilot";
  const status = usePoll<AiStatus>("/api/ai/status", open ? 120000 : 0);
  const ai = status.data?.available === true;
  const [q, setQ] = useState("");
  const [log, setLog] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const rec = useRef<any>(null);
  const end = useRef<HTMLDivElement>(null);
  const ctxSymbol = pageCtx.symbol || symbol;

  // Braces matter: newer browsers return a Promise from scrollIntoView, which React would call as a cleanup.
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [log, busy]);

  const update = (fn: (m: Msg) => Msg) => setLog((l) => [...l.slice(0, -1), fn(l[l.length - 1])]);

  const ask = useCallback(async (preset?: string) => {
    const query = (preset ?? q).trim();
    if (!query || busy) return;
    setQ("");
    setLog((l) => [...l, { role: "user", text: query }, { role: "ai", text: "", steps: [], pending: true }]);
    setBusy(true);
    const context = { symbol: ctxSymbol, market: pageCtx.market || (section === "markets" ? "IN" : undefined), page: section, expiry: pageCtx.expiry };
    try {
      if (ai) {
        const r = await streamChat({ message: query, session_id: sessionId(), context },
          (name) => update((m) => ({ ...m, steps: [...(m.steps || []), name] })));
        const text = r.error && !r.answer ? `AI error: ${r.error}` : r.answer || "No answer.";
        update((m) => ({ ...m, pending: false, text, citations: r.citations, followups: r.followups,
          steps: m.steps?.length ? m.steps : (r.tools_used || []).map((t) => t.name), via: [r.provider, r.model].filter(Boolean).join(" · ") }));
      } else {
        // Offline: "Explain X" goes to the definitions endpoint; everything else to the rule-based copilot.
        const ex = /^explain\s+(.+)$/i.exec(query);
        if (ex) {
          const r = await api.get<{ text: string; source: string }>(`/api/ai/explain${qs({ metric: ex[1].trim(), symbol: ctxSymbol })}`);
          update((m) => ({ ...m, pending: false, text: tidyExplain(r.text), via: r.source === "none" ? "no definition" : "built-in definitions" }));
        } else {
          const r = await api.post<{ response?: string; answer?: string }>("/api/copilot/ask", { query, context: { symbol: ctxSymbol, view: section } });
          update((m) => ({ ...m, pending: false, text: r.response || r.answer || "No answer.", via: "rule-based copilot" }));
        }
      }
    } catch (err: any) {
      update((m) => ({ ...m, pending: false, text: `Copilot unavailable: ${err?.message || err}` }));
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, busy, ai, ctxSymbol, section, pageCtx]);

  // A prompt handed over from the command palette or elsewhere: ask once status is known.
  useEffect(() => {
    if (open && aiPrompt && (status.data !== undefined || status.error)) {
      clearAiPrompt();
      if (/^explain$/i.test(aiPrompt.trim())) setQ("Explain ");
      else ask(aiPrompt);
    }
  }, [open, aiPrompt, status.data, status.error, ask, clearAiPrompt]);

  const listen = () => {
    if (listening) { rec.current?.stop(); return; }
    const r = new SpeechRec();
    r.lang = "en-IN"; r.interimResults = true; r.maxAlternatives = 1;
    r.onresult = (e: any) => setQ(Array.from(e.results as ArrayLike<any>).map((x: any) => x[0].transcript).join(""));
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    rec.current = r;
    setListening(true);
    r.start();
  };

  const submit = (e: FormEvent) => { e.preventDefault(); ask(); };
  const close = () => { rec.current?.stop(); setPanel(null); };

  return (
    <>
      <button className="btn primary copilot-fab" onClick={() => setPanel("copilot")} aria-label="Open AI copilot" data-tour="ai">
        <Icon name="chat" /><span className="hide-mobile">Ask AI</span>
      </button>
      {open && (
        <Modal drawer onClose={close}
          title={<span className="row wrap" style={{ gap: 8 }}><Icon name="chat" />AI copilot <span className="badge accent">{ctxSymbol}</span>
            {status.data === undefined && !status.error ? <Badge>checking…</Badge>
              : ai ? <Badge tone="up" dot>{[status.data?.provider, status.data?.model].filter(Boolean).join(" · ")}</Badge>
                : <Badge tone="warn" dot>AI offline</Badge>}</span>}
          footer={
            <form className="row" style={{ width: "100%" }} onSubmit={submit}>
              <input className="input grow" placeholder={`Ask about ${ctxSymbol}, risk, the chain…`} value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
              {SpeechRec && (
                <button type="button" className={`btn icon-btn ${listening ? "primary" : "ghost"}`} onClick={listen}
                  aria-label={listening ? "Stop voice input" : "Voice input"} aria-pressed={listening}><Icon name="mic" /></button>
              )}
              <button className="btn primary" disabled={busy || !q.trim()}>Send</button>
            </form>
          }>
          {status.data && !ai && (
            <div className="alert warn" style={{ fontSize: 12.5 }}>{AI_OFFLINE}. Until then answers come from the rule-based copilot.</div>
          )}
          {!log.length && (
            <div className="stack">
              <div className="faint">{ai ? "Answers cite the live data they used. The AI explains and analyses; it never places orders." : "Answers use the live engine state for the selected symbol."}
                {" "}Context sent: {section}{pageCtx.expiry ? ` · ${pageCtx.expiry}` : ""}.</div>
              {(section === "markets"
                ? [`What is the options market saying about ${ctxSymbol}?`, "Where are the OI walls and max pain?", "How are FIIs positioned in index futures?"]
                : [`Why is ${ctxSymbol} not trading?`, "Summarise my open risk", "Which setup is strongest right now?"]).map((p) => (
                <button key={p} className="chip" style={{ justifySelf: "start" }} onClick={() => ask(p)}>{p}</button>
              ))}
            </div>
          )}
          {log.map((m, i) => (
            <div key={i} className="card" style={{ padding: 12, background: m.role === "user" ? "var(--accent-soft)" : "var(--surface-2)", justifySelf: m.role === "user" ? "end" : "stretch", maxWidth: m.role === "user" ? "92%" : "100%" }}>
              {m.role === "user" ? m.text : (
                <div className="stack" style={{ gap: 6 }}>
                  {!!m.steps?.length && <div className="ai-steps">{m.steps.map((s, j) => <span key={j}>{m.pending && j === m.steps!.length - 1 ? "◌" : "✓"} using tool: {s}</span>)}</div>}
                  {m.pending ? <span className="faint">{m.steps?.length ? "Working…" : "Thinking…"}</span> : <Rich text={m.text} />}
                  {!!m.citations?.length && (
                    <div className="ai-cites">
                      {m.citations.map((c, j) => <ProvBadge key={j} loading={false} label={c.tool} prov={{ source: c.source, kind: c.kind, age_sec: c.age_sec, as_of: c.as_of, note: c.note } as Prov} />)}
                    </div>
                  )}
                  {!!m.followups?.length && i === log.length - 1 && (
                    <div className="row wrap" style={{ gap: 6 }}>{m.followups.map((f) => <button key={f} className="chip" onClick={() => ask(f)}>{f}</button>)}</div>
                  )}
                  {m.via && !m.pending && <div className="faint" style={{ fontSize: 11 }}>{m.via}</div>}
                </div>
              )}
            </div>
          ))}
          <div ref={end} />
          {log.length > 0 && <button className="btn ghost sm" style={{ justifySelf: "start" }} disabled={busy} onClick={() => {
            setLog([]);
            try { localStorage.removeItem(SESSION_KEY); } catch { /* storage blocked */ }
          }}>New conversation</button>}
        </Modal>
      )}
    </>
  );
}
