// India Standard Time helpers (the NSE session clock), independent of the browser time zone.

export const istNow = () => {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
    .formatToParts(new Date());
  const g = (t: string) => parts.find((p) => p.type === t)?.value || "";
  return { day: `${g("year")}-${g("month")}-${g("day")}`, minutes: Number(g("hour")) * 60 + Number(g("minute")) };
};
/** Pre-open brief until the 15:30 IST close, the post-close brief after it. */
export const briefKind = () => (istNow().minutes < 15 * 60 + 30 ? "pre" : "post");
