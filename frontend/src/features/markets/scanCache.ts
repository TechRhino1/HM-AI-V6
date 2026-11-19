import type { ScanOut } from "./types";

// The last opportunity scan this page ran (survives tab switches). One scan per 5 min; never run implicitly.
let last: { at: number; data: ScanOut } | null = null;
let requested = false;

export const getLastScan = () => last;
export const setLastScan = (v: { at: number; data: ScanOut }) => { last = v; };
/** Ask the scanner to run as soon as it is shown (command palette). */
export const requestScan = () => { requested = true; };
export const takeScanRequest = () => { const r = requested; requested = false; return r; };
