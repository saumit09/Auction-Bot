import math
import time
from bisect import bisect_right

class Bot:
    def __init__(self, config):
        self.config = dict(config or {})
        self.variation = 1
        self.block = -1
        self.previous = None
        self.history = []
        self.candidates = []
        self.count = 0
        self.low = 0.0
        self.high = 0.0
        self.start_capital = 0.0
        self.market_min = 0.0
        self.market_range = 100.0

    def reset(self, block, capital):
        self.block = block
        self.previous = None
        self.history = []
        self.count = 0
        self.low = math.inf
        self.high = -math.inf
        self.start_capital = capital
        pairs = {(m, r) for m in range(100, 1001, 10) for r in range(100, 1001, 10)}
        pairs.update((m, r) for m in range(10, 1001, 10) for r in range(100, 10001, 100))
        self.candidates = sorted((m, r) for m, r in pairs if m + 0.5 * r <= capital <= m + 2.5 * r)

    def estimate_market(self, x):
        self.count += 1
        self.low = min(self.low, x)
        self.high = max(self.high, x)
        self.candidates = [(m, r) for m, r in self.candidates if m <= self.low and m + r >= self.high]
        
        if self.candidates:
            smallest = min(r for m, r in self.candidates)
            total = mean_m = mean_r = 0.0
            for m, r in self.candidates:
                weight = (smallest / r) ** (self.count + 1)
                total += weight
                mean_m += weight * m
                mean_r += weight * r
            self.market_min = mean_m / total
            self.market_range = mean_r / total
        else:
            span = self.high - self.low
            if self.count > 1 and span > 0.0:
                gap = span / (self.count - 1)
                self.market_min = max(0.0, self.low - gap)
                self.market_range = max(1.0, span + 2.0 * gap)
            else:
                self.market_min = max(0.0, x * 0.25)
                self.market_range = max(100.0, x)

    def record_feedback(self, obs):
        prev_round, prev_x, prev_capital, prev_n = self.previous
        top = float(obs.get("highest_bid_last_round") or 0.0)
        second = float(obs.get("second_highest_bid_last_round") or 0.0)
        own = float(obs.get("my_last_bid") or 0.0)
        
        if not all(math.isfinite(v) and v >= 0.0 for v in (top, second, own)):
            return
            
        opponent = second if own == top and own > second else top
        lower_y = 0.0
        self.history.append((opponent, lower_y, prev_n, prev_round))
        if len(self.history) > 160:
            self.history.pop(0)

    def choose_bid(self, x, ceiling, n, round_number, start_time):
        rows = []
        for opponent, lower_y, old_n, old_round in self.history:
            if old_n == n:
                weight = 0.985 ** max(0, round_number - old_round - 1)
                rows.append((opponent, weight, x))
        rows.sort()
        
        thresholds = []
        prefix_w = [0.0]
        prefix_v = [0.0]
        for opponent, weight, value in rows:
            thresholds.append(opponent)
            prefix_w.append(prefix_w[-1] + weight)
            prefix_v.append(prefix_v[-1] + weight * value)

        bids = {0.0, ceiling}
        bids.update(ceiling * j / 40.0 for j in range(1, 40))
        bids.update(v for v in thresholds if 0.0 <= v <= ceiling)
        
        floor = self.market_min
        width = max(1.0, self.market_range)
        seed_bid = (floor + (n - 1.0) / n * (x - floor))
        bids.add(max(0.0, min(ceiling, seed_bid)))

        best_bid = 0.0
        best_gain = -math.inf
        
        for bid in sorted(bids):
            if time.perf_counter() - start_time > 0.85:
                break
                
            count = bisect_right(thresholds, bid)
            empirical = prefix_v[count] - bid * prefix_w[count]
            uniform_cdf = max(0.0, min(1.0, (bid - floor) / width))
            prior_gain = (x - bid) * uniform_cdf ** (n - 1)
            gain = empirical + 4.0 * prior_gain
            
            if gain > best_gain:
                best_gain = gain
                best_bid = bid
                
        return best_bid

    def get_bid(self, obs):
        start_time = time.perf_counter()
        
        try:
            x = float(obs.get("x", 0.0))
            capital = float(obs.get("capital", 0.0))
            max_bid = float(obs.get("max_bid") or capital)
            
            if not all(math.isfinite(v) for v in (x, capital, max_bid)):
                return 0.0
            if capital <= 0.0 or max_bid <= 0.0 or x <= 0.0:
                return 0.0
                
            round_number = int(obs.get("round", 1))
            start_players = self.config.get("num_players", 20)
            round_in_block = ((round_number - 1) % 500) + 1
            estimated_n = max(2, start_players - (round_in_block // 35))
            n = max(1, int(obs.get("num_players") or estimated_n))
            
            block = (round_number - 1) // 500
            reset_needed = block != self.block
            
            if self.previous is not None and not reset_needed:
                previous_round, previous_x, previous_capital, previous_n = self.previous
                payoff = float(obs.get("my_last_payoff") or 0.0)
                expected = previous_capital + payoff
                reset_needed = (round_number != previous_round + 1 or not math.isfinite(expected) or abs(capital - expected) > 1e-7 * max(1.0, capital))
                
            if reset_needed:
                self.reset(block, capital)
            elif self.previous is not None:
                self.record_feedback(obs)

            self.estimate_market(x)
            
            ceiling = min(x - 0.01, capital, max_bid)
            bid = 0.0 if n == 1 else self.choose_bid(x, ceiling, n, round_number, start_time)
            self.previous = (round_number, x, capital, n)
            
            if not math.isfinite(bid):
                return 0.0
                
            return float(max(0.0, min(bid, ceiling)))
        except Exception:
            return 0.0