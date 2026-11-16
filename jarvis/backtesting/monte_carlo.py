"""
HM Algo 2.0 — Monte Carlo Resampling & Risk of Ruin Simulator.
Simulates randomized trade sequences, slippage variance, and maximum drawdown distributions.
"""
from typing import List, Dict, Any
import numpy as np

class MonteCarloSimulator:
    def __init__(self, num_simulations: int = 500, seed: int = 7, noise_std: float = 2.0,
                 ruin_fraction: float = 0.5):
        # Seeded: identical inputs must give identical risk figures (it drew from
        # the global unseeded RNG, so every report differed run to run).
        self.num_simulations = num_simulations
        self.seed = seed
        self.noise_std = noise_std          # $ slippage noise per trade (0 = pure resampling)
        self.ruin_fraction = ruin_fraction  # "ruin" = equity at or below this share of the start

    def run_simulation(self, trades: List[Dict[str, Any]], initial_balance: float = 10000.0) -> Dict[str, Any]:
        if not trades:
            return {"simulations": 0, "var_95_pct": 0.0, "max_dd_median_pct": 0.0, "risk_of_ruin_pct": 0.0}

        pnls = np.array([t["pnl"] for t in trades])
        n_trades = len(pnls)

        rng = np.random.default_rng(self.seed)
        # Vectorised: all paths at once (it was a Python loop over paths x trades).
        sim = rng.choice(pnls, size=(self.num_simulations, n_trades), replace=True)
        if self.noise_std > 0:
            sim = sim + rng.normal(0.0, self.noise_std, size=sim.shape)
        eq = np.concatenate([np.full((self.num_simulations, 1), float(initial_balance)),
                             initial_balance + np.cumsum(sim, axis=1)], axis=1)
        ruin_count = int(np.any(eq <= initial_balance * self.ruin_fraction, axis=1).sum())
        final_balances = eq[:, -1]
        running_max = np.maximum.accumulate(eq, axis=1)
        max_drawdowns = np.max((running_max - eq) / (running_max + 1e-9) * 100.0, axis=1)

        var_95 = np.percentile(final_balances, 5)
        median_dd = np.median(max_drawdowns)
        max_dd_95th = np.percentile(max_drawdowns, 95)
        risk_of_ruin = (ruin_count / self.num_simulations) * 100.0

        return {
            "num_simulations": self.num_simulations,
            "median_final_balance": round(float(np.median(final_balances)), 2),
            "var_95_balance": round(float(var_95), 2),
            "max_dd_median_pct": round(float(median_dd), 2),
            "max_dd_95th_percentile_pct": round(float(max_dd_95th), 2),
            "risk_of_ruin_pct": round(float(risk_of_ruin), 2)
        }
