/** Rows → CSV text. Columns are the union of scalar keys, quoted per RFC 4180; formula-looking cells are neutralised. */
export function toCsv(rows: Record<string, unknown>[]): string {
  const cols: string[] = [];
  for (const r of rows) for (const [k, v] of Object.entries(r)) if (typeof v !== "object" && !cols.includes(k)) cols.push(k);
  const cell = (v: unknown) => {
    if (v === null || v === undefined) return "";
    let s = String(v);
    // Spreadsheet formula injection guard (symbols/comments come from the broker).
    if (/^[=+\-@]/.test(s) && !/^-?\d/.test(s)) s = `'${s}`;
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
}
