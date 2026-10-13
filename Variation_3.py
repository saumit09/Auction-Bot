import math
import random
import time
import numpy as np

class Bot:
    VARIATION = 3

    def __init__(self, config):
        self.config = dict(config or {})
        self.rng = random.Random(12700 + self.VARIATION * 101 + int(self.config.get("player_id", 0)))
        self.block = None
        self.previous = None
        self.history = []
        
        # Bayesian parameter grid
        self.grid_m = np.repeat(np.arange(100., 1001., 10.), 10)
        self.grid_r = np.tile(np.arange(100., 1001., 100.), 91)
        self.logp = np.zeros(910)
        
        # Fast trackers for initial dodge filter
        self.fast_min = 10000.0
        self.fast_max = 0.0

    def _reset(self, block, capital):
        self.block = block
        self.previous = None
        self.history = []
        self.fast_min = 10000.0
        self.fast_max = 0.0
        valid = ((capital >= self.grid_m + 0.5 * self.grid_r - 1e-8) &
                 (capital <= self.grid_m + 2.5 * self.grid_r + 1e-8))
        self.logp = np.where(valid, -np.log(2.0 * self.grid_r), -np.inf)

    def _observe(self, obs, x, n):
        m, width = self.grid_m, self.grid_r
        if self.previous is not None:
            px, pn, pr = self.previous
            if int(obs.get("round", 1)) == pr + 1:
                X = float(obs.get("max_value_last_round") or 0.0)
                if X >= px - 1e-8 and X > 0:
                    f = np.clip((X - m) / width, 1e-300, 1.0)
                    valid = (X >= m) & (X <= m + width + 1e-8)
                    if abs(X - px) <= 1e-8:
                        likelihood = (pn - 1) * np.log(f)
                    else:
                        likelihood = math.log(max(1, pn - 1)) - np.log(width) + (pn - 2) * np.log(f)
                    self.logp += np.where(valid, likelihood, -np.inf)
                    
                    rank = int(obs.get("my_last_rank") or 0)
                    top = [float(obs.get("highest_bid_last_round") or 0.0),
                           float(obs.get("second_highest_bid_last_round") or 0.0)]
                    if 1 <= rank <= len(top):
                        top.pop(rank - 1)
                        
                    top = (top + [0.0] * (pn - 1))[:pn - 1]
                    self.history.append((top, X, px, pn))
                    self.history = self.history[-72:]
                    
        valid = (x >= m - 1e-8) & (x <= m + width + 1e-8)
        self.logp += np.where(valid, -np.log(width), -np.inf)
        finite = np.isfinite(self.logp)
        if not np.any(finite):
            self.off_grid = True
            self.logp = np.where(valid, -np.log(width), -np.inf)
            finite = np.isfinite(self.logp)
        else:
            self.off_grid = False
            
        if np.any(finite):
            peak = float(np.max(self.logp[finite]))
            self.logp -= peak
            p = np.exp(self.logp)
            p /= p.sum()
            lo = float(p @ m)
            hi = float(p @ (m + width))
        else:
            recent = [h[1] for h in self.history]
            lo = max(0.0, min([x] + recent) * 0.5)
            hi = max([x] + recent) * 1.05
        self.previous = (x, n, int(obs.get("round", 1)))
        return lo, hi

    def _scenarios(self, x, n, lo, hi):
        rows, values, weights = [], [], []
        relevant = [h for h in self.history if h[3] == n]
        for age, (bids, X, px, pn) in enumerate(reversed(relevant)):
            weight = 0.965 ** age
            if X > px + 1e-8:
                rows.append(bids)
                values.append(max(x, X))
                weights.append(weight)
            else:
                for q in (0.1666667, 0.5, 0.8333333):
                    rival_x = lo + max(0.0, min(px, hi) - lo) * (q ** (1.0 / (n - 1)))
                    rows.append(bids)
                    values.append(max(x, rival_x))
                    weights.append(weight / 3.0)
                    
        prior_weight = 1.0 if not relevant else 0.12
        for unused in range(12):
            vals = [lo + (hi - lo) * self.rng.random() for j in range(n - 1)]
            bids = [max(0.0, v + (15.0 if j % 3 == 0 else 5.0)) if j % 3 != 2 else 0.5 * v for j, v in enumerate(vals)]
            rows.append(sorted(bids, reverse=True))
            values.append(max([x] + vals))
            weights.append(prior_weight)
            
        w = np.asarray(weights, dtype=float)
        w /= w.sum()
        return np.asarray(rows), np.asarray(values), w

    def _utility(self, candidates, rivals, X, weights, capital, n):
        b = candidates[:, None]
        greater = np.sum(rivals[None, :, :] > b[:, :, None] + 1e-9, axis=2)
        equal = np.sum(np.abs(rivals[None, :, :] - b[:, :, None]) <= 1e-9, axis=2)
        a = rivals[:, 0][None, :]
        y = X[None, :]
        
        mean = np.zeros(len(candidates))
        loss2 = np.zeros(len(candidates))
        
        for rank in range(1, min(n, 2) + 1):
            prob = ((greater < rank) & (greater + equal + 1 >= rank)) / (equal + 1.0)
            pay = y - b if rank == 1 else -0.5 * np.maximum(y - a, 0.0)
            mean += (prob * pay) @ weights
            loss2 += (prob * np.minimum(pay, 0.0) ** 2) @ weights
            
        return mean - 1.5 * loss2 / max(capital, 1.0)

    def get_bid(self, obs):
        start_time = time.perf_counter()
        
        try:
            x = float(obs.get("x", 0.0))
            capital = float(obs.get("capital", 0.0))
            limit = min(capital, float(obs.get("max_bid") or capital))
            n = int(obs.get("num_players") or 20)
            
            if not math.isfinite(x) or not math.isfinite(limit) or limit <= 0.0 or n < 2:
                return 0.0
                
            block = (int(obs.get("round", 1)) - 1) // 500
            if block != self.block:
                self._reset(block, capital)
                
            self.fast_min = min(self.fast_min, x)
            self.fast_max = max(self.fast_max, x)
            if "max_value_last_round" in obs and int(obs.get("round", 1)) % 500 != 1:
                self.fast_max = max(self.fast_max, float(obs.get("max_value_last_round") or 0.0))
                
            m_b = max(100.0, (int(self.fast_min) // 10) * 10.0)
            R_b = max(100.0, self.fast_max - m_b)
            percentile = (x - m_b) / R_b if R_b > 0.0 else 0.0
            
            # Endgame 1v1 mode
            if n == 2:
                self.previous = (x, n, int(obs.get("round", 1)))
                return float(max(0.0, min(x - 0.1, limit)))
                
            # Multiplayer Rank 2 dodge
            if n > 2 and percentile < 0.70:
                self.previous = (x, n, int(obs.get("round", 1)))
                return 0.0

            # Bayesian optimization
            lo, hi = self._observe(obs, x, n)
            rivals, values, weights = self._scenarios(x, n, lo, hi)
            
            ceiling = max(0.0, min(limit, max(x, hi), x + 0.12 * capital))
            thresholds = np.quantile(rivals[:, :min(4, n - 1)].ravel(), np.linspace(0.0, 1.0, 31))
            
            candidates = np.unique(np.clip(np.concatenate((
                np.linspace(0.0, ceiling, 21), thresholds - 1e-6,
                thresholds + 1e-6, [0.0, min(x, limit), ceiling])), 0.0, ceiling))
                
            utility = self._utility(candidates, rivals, values, weights, capital, n)
            
            if time.perf_counter() - start_time > 0.85:
                return float(max(0.0, min(x - 0.1, limit)))
                
            best = int(np.argmax(utility))
            bid = float(candidates[best])
            
            return float(max(0.0, min(bid, limit)))
            
        except Exception:
            x_val = float(obs.get("x", 0.0))
            cap_val = float(obs.get("capital", 0.0))
            return float(max(0.0, min(x_val - 0.1, cap_val)))