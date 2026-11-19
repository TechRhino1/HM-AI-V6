import { useState } from "react";
import { useLocalStorage } from "../lib/hooks";
import { Modal } from "./ui";
import { Icon, IconName } from "./Icon";

const STEPS: { route?: string; icon: IconName; title: string; body: string }[] = [
  { route: "overview", icon: "home", title: "Start with Today", body: "Overview opens with the Today card: the AI market brief, NSE/US session state, unread alerts, today's corporate events and the last scan's opportunities. Account, guardrails and exposure follow below." },
  { route: "trade", icon: "candles", title: "Trade", body: "Chart, engine reasoning and the order ticket for the selected symbol. Orders are only ever placed by you from the ticket; the AI never places orders." },
  { route: "markets/fno", icon: "globe", title: "Markets", body: "India F&O adviser with chain, structure, volatility and a copyable broker basket; the Institutional tab adds participant positioning, futures basis and buildup, deals, events, delivery and IV term structure. Every value shows where it came from and how fresh it is; the small “i” explains a metric." },
  { icon: "bell", title: "Alerts", body: "The bell in the top bar lists fired alerts and your rules. Create alerts from the form, in plain English, or with the bell buttons beside OI walls, max pain, futures and events. Alerts notify only." },
  { icon: "chat", title: "Ask AI", body: "The Ask AI button (bottom right) answers with citations to the live data it used and knows which page and symbol you are on. Press Ctrl K for search and quick actions: ask AI, new alert, run the F&O scan, generate the brief." },
];

/** First-run tour; dismissed for good once finished or skipped (localStorage hm.tourDone). */
export function Tour({ go }: { go: (r: string) => void }) {
  const [done, setDone] = useLocalStorage("hm.tourDone", false);
  const [i, setI] = useState(0);
  if (done) return null;
  const s = STEPS[i];
  const to = (n: number) => { setI(n); if (STEPS[n].route) go(STEPS[n].route!); };
  const finish = () => setDone(true);
  return (
    <Modal title={<span className="row" style={{ gap: 8 }}><Icon name={s.icon} />{s.title}</span>} onClose={finish}
      footer={
        <div className="row between" style={{ width: "100%" }}>
          <div className="tour-dots" aria-hidden="true">
            {STEPS.map((_, j) => <i key={j} className={j === i ? "on" : ""} />)}
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn ghost sm" onClick={finish}>Skip tour</button>
            {i > 0 && <button className="btn sm" onClick={() => to(i - 1)}>Back</button>}
            <button className="btn primary sm" autoFocus onClick={() => (i < STEPS.length - 1 ? to(i + 1) : finish())}>{i < STEPS.length - 1 ? "Next" : "Done"}</button>
          </div>
        </div>
      }>
      <div className="muted">{s.body}</div>
      <div className="faint" style={{ fontSize: 12 }}>Step {i + 1} of {STEPS.length}</div>
    </Modal>
  );
}
