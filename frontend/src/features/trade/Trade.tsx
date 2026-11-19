import { Watchlist } from "./Watchlist";
import { ChartPanel } from "./ChartPanel";
import { OrderTicket } from "./OrderTicket";
import { EngineView } from "./EngineView";
import { SignalPanel } from "./SignalPanel";

/** Trade desk: pick a symbol, read the chart and the engine's plan, place an order. */
export default function Trade({ go }: { sub: string; go: (r: string) => void }) {
  return (
    <div className="trade-layout">
      <div className="watch"><Watchlist /></div>
      <div className="stack" style={{ gap: 18, minWidth: 0 }}>
        <ChartPanel />
        <div className="trade-engine">
          <EngineView go={go} />
          <SignalPanel />
        </div>
      </div>
      <OrderTicket />
    </div>
  );
}
