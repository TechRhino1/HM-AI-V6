import { Seg } from "../../components/ui";
import { Controls } from "./Controls";
import { SymbolUniverse } from "./SymbolUniverse";
import { Users } from "./Users";
import { AccountSettings } from "./AccountSettings";
import { AiGovernor } from "./AiGovernor";
import { Health } from "./Health";

const TABS = [
  { value: "controls", label: "Engine controls" },
  { value: "health", label: "Health" },
  { value: "ai", label: "AI governor" },
  { value: "symbols", label: "Symbol universe" },
  { value: "users", label: "Users" },
  { value: "account", label: "My account" },
];

/** System: how the engine runs (mode, style, safety), what it trades, and who can use the console. */
export default function System({ sub, go }: { sub: string; go: (r: string) => void }) {
  const tab = TABS.some((t) => t.value === sub) ? sub : "controls";
  return (
    <>
      <Seg value={tab} onChange={(v) => go(`system/${v}`)} options={TABS} />
      {tab === "controls" && <Controls />}
      {tab === "health" && <Health />}
      {tab === "ai" && <AiGovernor />}
      {tab === "symbols" && <SymbolUniverse />}
      {tab === "users" && <Users />}
      {tab === "account" && <AccountSettings />}
    </>
  );
}
