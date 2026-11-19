import { dateTime } from "../lib/format";
import { Prov, provLabel } from "../features/markets/logic";

/**
 * Where a market value came from and how fresh it is: live · 4s, delayed 15m, close, EOD, stale, unavailable.
 * Before the first response (`prov` still undefined) it reads "loading"; pass `loading={false}` where the
 * payload has arrived and simply carries no provenance, so that shows as unavailable.
 */
export function ProvBadge({ prov, label, loading }: { prov?: Prov | null; label?: string; loading?: boolean }) {
  if (loading ?? prov === undefined)
    return <span className="badge prov" data-kind="loading"><span className="dot" />{label ? `${label}: ` : ""}loading</span>;
  const { text, tone, kind } = provLabel(prov);
  const title = [
    label, prov?.source, prov?.as_of ? `as of ${dateTime(prov.as_of)}` : "", prov?.note,
  ].filter(Boolean).join(" · ") || "No provenance reported";
  const note = kind === "unavailable" && prov?.note ? ` · ${prov.note}` : "";
  return (
    <span className={`badge prov ${tone === "flat" ? "" : tone}`} title={title} data-kind={kind}>
      <span className={`dot ${kind === "live" ? "up" : kind === "stale" ? "warn" : ""}`} />
      {label ? `${label}: ` : ""}{text}{note}
    </span>
  );
}
