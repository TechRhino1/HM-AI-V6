// Shapes of the server payloads the UI reads. Loose on purpose: the server adds fields freely.

export interface Account {
  login: number; server: string; name: string; company: string; currency: string;
  balance: number; equity: number; profit: number; margin: number; free_margin: number;
  margin_level: number; leverage: number; trade_allowed: boolean; last_sync_time: string;
}

export interface Position {
  ticket: number; symbol: string; type: string; volume: number; open_price: number; current_price: number;
  sl: number; tp: number; tp1?: number | null; tp2?: number | null; tp3?: number | null;
  profit: number; swap: number; commission: number; open_time: string; comment: string; magic: number;
  style?: string; is_manual?: boolean; monitoring_mode?: string; is_be_locked?: boolean;
  milestone_status?: string; mfe?: number; mae?: number; current_r?: number;
}

export interface Opportunity {
  symbol: string; trade_style: string; timeframe: string; current_price: number; entry_price: number;
  stop_loss: number; take_profit: number; tp1_price?: number; tp2_price?: number; tp3_price?: number;
  risk_reward_ratio: number; ev: number; bias: string; action: string; status_label: string; decision: string;
  score: number; win_prob: number; ml_prob?: number; confluence_score: number; confluence_tier: string;
  regime: string; strategy: string; gate_passed: boolean; failing_reasons: string[]; waiting_reasons: string[];
  rejection_reasons: string[]; risk_factors: string[]; checks: Record<string, boolean>; adversarial_penalty?: number;
  invalidation_levels?: unknown[]; mtf_alignment?: Record<string, string>; mtf_confluence?: number;
  setup_grade?: string; is_actionable?: boolean;
}

export interface MarketStatus {
  is_open: boolean; status: string; status_text?: string; next_event?: string; countdown_formatted?: string;
  countdown_seconds?: number; market_type?: string; current_session?: string;
}

export interface Telemetry {
  execution_mode: string; trade_style: string; safe_mode: boolean; is_running: boolean;
  account: Account | null; positions: Position[]; positions_count: number;
  services: Record<string, string>; radar_opportunities: Opportunity[];
  latest_decisions: Record<string, any>; market_statuses: Record<string, MarketStatus>;
  timestamp?: string;
}

export interface RiskStatus {
  daily_loss_pct: number; max_daily_loss_pct: number; total_dd_pct: number; max_drawdown_pct: number;
  daily_start_equity: number; peak_equity: number; drawdown_multiplier: number;
  circuit_breaker_active: boolean; circuit_breaker_reason: string; circuit_breaker_cooldown_sec: number;
  consecutive_losses: number; paused_symbols: string[]; portfolio_heat_score: number; portfolio_heat_zone: string;
  heat_risk_multiplier: number; allow_new_risk: boolean; margin_utilization_pct: number;
  heat_components?: Record<string, number>; heat_reasons?: string[];
}

export interface SymbolIntel {
  symbol: string; canonical: string; asset_class: string; is_enabled: boolean; is_open: boolean; session_name: string;
  bid: number; ask: number; digits: number; spread_pips: number; max_spread_pips: number;
  tick_value?: number; tick_size?: number; volume_min?: number; volume_step?: number; volume_max?: number;
  bias: string; decision: string; regime: string; strategy: string; win_prob: number; confluence_score: number;
  confluence_tier: string; grade: string; risk_reward_ratio: number; ev: number; suggestion: string; suggestion_type: string;
}

export interface ClosedTrade {
  id?: number; ticket: number; symbol: string; action?: string; type?: string; volume: number;
  entry_price: number; exit_price?: number; realized_pnl?: number; profit?: number;
  timestamp?: string; closed_at?: string; exit_time?: string; strategy?: string; trade_style?: string;
  exit_reason?: string; origin?: string; executor?: string; [k: string]: unknown;
}

export interface PendingOrder {
  ticket: number; symbol: string; type: number | string; volume: number; price: number; sl: number; tp: number;
  time_setup?: number | string; comment?: string;
}

export type TradeStyle = "AUTO" | "ALL" | "SCALP" | "DAY_TRADING" | "SWING";
export const STYLES: { value: TradeStyle; label: string }[] = [
  { value: "AUTO", label: "Auto" },
  { value: "ALL", label: "All" },
  { value: "SCALP", label: "Scalp" },
  { value: "DAY_TRADING", label: "Day" },
  { value: "SWING", label: "Swing" },
];
