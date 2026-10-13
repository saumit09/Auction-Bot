import math
import time

class Bot:
    def __init__(self, config):
        self.config = dict(config or {})
        self.block = -1
        self.last_round = -1
        self.start_capital = 1000.0
        self.count = 0
        self.low_x = math.inf
        self.high_x = -math.inf
        self.market_min = 100.0
        self.market_range = 900.0

    def reset(self, block, capital):
        self.block = block
        self.start_capital = max(1.0, float(capital))
        self.count = 0
        self.low_x = math.inf
        self.high_x = -math.inf
        self.market_min = 100.0
        self.market_range = max(400.0, 0.45 * self.start_capital)

    def update_tracker(self, x, last_max):
        self.count += 1
        self.low_x = min(self.low_x, x)
        self.high_x = max(self.high_x, x)
        
        # Validated common prize integration
        if last_max is not None and math.isfinite(last_max) and last_max > 0.0:
            self.high_x = max(self.high_x, last_max)
            
        if self.count >= 2 and self.high_x > self.low_x:
            span = self.high_x - self.low_x
            est_range = span * (self.count + 1.0) / max(1.0, self.count - 1.0)
            est_min = max(0.0, self.low_x - (est_range - span) * 0.5)
            self.market_min = est_min
            min_allowable_range = max(350.0, 0.40 * self.start_capital)
            self.market_range = max(min_allowable_range, est_range)
        else:
            self.market_min = max(0.0, self.low_x * 0.5)
            self.market_range = max(400.0, x)

    def get_bid(self, obs):
        start_time = time.perf_counter()
        
        try:
            # 1. Read only keys explicitly permitted for Variation 4
            x = float(obs.get("x") or 0.0)
            capital = float(obs.get("capital") or 0.0)
            
            # Boundary & solvency guard
            if not (math.isfinite(x) and math.isfinite(capital)):
                return 0.0
            if capital <= 0.0 or x <= 0.0:
                return 0.0
                
            t = int(obs.get("round") or 1)
            block = (t - 1) // 500
            round_in_block = ((t - 1) % 500) + 1
            
            # 2. Block transition and restart synchronization
            if block != self.block or t == 1 or (self.last_round > 0 and t != self.last_round + 1):
                self.reset(block, capital)
            self.last_round = t
                
            # 3. Dynamic lobby population check
            n = int(obs.get("num_players") or 20)
            
            # 4. In-block tracker update (no cross-block pollution)
            last_max = float(obs.get("max_value_last_round") or 0.0) if round_in_block > 1 else None
            self.update_tracker(x, last_max)
            
            # 5. Percentile estimation
            percentile = (x - self.market_min) / max(1.0, self.market_range)
            percentile = max(0.0, min(1.0, percentile))
            
            # Branch A: Duel (n <= 2) - No rank 3-5 tax exists
            if n <= 2:
                return float(max(0.0, min(x, capital)))
                
            # Branch B: Depleted lobby (3 <= n <= 5) - Strict entry gates
            if n <= 5:
                threshold = 0.85 if n == 3 else (0.90 if n == 4 else 0.92)
                if percentile >= threshold and capital >= 25.0:
                    bid = min(x, capital)
                else:
                    bid = 0.0
                return float(max(0.0, min(bid, capital)))
                
            # Branch C: Crowded lobby (n >= 6) - Target Rank 1 or drop to Rank 6+ (0 tax)
            required_percentile = max(0.978, (0.75) ** (1.0 / max(1.0, float(n - 1))))
            
            if self.count < 10:
                required_percentile = max(required_percentile, 0.985)
                
            if capital < 0.35 * self.start_capital:
                required_percentile = max(required_percentile, 0.988)
                
            if percentile >= required_percentile and capital >= 25.0:
                bid = min(x, capital)
            else:
                bid = 0.0
                
            # Timeout guard (< 850 ms)
            if time.perf_counter() - start_time > 0.85:
                return 0.0
                
            return float(max(0.0, min(bid, capital)))
            
        except Exception:
            return 0.0
        