import { useMemo } from "react";
import { useStore } from "../../state/store";
import { api } from "../../lib/api";
import { useFeedback } from "../../components/feedback";
import { ago, cleanSymbol, isNum, price, rMult, signedMoney, tone } from "../../lib/format";
import { Badge, Card, Empty, Loading, sideTone } from "../../components/ui";
import type { Position } from "../../lib/types";

const MODES = ["AUTO_PILOT", "TRAIL", "PROTECT_ONLY", "OFF"] as const;
const MODE_LABEL: Record<string, string> = { AUTO_PILOT: "Auto-pilot", TRAIL: "Trail", PROTECT_ONLY: "Protect only", OFF: "Off" };

/** R multiple from the initial risk (entry→SL); undefined once the stop is at/through entry. */
export const rOf = (p: Position) => {
  if (isNum(p.current_r) && p.current_r !== 0) return p.current_r;
  const risk = Math.abs(p.open_price - p.sl);
  if (!p.sl || risk === 0) return undefined;
  const dir = String(p.type).toUpperCase().includes("BUY") ? 1 : -1;
  return ((p.current_price - p.open_price) * dir) / risk;
};

export function OpenPositions() {
  const { telemetry, symbols, refresh } = useStore();
  const { run } = useFeedback();
  const positions = telemetry?.positions;
  const ccy = telemetry?.account?.currency || "USD";
  const total = useMemo(() => (positions || []).reduce((a, p) => a + (p.profit || 0) + (p.swap || 0) + (p.commission || 0), 0), [positions]);

  if (!telemetry) return <Card title="Open positions"><Loading /></Card>;
  const digitsOf = (s: string) => symbols.find((x) => x.symbol === cleanSymbol(s))?.digits;

  const close = (p: Position) => run(() => api.post("/api/action/close_position", { ticket: p.ticket }), {
    success: `Closed ${cleanSymbol(p.symbol)} #${p.ticket}`,
    confirm: { title: `Close ${cleanSymbol(p.symbol)}?`, danger: true, confirmLabel: "Close position",
      body: <>Close {p.type} {p.volume} {cleanSymbol(p.symbol)} (ticket {p.ticket}) at market. Current P&L {signedMoney(p.profit, ccy)}.</> },
  }).then(refresh);

  const closeAll = () => run(() => api.post<{ closed_count: number }>("/api/action/close_all_positions"), {
    success: "Close-all sent",
    confirm: { title: `Close all ${positions?.length} positions?`, danger: true, confirmLabel: "Close everything",
      body: <>Every open position is closed at market. Combined P&L now {signedMoney(total, ccy)}. This cannot be undone.</> },
  }).then(refresh);

  const setMode = (p: Position, mode: string) => run(() => api.post("/api/action/set_manual_mode", { ticket: p.ticket, mode }), {
    success: `${cleanSymbol(p.symbol)} #${p.ticket}: management set to ${MODE_LABEL[mode]}`,
  }).then(refresh);

  return (
    <Card title="Open positions" sub={<>Floating <span className={tone(total)}>{signedMoney(total, ccy)}</span> incl. swap & commission</>}
      actions={<button className="btn danger sm" disabled={!positions?.length} onClick={closeAll}>Close all</button>} flush>
      {!positions?.length ? <Empty title="No open positions" icon="briefcase" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>Symbol</th><th>Side</th><th className="r">Lots</th><th className="r">Entry</th><th className="r">Price</th>
                <th className="r">Stop</th><th className="r">Target</th><th className="r">R</th><th className="r">P&L</th><th>Management</th><th>Opened</th><th /></tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const d = digitsOf(p.symbol);
                const r = rOf(p);
                const mode = p.monitoring_mode || "AUTO_PILOT";
                const ft = String(p.comment || "").startsWith("FT_");
                return (
                  <tr key={p.ticket}>
                    <td><b>{cleanSymbol(p.symbol)}</b><div className="faint" style={{ fontSize: 11.5 }}>#{p.ticket}{ft ? " · forward test" : p.is_manual ? " · manual" : ""}</div></td>
                    <td><Badge tone={sideTone(p.type)}>{p.type}</Badge></td>
                    <td className="num">{p.volume}</td>
                    <td className="num">{price(p.open_price, d)}</td>
                    <td className="num">{price(p.current_price, d)}</td>
                    <td className="num">{p.sl ? price(p.sl, d) : "—"}{p.is_be_locked && <div className="faint" style={{ fontSize: 11 }}>break-even</div>}</td>
                    <td className="num">{p.tp ? price(p.tp, d) : "—"}</td>
                    <td className={`num ${tone(r)}`}>{rMult(r)}</td>
                    <td className={`num ${tone(p.profit)}`}><b>{signedMoney(p.profit, ccy)}</b></td>
                    <td>
                      <select className="select" style={{ height: 30, width: 130 }} value={mode} aria-label="Position management mode"
                        onChange={(e) => setMode(p, e.target.value)}>
                        {MODES.map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
                      </select>
                    </td>
                    <td className="muted">{ago(p.open_time)}</td>
                    <td><button className="btn sm danger" onClick={() => close(p)}>Close</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
