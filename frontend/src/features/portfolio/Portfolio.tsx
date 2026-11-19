import { Seg } from "../../components/ui";
import { useStore } from "../../state/store";
import { OpenPositions } from "./OpenPositions";
import { PendingOrders } from "./PendingOrders";
import { Journal } from "./Journal";

/** Portfolio: what is open, what is waiting, and the journal of everything that closed. */
export default function Portfolio({ sub, go }: { sub: string; go: (r: string) => void }) {
  const { telemetry } = useStore();
  const tab = ["open", "pending", "history"].includes(sub) ? sub : "open";
  return (
    <>
      <Seg value={tab} onChange={(v) => go(`portfolio/${v}`)} options={[
        { value: "open", label: `Open (${telemetry?.positions?.length ?? 0})` },
        { value: "pending", label: "Pending" },
        { value: "history", label: "Journal" },
      ]} />
      {tab === "open" && <OpenPositions />}
      {tab === "pending" && <PendingOrders />}
      {tab === "history" && <Journal />}
    </>
  );
}
