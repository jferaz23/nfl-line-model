"""Game model: predicts home margin and total points from the feature table.

Main component is a ridge regression (every factor included, shrunk toward zero
so noisy factors can't dominate). An optional shallow gradient-boosting model
picks up non-linear effects (wind x passing, cold x dome teams, etc.) and is
blended in with cfg.gbm_weight. The model never sees the betting line, so its
opinion is independent of the market; pricing.py decides how much to trust it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler

from .features import MARGIN_GROUPS, TOTAL_GROUPS

TARGETS = {"margin": ("result", MARGIN_GROUPS), "total": ("total", TOTAL_GROUPS)}


class LineModel:
    def __init__(self, cfg, kind: str, drop_groups=(), use_gbm=None):
        if kind not in TARGETS:
            raise ValueError(kind)
        self.cfg, self.kind = cfg, kind
        self.target, groups = TARGETS[kind]
        self.groups = {g: fs for g, fs in groups.items() if g not in set(drop_groups)}
        self.features = list(dict.fromkeys(f for fs in self.groups.values() for f in fs))
        gw = getattr(cfg, f"gbm_weight_{kind}", -1.0)
        self.gw = cfg.gbm_weight if gw is None or gw < 0 else float(gw)
        # an explicit use_gbm=True fits the booster even at weight 0 (the backtest needs it to choose)
        self.use_gbm = (cfg.use_gbm and self.gw > 0) if use_gbm is None else use_gbm
        self.gbm = None
        # spreads: blend in the market-implied ratings forecast (as-of: earlier weeks' closing lines)
        self.mb = float(getattr(cfg, "mkt_blend_margin", 0.0) or 0.0) if kind == "margin" else 0.0

    def _blend(self, df, p):
        if self.mb <= 0 or "d_mkt_rating" not in df.columns:
            return p
        m = df["d_mkt_rating"].astype(float).fillna(0.0).to_numpy()
        return (1 - self.mb) * p + self.mb * m

    def _xy(self, df):
        d = df[df["has_ratings"].astype(bool) & df[self.target].notna()]
        return d, d[self.features].astype(float), d[self.target].astype(float)

    def fit(self, df: pd.DataFrame):
        d, X, y = self._xy(df)
        if len(d) < 200:
            raise RuntimeError(f"Only {len(d)} training games for the {self.kind} model; need more history.")
        w = self.cfg.train_recency_decay ** (d["season"].max() - d["season"]).to_numpy(dtype=float)
        self.imputer = SimpleImputer(strategy="median", keep_empty_features=True).fit(X)
        Xi = self.imputer.transform(X)
        self.scaler = StandardScaler().fit(Xi)
        # near-constant columns (floating-point noise around a constant) would be blown up to huge values
        self.scaler.scale_[self.scaler.scale_ < 1e-8] = 1.0
        Xs = self.scaler.transform(Xi)
        self.ridge = RidgeCV(alphas=self.cfg.ridge_alphas).fit(Xs, y, sample_weight=w)
        if self.use_gbm and len(d) >= 800:
            self.gbm = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.04, max_iter=400,
                                                     min_samples_leaf=40, l2_regularization=1.0,
                                                     random_state=7).fit(X, y, sample_weight=w)
        self.n_train = len(d)
        self.train_seasons = (int(d["season"].min()), int(d["season"].max()))
        return self

    def _xs(self, df):
        X = df[self.features].astype(float)
        return X, self.scaler.transform(self.imputer.transform(X))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        X, Xs = self._xs(df)
        p = self.ridge.predict(Xs)
        if self.gbm is not None and self.gw > 0:
            p = (1 - self.gw) * p + self.gw * self.gbm.predict(X)
        return self._blend(df, p)

    def predict_parts(self, df: pd.DataFrame):
        """(ridge prediction, boosting prediction or NaN) so the backtest can choose the blend."""
        X, Xs = self._xs(df)
        r = self.ridge.predict(Xs)
        g = self.gbm.predict(X) if self.gbm is not None else np.full(len(r), np.nan)
        return self._blend(df, r), self._blend(df, g)

    def explain(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ridge contribution of each factor group, in points, relative to an average game."""
        _, Xs = self._xs(df)
        contrib = Xs * self.ridge.coef_
        out = pd.DataFrame(index=df.index)
        pos = {f: i for i, f in enumerate(self.features)}
        for g, fs in self.groups.items():
            out[g] = contrib[:, [pos[f] for f in dict.fromkeys(fs)]].sum(axis=1)
        out["baseline"] = self.ridge.intercept_
        if self.mb > 0 and "d_mkt_rating" in df.columns:
            out = out * (1 - self.mb)
            out["market_view"] = self.mb * df["d_mkt_rating"].astype(float).fillna(0.0).to_numpy()
        return out

    def coefficients(self) -> pd.DataFrame:
        grp = {f: g for g, fs in self.groups.items() for f in fs}
        return pd.DataFrame({
            "feature": self.features,
            "group": [grp[f] for f in self.features],
            "pts_per_sd": self.ridge.coef_,
            "pts_per_unit": self.ridge.coef_ / self.scaler.scale_,
        }).sort_values("pts_per_sd", key=np.abs, ascending=False).reset_index(drop=True)
