import { useMemo, useState } from "react";
import { useStore } from "../../state/store";
import { price } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, sideTone } from "../../components/ui";

const CLASSES = ["ALL", "FOREX", "COMMODITY", "CRYPTO", "INDEX"];

/** The one symbol list on the desk. Enabling/disabling symbols for the engine is in System › Symbols. */
export function Watchlist() {
  const { symbols, symbol, setSymbol, symbolsError, reloadSymbols } = useStore();
  const [cls, setCls] = useState("ALL");
  const [q, setQ] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(true);

  const rows = useMemo(() => symbols
    .filter((s) => (cls === "ALL" || s.asset_class === cls) && (!enabledOnly || s.is_enabled || s.symbol === symbol))
    .filter((s) => !q || s.symbol.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(b.is_enabled) - Number(a.is_enabled) || a.symbol.localeCompare(b.symbol)),
  [symbols, cls, q, enabledOnly, symbol]);

  return (
    <Card title="Watchlist" sub={`${symbols.filter((s) => s.is_enabled).length} traded by the engine`} flush>
      <div className="stack" style={{ padding: 12, gap: 8, borderBottom: "1px solid var(--line)" }}>
        <input className="input" placeholder="Search symbol" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search symbol" />
        <div className="row wrap" style={{ gap: 6 }}>
          {CLASSES.map((c) => (
            <button key={c} className={`chip ${cls === c ? "on" : ""}`} onClick={() => setCls(c)}>{c === "ALL" ? "All" : c.toLowerCase()}</button>
          ))}
          <button className={`chip ${enabledOnly ? "on" : ""}`} onClick={() => setEnabledOnly(!enabledOnly)} title="Show only symbols the engine trades">Traded only</button>
        </div>
      </div>
      <ErrorNote error={symbolsError && `Symbol data stale or unavailable: ${symbolsError}`} onRetry={reloadSymbols} />
      {!rows.length ? <Empty title="No symbols" /> : (
        <div className="list" style={{ maxHeight: 640, overflowY: "auto" }}>
          {rows.map((s) => (
            <div key={s.symbol} className={`list-item clickable ${s.symbol === symbol ? "selected" : ""}`}
              onClick={() => setSymbol(s.symbol)} role="button" tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && setSymbol(s.symbol)}>
              <span className={`dot ${s.is_open ? "up" : ""}`} title={s.is_open ? "Market open" : "Market closed"} />
              <div className="grow">
                <b>{s.symbol}</b>
                <div className="faint" style={{ fontSize: 11.5 }}>spread {s.spread_pips} · {s.decision === "EXECUTE" ? "ready" : s.decision.toLowerCase().replace("_", " ")}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="mono">{s.bid > 0 ? price(s.bid, s.digits) : "—"}</div>
                <Badge tone={sideTone(s.bias)}>{s.bias === "NEUTRAL" || s.bias === "HOLD" ? "flat" : s.bias.toLowerCase()}</Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
