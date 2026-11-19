import { usePoll } from "../../lib/hooks";

export interface DeploymentRow {
  symbol: string; refusal: string | null; geometry_mode?: string; tp_r?: number;
  oos_trades?: number; oos_win_rate?: number; oos_expectancy_r?: number; oos_profit_factor?: number;
}
export interface Deployment { min_oos_expectancy_r: number; min_oos_trades: number; symbols: DeploymentRow[] }

/** The live deployment gate per symbol (out-of-sample expectancy check). Changes only on recalibration. */
export const useDeployment = () => usePoll<Deployment>("/api/calibration/deployment", 300000);
