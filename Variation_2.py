import math
import time

class Bot:
    def __init__(self, config):
        self.config = dict(config or {})
        self.min_x = 10000.0
        self.ema_X = None
        self.last_capital = None
        # Start at high aggression (0.85) to eliminate early passive rounds
        self.alpha = 0.85  
        self.losses_in_a_row = 0
        
    def get_bid(self, obs):
        start_time = time.perf_counter()
        
        try:
            current_round = int(obs.get("round", 1))
            x_val = float(obs.get("x", 0.0))
            capital = float(obs.get("capital", 0.0))
            max_bid = float(obs.get("max_bid") or capital)
            
            # Input sanity and insolvency filter
            if not all(math.isfinite(v) for v in (x_val, capital, max_bid)):
                return 0.0
            if capital <= 0.0 or max_bid <= 0.0 or x_val <= 0.0:
                return 0.0
            
            # Deterministic 500-round block reset
            if current_round % 500 == 1:
                self.min_x = 10000.0
                self.ema_X = None
                self.last_capital = None
                self.alpha = 0.85 
                self.losses_in_a_row = 0
                
            self.min_x = min(self.min_x, x_val)
            m_b = max(100.0, (int(self.min_x) // 10) * 10.0)
            
            if self.ema_X is None:
                self.ema_X = x_val
                
            # Asymmetric prize radar with fast upward tracking
            actual_last_X = float(obs.get("max_value_last_round") or 0.0)
            if actual_last_X > 0.0 and current_round % 500 != 1:
                if actual_last_X < self.ema_X:
                    self.ema_X = 0.50 * self.ema_X + 0.50 * actual_last_X
                else:
                    # 25% weight accelerates response to aggressive prize spikes
                    self.ema_X = 0.75 * self.ema_X + 0.25 * actual_last_X
                    
            # Adaptive aggression control based on capital feedback
            if self.last_capital is not None:
                if capital > self.last_capital + 1e-6:
                    # Win: shade down slowly (-0.02) to lock in profit margin
                    self.alpha = max(0.20, self.alpha - 0.02)
                    self.losses_in_a_row = 0
                else:
                    self.losses_in_a_row += 1
                    # Loss: react after two dry rounds (+0.05) to stop starvation
                    if self.losses_in_a_row > 1:
                        self.alpha = min(0.99, self.alpha + 0.05)
                        
            self.last_capital = capital
            
            # Calculate interpolated target valuation
            expected_X = max(x_val, self.ema_X)
            smart_bid = m_b + self.alpha * (expected_X - m_b)
            baseline_bid = 0.51 * x_val
            bid = max(smart_bid, baseline_bid)
            
            # Speculative leverage expanded to 50% capital
            speculation_limit = x_val + 0.50 * capital
            # Squeeze safe prize cap to 0.99 * E[X] to outbid competitors
            safe_prize_cap = expected_X * 0.99
            ceiling = min(speculation_limit, safe_prize_cap, capital, max_bid)
            
            # Server timeout ejector
            if time.perf_counter() - start_time > 0.85:
                return 0.0
                
            safe_bid = min(bid, ceiling)
            return float(max(0.0, safe_bid))
            
        except Exception:
            return 0.0