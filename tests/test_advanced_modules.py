"""Tests for the new HM Algo 2.0 advanced modules (ML, gates, GEX, walk-forward)."""
import math
import numpy as np
import unittest


class TestMetaLabeler(unittest.TestCase):
    def test_train_and_predict(self):
        import tempfile, os
        from jarvis.intelligence.meta_labeler import MetaLabeler, _HAVE_SKLEARN
        if not _HAVE_SKLEARN:
            self.skipTest("scikit-learn not installed")

        np.random.seed(1)
        n = 320
        prices = 100 + np.cumsum(np.random.randn(n) * 0.1)
        candles = [
            {"open": prices[i], "high": prices[i] + 0.05, "low": prices[i] - 0.05,
             "close": prices[i], "volume": 1000 + np.random.rand() * 100}
            for i in range(n)
        ]
        tmp = tempfile.mktemp(suffix=".joblib")
        ml = MetaLabeler(model_path=tmp)  # isolated on-disk model
        ok = ml.train(candles, horizon=20)
        self.assertTrue(ok)
        prob = ml.predict_proba(candles[-40:], bias=1.0)
        self.assertIsNotNone(prob)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)
        # a model pointing at a non-existent path is genuinely untrained -> None
        fresh = MetaLabeler(model_path=tempfile.mktemp(suffix=".joblib"))
        self.assertIsNone(fresh.predict_proba(candles[-40:], bias=1.0))
        if os.path.exists(tmp):
            os.remove(tmp)


class TestGatePolicy(unittest.TestCase):
    def test_hard_always_blocks(self):
        from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
        gp = AdaptiveGatePolicy()
        decision, soft = gp.decide(["Drawdown Safety Guard"], 0.95)
        self.assertEqual(decision, "BLOCK")

    def test_no_evidence_blocks_soft(self):
        from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
        gp = AdaptiveGatePolicy()
        decision, soft = gp.decide(["Order Flow Momentum", "Calibrated Win Prob"], None)
        self.assertEqual(decision, "BLOCK")

    def test_good_evidence_softens(self):
        from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
        gp = AdaptiveGatePolicy()
        decision, soft = gp.decide(["Order Flow Momentum"], 0.62)
        self.assertEqual(decision, "SOFTEN")
        # 3 soft failures -> soften with new max_soft_fail=3
        decision, _ = gp.decide(["Order Flow Momentum", "Calibrated Win Prob", "AI Score"], 0.7)
        self.assertEqual(decision, "SOFTEN")
        # 4 soft failures -> block even with good evidence
        decision, _ = gp.decide(["Order Flow Momentum", "Calibrated Win Prob", "AI Score", "Spread Protection"], 0.7)
        self.assertEqual(decision, "BLOCK")

    def test_penalty_capped(self):
        from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
        gp = AdaptiveGatePolicy()
        self.assertAlmostEqual(gp.confidence_penalty(["a", "b", "c", "d", "e"]), 0.12)


class TestWalkForward(unittest.TestCase):
    def test_purged_kfold_splits(self):
        from jarvis.learning.walk_forward import PurgedKFold
        kf = PurgedKFold(n_splits=5, embargo_frac=0.02)
        splits = kf.split(500)
        self.assertGreaterEqual(len(splits), 3)
        for tr, te in splits:
            self.assertTrue(len(tr) > 0 and len(te) > 0)
            self.assertEqual(len(set(tr) & set(te)), 0)

    def test_purged_cv_score(self):
        from jarvis.learning.walk_forward import purged_cv_score
        np.random.seed(2)
        X = np.random.randn(300, 4)
        y = (X[:, 0] + X[:, 1] > 0).astype(int)

        def fit_predict(Xtr, ytr, Xte):
            w = np.linalg.lstsq(Xtr, ytr, rcond=None)[0]
            return np.clip(Xte @ w, 0, 1)

        res = purged_cv_score(X, y, fit_predict, n_splits=4)
        self.assertIn("oos_accuracy", res)
        self.assertGreater(res["n_test"], 0)

    def test_walk_forward_optimize(self):
        from jarvis.learning.walk_forward import walk_forward_optimize
        np.random.seed(3)
        X = np.random.randn(300, 2)
        y = (X[:, 0] > 0).astype(int)
        grid = [{"a": 1}, {"a": 2}, {"a": 3}]

        def backtest(params, Xte, yte):
            # arbitrary oos metric favoring param a==2
            return 1.0 if params["a"] == 2 else 0.1

        out = walk_forward_optimize(grid, backtest, X, y, n_splits=4)
        self.assertEqual(out["best_params"]["a"], 2)


class TestDecisionObjectSchema(unittest.TestCase):
    def test_new_fields_present(self):
        from jarvis.data.schemas import DecisionObject
        fields = DecisionObject.__dataclass_fields__
        self.assertIn("meta_label_prob", fields)
        self.assertIn("gate_policy_decision", fields)
        # default values
        self.assertIsNone(fields["meta_label_prob"].default)
        self.assertEqual(fields["gate_policy_decision"].default, "BLOCK")


if __name__ == "__main__":
    unittest.main()
