import { FormEvent, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { ago } from "../../lib/format";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { Empty, ErrorNote, Field, Loading, Modal, Seg } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { Icon } from "../../components/Icon";

interface Prop { type: "string" | "number" | "integer" | "boolean"; enum?: string[] }
interface RuleType { required: string[]; props: Record<string, Prop> }
export type Rule = { type: string; [k: string]: unknown };
interface SavedRule extends Rule { id: string; created: number; active: boolean; state?: Record<string, unknown> }

export const AI_OFFLINE = "AI offline — set GEMINI_API_KEY or ANTHROPIC_API_KEY and restart";

const LABELS: Record<string, string> = {
  level_cross: "Price crosses a level", oi_wall_cross: "Spot crosses an OI wall", max_pain_distance: "Spot within % of max pain",
  iv_change: "ATM IV moves by N points", pcr_cross: "PCR crosses a threshold", fii_flip: "FII / DII index-futures net flips",
  futures_buildup_change: "Futures buildup changes", ledger_event: "Adviser ledger opens / settles", new_recommendation: "New adviser recommendation",
  expiry_pin: "Expiry-day pin near max pain", event_upcoming: "Corporate event within N days",
};
const HIDDEN = new Set(["id", "created", "active", "state", "type"]);

/** One line a person can read: "Price crosses a level · NIFTY above 25500". */
export const describeRule = (r: Rule) =>
  `${LABELS[r.type] || r.type.replace(/_/g, " ")}${Object.entries(r).filter(([k, v]) => !HIDDEN.has(k) && v !== undefined && v !== "")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`).reduce((a, b) => `${a}${a ? " · " : " — "}${b}`, "")}`;

/** "+ alert" anywhere in the app: saves the rule straight away and confirms with a toast. */
export function QuickAlert({ rule, title }: { rule: Rule; title?: string }) {
  const { run } = useFeedback();
  return (
    <button type="button" className="mini-btn" title={title || `Alert me: ${describeRule(rule)}`} aria-label={title || "Add alert"}
      onClick={(e) => { e.stopPropagation(); run(() => api.post("/api/alerts", { rule }), { success: `Alert saved: ${describeRule(rule)}` }); }}>
      <Icon name="bell" size={11} />
    </button>
  );
}

type Tab = "feed" | "rules" | "new";

/** Bell drawer: fired alerts, saved rules, and a new-alert form (typed or plain English). */
export function AlertsDrawer({ onClose, initialTab = "feed" }: { onClose: () => void; initialTab?: Tab }) {
  const { unread } = useStore();
  const [tab, setTab] = useState<Tab>(initialTab);
  const cfg = usePoll<{ rules?: SavedRule[]; rule_types?: Record<string, RuleType> }>("/api/alerts", 30000);
  return (
    <Modal drawer title={<span className="row"><Icon name="bell" />Alerts</span>} onClose={onClose}>
      <Seg value={tab} onChange={setTab} full options={[
        { value: "feed", label: `Fired${unread ? ` (${unread})` : ""}` },
        { value: "rules", label: `Rules${cfg.data?.rules?.length ? ` (${cfg.data.rules.length})` : ""}` },
        { value: "new", label: "New alert" },
      ]} />
      <ErrorNote error={cfg.error} onRetry={cfg.reload} />
      {tab === "feed" && <Feed />}
      {tab === "rules" && (cfg.loading && !cfg.data ? <Loading /> : <Rules rules={cfg.data?.rules || []} reload={cfg.reload} onNew={() => setTab("new")} />)}
      {tab === "new" && (cfg.loading && !cfg.data ? <Loading /> :
        <NewAlert types={cfg.data?.rule_types || {}} onSaved={() => { cfg.reload(); setTab("rules"); }} />)}
      <div className="faint" style={{ fontSize: 12 }}>Alerts only notify you. Nothing here places or changes orders.</div>
    </Modal>
  );
}

function Feed() {
  const { alerts, markAcked, reloadAlerts } = useStore();
  const { toast } = useFeedback();
  const ack = async (ids: number[]) => {
    if (!ids.length) return;
    try { await api.post("/api/alerts/ack", { ids }); markAcked(ids); }
    catch (e: any) { toast("down", "Could not acknowledge", e?.message); reloadAlerts(); }
  };
  const open = alerts.filter((a) => !a.acked);
  if (!alerts.length) return <Empty title="No alerts fired in the last 7 days" icon="bell">Create a rule under “New alert”, or use the bell buttons next to OI walls, max pain, futures and events.</Empty>;
  return (
    <div className="stack">
      <div className="row between">
        <span className="faint" style={{ fontSize: 12 }}>{open.length} unread · last 7 days</span>
        <button className="btn sm" disabled={!open.length} onClick={() => ack(open.map((a) => a.id))}>Acknowledge all</button>
      </div>
      {alerts.map((a) => (
        <div key={a.id} className={`alert-item ${a.acked ? "acked" : ""}`}>
          <div className="row between" style={{ gap: 8 }}>
            <b style={{ fontSize: 13 }}>{a.message}</b>
            {!a.acked && <button className="btn ghost sm" onClick={() => ack([a.id])}>Ack</button>}
          </div>
          <div className="row wrap" style={{ gap: 6, fontSize: 12 }}>
            <span className="faint">{ago(a.ts)} · {a.type.replace(/_/g, " ")}</span>
            <ProvBadge prov={a.prov} loading={false} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Rules({ rules, reload, onNew }: { rules: SavedRule[]; reload: () => void; onNew: () => void }) {
  const { run } = useFeedback();
  if (!rules.length) return <Empty title="No alert rules" icon="bell"><button className="btn sm primary" onClick={onNew}>New alert</button></Empty>;
  return (
    <div className="list card">
      {rules.map((r) => (
        <div key={r.id} className="list-item">
          <div className="grow" style={{ fontSize: 13 }}>{describeRule(r)}
            <div className="faint" style={{ fontSize: 11.5 }}>created {ago(r.created)}{r.active ? "" : " · paused"}</div>
          </div>
          <button className="btn danger sm" onClick={async () => {
            await run(() => api.post("/api/alerts/delete", { id: r.id }), { success: "Alert rule deleted" });
            reload();
          }}>Delete</button>
        </div>
      ))}
    </div>
  );
}

function NewAlert({ types, onSaved }: { types: Record<string, RuleType>; onSaved: () => void }) {
  const { toast } = useFeedback();
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<{ rules: Rule[]; errors: string[]; unparsed?: string[] } | null>(null);
  const save = async (rule: Rule) => {
    try {
      await api.post("/api/alerts", { rule });
      toast("up", "Alert saved", describeRule(rule));
      return true;
    } catch (e: any) {
      toast("down", "Alert not saved", e?.message);
      return false;
    }
  };
  const parse = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setParsing(true); setParsed(null);
    try {
      const r = await api.post<{ rules?: Rule[]; errors?: string[]; unparsed?: string[] }>("/api/ai/alerts/parse", { text });
      setParsed({ rules: r.rules || [], errors: r.errors || [], unparsed: r.unparsed });
    } catch (ex: any) {
      setParsed({ rules: [], errors: [ex?.message || "Parse failed"] });
    } finally { setParsing(false); }
  };
  const offline = parsed?.errors.some((x) => /no AI provider|not configured|offline/i.test(x));
  return (
    <div className="stack" style={{ gap: 18 }}>
      <form className="stack" onSubmit={parse}>
        <Field label="Describe it in plain English">
          <textarea className="input" style={{ height: 64, padding: 10, resize: "vertical" }} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Tell me if NIFTY breaks 25,500 or IV jumps 2 points" />
        </Field>
        <button className="btn sm" style={{ justifySelf: "start" }} disabled={parsing || !text.trim()}>{parsing ? "Reading…" : "Parse with AI"}</button>
        {parsed && (
          <div className="stack">
            {offline ? <div className="alert warn">{AI_OFFLINE}. Use the form below instead.</div>
              : parsed.errors.map((x, i) => <div key={i} className="alert warn">{x}</div>)}
            {parsed.unparsed?.length ? <div className="faint" style={{ fontSize: 12.5 }}>Not understood: {parsed.unparsed.join("; ")}</div> : null}
            {parsed.rules.length > 0 && <div className="faint" style={{ fontSize: 12.5 }}>Check each rule before saving; nothing is saved until you confirm.</div>}
            {parsed.rules.map((r, i) => (
              <div key={i} className="row between card" style={{ padding: 10 }}>
                <span style={{ fontSize: 13 }}>{describeRule(r)}</span>
                <button className="btn primary sm" onClick={async () => {
                  if (await save(r)) setParsed((p) => p && { ...p, rules: p.rules.filter((_, j) => j !== i) });
                }}>Save</button>
              </div>
            ))}
            {parsed.rules.length > 1 && <button className="btn sm" style={{ justifySelf: "start" }} onClick={async () => {
              for (const r of parsed.rules) await save(r);
              onSaved();
            }}>Save all {parsed.rules.length}</button>}
          </div>
        )}
      </form>
      <RuleForm types={types} onSave={async (r) => { if (await save(r)) onSaved(); }} />
    </div>
  );
}

function RuleForm({ types, onSave }: { types: Record<string, RuleType>; onSave: (r: Rule) => void }) {
  const names = Object.keys(types);
  const { alertDraft, setAlertDraft } = useStore();
  const [type, setType] = useState(() => String(alertDraft?.type || names[0] || "level_cross"));
  const [vals, setVals] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(Object.entries(alertDraft || {}).filter(([k]) => k !== "type").map(([k, v]) => [k, typeof v === "boolean" ? v : String(v)])));
  useEffect(() => { if (alertDraft) setAlertDraft(null); }, [alertDraft, setAlertDraft]);
  const spec = types[type];
  if (!spec) return <Empty title="Rule types unavailable" />;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const rule: Rule = { type };
    for (const [k, p] of Object.entries(spec.props)) {
      const v = vals[k];
      if (v === undefined || v === "") continue;
      rule[k] = p.type === "number" || p.type === "integer" ? Number(v) : v;
    }
    onSave(rule);
  };
  return (
    <form className="stack card" style={{ padding: 14 }} onSubmit={submit}>
      <b style={{ fontSize: 13 }}>Or build it yourself</b>
      <Field label="Alert when">
        <select className="select" value={type} onChange={(e) => { setType(e.target.value); setVals({}); }}>
          {names.map((n) => <option key={n} value={n}>{LABELS[n] || n}</option>)}
        </select>
      </Field>
      <div className="grid cols-2" style={{ gap: 10 }}>
        {Object.entries(spec.props).map(([k, p]) => {
          const req = spec.required.includes(k);
          const label = `${k.replace(/_/g, " ")}${req ? " *" : ""}`;
          if (p.type === "boolean")
            return <label key={k} className="row" style={{ gap: 8, fontSize: 13 }}>
              <input type="checkbox" checked={!!vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.checked })} />{label}</label>;
          return (
            <Field key={k} label={label}>
              {p.enum ? (
                <select className="select" required={req} value={String(vals[k] ?? "")} onChange={(e) => setVals({ ...vals, [k]: e.target.value })}>
                  <option value="">—</option>
                  {p.enum.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input className={`input ${p.type === "string" ? "" : "mono"}`} required={req} inputMode={p.type === "string" ? "text" : "decimal"}
                  type={p.type === "string" ? "text" : "number"} step={p.type === "integer" ? 1 : "any"}
                  placeholder={k === "symbol" ? "NIFTY" : ""} value={String(vals[k] ?? "")} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />
              )}
            </Field>
          );
        })}
      </div>
      <button className="btn primary sm" style={{ justifySelf: "start" }}>Save alert</button>
    </form>
  );
}

/** Bell with unread count for the top bar. */
export function AlertBell() {
  const { unread, setPanel } = useStore();
  return (
    <button className="btn ghost icon-btn bell" onClick={() => setPanel("alerts")} aria-label={`Alerts${unread ? `, ${unread} unread` : ""}`} data-tour="bell">
      <Icon name="bell" />
      {unread > 0 && <span className="count">{unread > 99 ? "99+" : unread}</span>}
    </button>
  );
}
