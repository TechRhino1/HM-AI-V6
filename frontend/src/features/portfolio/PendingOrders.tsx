import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { cleanSymbol, dateTime, price } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Field, Loading, Modal, sideTone } from "../../components/ui";
import type { PendingOrder } from "../../lib/types";

// MT5 ORDER_TYPE enum values for pending orders.
const TYPE_NAME: Record<string, string> = { "2": "BUY LIMIT", "3": "SELL LIMIT", "4": "BUY STOP", "5": "SELL STOP" };
const typeName = (t: PendingOrder["type"]) => TYPE_NAME[String(t)] || String(t).replace("_", " ");

export function PendingOrders() {
  const res = usePoll<PendingOrder[] | { orders: PendingOrder[] }>("/api/pending_orders", 10000);
  const { symbols } = useStore();
  const { run } = useFeedback();
  const [edit, setEdit] = useState<PendingOrder | null>(null);
  const orders = Array.isArray(res.data) ? res.data : res.data?.orders || [];
  const digitsOf = (s: string) => symbols.find((x) => x.symbol === cleanSymbol(s))?.digits;

  const cancel = (o: PendingOrder) => run(() => api.post("/api/action/cancel_pending_order", { ticket: o.ticket }), {
    success: `Cancelled order #${o.ticket}`,
    confirm: { title: "Cancel pending order?", danger: true, confirmLabel: "Cancel order",
      body: <>{typeName(o.type)} {o.volume} {cleanSymbol(o.symbol)} @ {o.price} (#{o.ticket})</> },
  }).then(res.reload);

  return (
    <Card title="Pending orders" sub="Limit and stop orders waiting at the broker" flush>
      <ErrorNote error={res.error} onRetry={res.reload} />
      {res.loading && !res.data ? <Loading /> : !orders.length ? <Empty title="No pending orders" icon="clock">Place limit or stop orders from the Trade ticket.</Empty> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Symbol</th><th>Type</th><th className="r">Lots</th><th className="r">Price</th><th className="r">Stop</th><th className="r">Target</th><th>Placed</th><th /></tr></thead>
            <tbody>
              {orders.map((o) => {
                const d = digitsOf(o.symbol);
                return (
                  <tr key={o.ticket}>
                    <td><b>{cleanSymbol(o.symbol)}</b><div className="faint" style={{ fontSize: 11.5 }}>#{o.ticket}</div></td>
                    <td><Badge tone={sideTone(typeName(o.type))}>{typeName(o.type)}</Badge></td>
                    <td className="num">{o.volume}</td>
                    <td className="num">{price(o.price, d)}</td>
                    <td className="num">{o.sl ? price(o.sl, d) : "—"}</td>
                    <td className="num">{o.tp ? price(o.tp, d) : "—"}</td>
                    <td className="muted">{dateTime(o.time_setup)}</td>
                    <td className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <button className="btn sm" onClick={() => setEdit(o)}>Modify</button>
                      <button className="btn sm danger" onClick={() => cancel(o)}>Cancel</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {edit && <ModifyOrder order={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); res.reload(); }} />}
    </Card>
  );
}

function ModifyOrder({ order, onClose, onDone }: { order: PendingOrder; onClose: () => void; onDone: () => void }) {
  const { run } = useFeedback();
  const [p, setP] = useState(String(order.price || ""));
  const [sl, setSl] = useState(String(order.sl || ""));
  const [tp, setTp] = useState(String(order.tp || ""));
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));
  const save = async () => {
    const r = await run(() => api.post("/api/action/modify_pending_order", { ticket: order.ticket, price: num(p), sl: num(sl), tp: num(tp) }), { success: `Order #${order.ticket} updated` });
    if (r) onDone();
  };
  return (
    <Modal title={`Modify ${typeName(order.type)} ${cleanSymbol(order.symbol)}`} onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save changes</button></>}>
      <Field label="Price"><input className="input mono" inputMode="decimal" value={p} onChange={(e) => setP(e.target.value)} /></Field>
      <Field label="Stop-loss"><input className="input mono" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} /></Field>
      <Field label="Take-profit"><input className="input mono" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} /></Field>
    </Modal>
  );
}
