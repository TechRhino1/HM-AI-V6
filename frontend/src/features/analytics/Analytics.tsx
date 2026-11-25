import { Seg } from "../../components/ui";
import { Performance } from "./Performance";
import { Calibration } from "./Calibration";
import { Lab } from "./Lab";
import { Research } from "./Research";
import { Gates } from "./Gates";

const TABS = [
  { value: "performance", label: "Performance" },
  { value: "gates", label: "Gates" },
  { value: "calibration", label: "Calibration" },
  { value: "lab", label: "Backtest lab" },
  { value: "research", label: "Research" },
];

/** Analytics: how the system has done, whether it is allowed to trade, and the tools to test changes. */
export default function Analytics({ sub, go }: { sub: string; go: (r: string) => void }) {
  const tab = TABS.some((t) => t.value === sub) ? sub : "performance";
  return (
    <>
      <Seg value={tab} onChange={(v) => go(`analytics/${v}`)} options={TABS} />
      {tab === "performance" && <Performance />}
      {tab === "gates" && <Gates />}
      {tab === "calibration" && <Calibration />}
      {tab === "lab" && <Lab />}
      {tab === "research" && <Research />}
    </>
  );
}
