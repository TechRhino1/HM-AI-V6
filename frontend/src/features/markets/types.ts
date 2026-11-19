import type { Prov } from "./logic";

export interface Wall { strike: number; oi: number; oi_change: number }
export interface Side {
  ltp?: number | null; bid?: number | null; ask?: number | null; mid?: number | null; spread_pct?: number | null;
  oi?: number | null; oi_change?: number | null; oi_change_pct?: number | null; volume?: number | null;
  iv?: number | null; iv_source?: string | null; buildup?: string | null; delta?: number | null;
  gamma?: number | null; vega?: number | null; theta?: number | null;
}
export interface StrikeRow { strike: number; call: Side | null; put: Side | null }
export interface Analytics {
  symbol?: string; expiry?: string; spot?: number; forward?: number; days_to_expiry?: number; lot_size?: number;
  atm_strike?: number; atm_iv?: number; atm_straddle?: number;
  expected_move?: { one_sd?: number; one_sd_pct?: number; upper_1sd?: number; lower_1sd?: number };
  max_pain?: number;
  pcr?: { oi?: number; volume?: number; oi_change?: number; call_oi?: number; put_oi?: number; call_oi_change?: number; put_oi_change?: number };
  walls?: { resistance?: Wall[]; support?: Wall[]; fresh_call_writing?: Wall[]; fresh_put_writing?: Wall[] };
  skew?: { call25_iv?: number; put25_iv?: number; rr25?: number };
  gex?: { net_gex_cr?: number; regime?: string; gamma_flip_strike?: number; assumption?: string };
  positioning?: { bias?: string; [k: string]: unknown };
  coverage?: { strikes?: number; with_iv?: number };
  strikes?: StrikeRow[]; expiries?: string[]; prov?: Prov;
}
export interface LegOut {
  strike: number; type: "CE" | "PE"; side: "BUY" | "SELL"; lots: number; price?: number; mid?: number;
  iv?: number; delta?: number; oi?: number; volume?: number; spread_pct?: number;
}
export interface Strategy {
  name?: string; legs?: LegOut[]; net_debit?: number; max_gain_per_lot?: number | null; max_loss_per_lot?: number | null;
  unlimited_loss?: boolean; unlimited_gain?: boolean; breakevens?: number[]; reward_risk?: number | null;
  market?: { pop?: number; ev_per_lot?: number }; view?: { pop?: number; ev_per_lot?: number };
  edge_per_lot?: number | null; cost_per_lot?: number; payoff_curve?: { s: number; pnl: number }[];
  rejected?: string[]; prov?: Prov; error?: string;
}
export interface Forecast {
  horizon_days?: number; premium_now?: number; move_1sd?: number; time_decay?: number; unchanged_spot_and_iv?: number;
  grid?: ({ spot_sigma: number; spot: number } & Record<string, { premium: number; pct: number } | number>)[]; prov?: Prov;
}
export interface Plan {
  entry?: { net?: number; type?: string; zone?: number[]; orders?: { side: string; lots: number; contract: string; limit: number }[] };
  target?: { rule?: string; close_at_net_credit?: number; [k: string]: unknown };
  stop?: { rule?: string; close_at_net_credit?: number; [k: string]: unknown };
  trailing?: string; max_loss_per_lot?: number | null; max_gain_per_lot?: number | null; breakevens?: number[];
  reward_risk?: number | null; premium_forecast?: Forecast;
}
export interface Advice {
  status?: "RECOMMEND" | "NO_TRADE" | "UNAVAILABLE"; reason?: string | null; symbol?: string; kind?: string; prov?: Prov;
  analytics?: Analytics;
  volatility?: {
    available?: boolean; rv10?: number; rv20?: number; rv60?: number; atm_iv?: number; iv_minus_rv20?: number; vol_view?: string;
    iv_percentile?: number | null; iv_history_days?: number; forecast_vol?: number; bars_prov?: Prov;
    trend?: { label?: string; sma20?: number; sma50?: number; sma20_slope_pct?: number };
  };
  evidence?: { score?: number; lean?: string; notes?: string[]; validated?: boolean };
  direction_model?: { validated?: boolean; reason?: string };
  vrp_history?: { available?: boolean; iv_above_rv_pct?: number; days?: number; from?: string; mean_iv_minus_rv?: number; worst_5pct?: number };
  expiry_desk?: {
    available?: boolean; is_expiry_day?: boolean; is_expiry_week?: boolean; days_to_expiry?: number;
    straddle_decay_if_spot_and_iv_unchanged?: { after_hours: number; atm_straddle: number }[];
    distance_to_max_pain_pct?: number; pin_candidates?: number[]; atm_gamma_per_lot?: number;
    oi_shift_today?: { available?: boolean; reason?: string; largest?: Record<string, unknown>[] }; guidance?: string[];
  };
  recommendation?: Strategy; plan?: Plan; strategies?: Strategy[]; reasoning?: string[];
  institutional?: {
    validated?: boolean; validation?: string; notes?: string[];
    fii_index_futures?: { date?: string; long_pct?: number; long_pct_chg?: number; net_contracts?: number; net_chg?: number; prov?: Prov };
    futures?: { expiry?: string; basis?: number; basis_ann_pct?: number; buildup?: string; rollover_pct?: number; prov?: Prov };
    ban_trade_date?: string; in_ban?: boolean; events?: { purpose?: string; date?: string }[]; event_risk?: boolean | string | null;
  };
}
/** The scan summary names the strategy as a string; older payloads carried the object. */
export const recName = (r?: string | Strategy | null) => (typeof r === "string" ? r : r?.name);
export interface ScanOut {
  scanned?: number; seconds?: number; prov?: Prov;
  summary?: { symbol: string; status: string; reason?: string | null; recommendation?: string | Strategy | null; edge_per_lot?: number | null; lean?: string; prov?: Prov }[];
}
