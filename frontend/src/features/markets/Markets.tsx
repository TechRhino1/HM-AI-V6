import { Seg } from "../../components/ui";
import { Fno } from "./Fno";
import { Equities } from "./Equities";
import { Sources } from "./Sources";
import { Inst } from "./Inst";

const TABS = [
  { value: "fno", label: "India F&O" },
  { value: "inst", label: "Institutional" },
  { value: "india", label: "India equities" },
  { value: "us", label: "US stocks" },
  { value: "sources", label: "Data sources" },
];

/** Markets: India options (adviser), India equities, US stocks and live-data status. Every value carries its provenance. */
export default function Markets({ sub, go }: { sub: string; go: (r: string) => void }) {
  const tab = TABS.some((t) => t.value === sub) ? sub : "fno";
  return (
    <>
      <Seg value={tab} onChange={(v) => go(`markets/${v}`)} options={TABS} />
      {tab === "fno" && <Fno />}
      {tab === "inst" && <Inst />}
      {tab === "india" && <Equities key="IN" market="IN" />}
      {tab === "us" && <Equities key="US" market="US" />}
      {tab === "sources" && <Sources />}
    </>
  );
}
