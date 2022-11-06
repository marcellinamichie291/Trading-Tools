import threading
from py_vollib_vectorized import vectorized_implied_volatility as viv
from datetime import datetime
import pytz
from scipy.stats import norm
import numpy as np
import logging
import time

class DeltaHedge:
    
    def __init__(self, feed):
        
        self.feed = feed
        self.logger = logging.getLogger("deribit")
        self.delta_hedging_activated = False
        self.stop_hedger = False
        self.hedging_thread = threading.Thread(target=lambda: self.wait_for_input())
        self.hedging_thread.start()
        self.months = {"JAN":1, "FEB":2, "MAR":3, "APR":4, "MAY":5, "JUN":6, 
                       "JUL":7, "AUG":8, "SEP":9, "OCT":10, "NOV":11, "DEC":12}
        
        self.max_delta_mismatch = 0.025
        
        self.op_delta = 0
        self.btcperp_delta = 0
        self.send_to_ws = None
    
    def check_deltas(self, send_method):
        
        self.send_to_ws = send_method
        current_options_delta, current_perp_delta = self.determine_option_delta()
        
        if not self.delta_hedging_activated:
            pass
        
        else:
            if abs(current_options_delta) > 0:
                if (1 - self.max_delta_mismatch < ((current_perp_delta * -1) / current_options_delta) < 1 + self.max_delta_mismatch):
                    self.rehedge(current_options_delta, current_perp_delta)

    
    def determine_option_delta(self):
        
        positions = self.feed.positions.copy()
        perp_delta = 0
        if "BTC-PERPETUAL" in positions.keys():
            btc_perp_position = positions["BTC-PERPETUAL"]["size"]
            btc_perp_position_side = positions["BTC-PERPETUAL"]["direction"]
            if btc_perp_position_side == "buy":
                perp_delta = btc_perp_position
            else:
                perp_delta = btc_perp_position * -1
        else:
            pass
        
        
        keys_to_delete = []
        
        for key in positions.keys():
            if (str(key)[-1] != "P" and str(key)[-1] != "C"):
                keys_to_delete.append(key)
            elif positions[key]["size"] == 0:
                keys_to_delete.append(key)
                
        for key in keys_to_delete:
            del positions[key]
        
        
        option_delta = 0
        
        if len(positions) > 0:
        
            for key in positions.keys():
                name = str(positions[key]["instrument_name"])
                size = positions[key]["size"]
                btcusd_price = (self.feed.btcusd_best_ask + self.feed.btcusd_best_bid) / 2
                price = positions[key]["mark_price"] * btcusd_price
                
                first = name.find("-")
                second = name.find("-", first+1)
                third = name.find("-", second+1)
                
                typ = name[-1]
                exp = name[first+1:second]
                strike = int(name[second+1:third])
                
                year = int(exp[-2]) + 2000
                month = self.months[exp[-5:-2]]
                day = int(exp[:-5])
                
                expiration = datetime(year, month, day, 8, 0, 0, 0, pytz.UTC)
                ttmyears = ((expiration - datetime.now(pytz.UTC)).total_seconds()) / (60*60*24*365)
                
                iv = viv(price, self.feed.btcusd_best_bid, strike, ttmyears, 0, typ.lower(), 0, on_error="ignore", model='black_scholes_merton', return_as = 'numpy').round(4)
                delta = self.bsm(btcusd_price, strike, iv, 0, 0, ttmyears, typ.lower(), "delta")
                delta = delta * size * btcusd_price
                option_delta += delta
        
        self.op_delta = option_delta
        self.btcperp_delta = perp_delta
        
        return option_delta, perp_delta
    
    
    
    def rehedge(self, option_delta, perp_delta):
        side = ""
        target = option_delta * -1
        diff = perp_delta - target
        
        if diff > 0:
            side = "sell"
            price = self.feed.btcusd_best_bid
        else:
            side = "buy"
            price = self.feed.btcusd_best_ask
            
        call_type = "private/{}".format(side)
        
        self.logger.info("Rehedging. {} {} at market.".format(side, abs(diff)))
        
        message = {"instrument_name":"BTC-PERPETUAL", "amount":abs(diff), 
                   "type":"limit", "label":"delta_hedge", "price":price}
        self.send_to_ws(message, call_type)
        
        
    def wait_for_input(self):
        
        while True:
            
            if not self.stop_hedger:
                time.sleep(0.5)
                if not self.delta_hedging_activated:
                    x = input("Activate dynamic Delta-Hedging? (y/n)\n")
                    if x == "y":
                        self.delta_hedging_activated = True
                        self.logger.info("Dynamic delta-hedging activated: "
                                         "{}".format(self.delta_hedging_activated))
                        self.check_deltas(self.send_to_ws)            
                else:
                    x = input("Deactivate dynamic Delta-Hedging? (y/n)\n")
                    if x == "y":
                        self.delta_hedging_activated = False
                        self.logger.info("Dynamic delta-hedging activated: "
                                         "{}".format(self.delta_hedging_activated))
                        
            else:
                break
            
            
            
    def bsm(self, S,X,sigma, r, q, ttm, otype, greek):
        t = float(ttm)
        X = float(X)
        r = float(r)
        b = float(r - q)
        
        d1 = (np.log(S/X) + (b + (sigma**2)/2)*t) / (sigma * np.sqrt(t))
        d2 = d1 - sigma * np.sqrt(t)
    
        if greek == "vanna":
            vanna = ((-np.exp((b-r)*t)*d2)/sigma)*norm.pdf(d1)
            return vanna / 100
        elif greek == "charm":
            if(otype == "c"):
                charm = -np.exp((b-r)*t)*((norm.pdf(d1)*(b/(sigma*np.sqrt(t))-(d2/(2*t)))) + (b-r)*norm.cdf(d1))
            elif(otype == "p"):
                charm = -np.exp((b-r)*t)*((norm.pdf(d1)*(b/(sigma*np.sqrt(t))-(d2/(2*t))) - (b-r)*norm.cdf(-d1)))
            return charm 
        elif greek == "price":
            if(otype == "c"):
                price = S * np.exp((b-r)*t) * norm.cdf(d1) - X * np.exp(-r *t)  * norm.cdf(d2)
            elif (otype == "p"):
                price = (X * np.exp(-r *t)  * norm.cdf(-d2) - S * np.exp((b-r)*t) * norm.cdf(-d1))
            return price
        elif greek == "delta":
            if(otype == "c"):
                delta = np.exp((b-r)*t)*norm.cdf(d1)
            elif(otype == "p"):
                delta = -np.exp((b-r)*t)*norm.cdf(-d1)
            return delta 
        elif greek == "gamma":
            gamma = (np.exp((b-r)*t)*norm.pdf(d1)) / (S*sigma*np.sqrt(t))
            return gamma
        elif greek == "vega":
            vega = 0.01*S*np.exp((b-r)*t)*((1/(2*np.pi))*((-d1**2)/2))
            return vega
            
        elif greek == "rho":
            if otype == "c":
                rho = 0.01*X*t*np.exp((b-r)*t)*norm.cdf(d2)
                return rho
            if otype == "p":
                rho = -0.01*X*t*np.exp((b-r)*t)*norm.cdf(-d2)    
                return rho
        elif greek == "d1":
            return d1
        elif greek == "d2":
            return d2
        
        elif greek == "lm":
            return (np.log(S/X) + (b + (sigma**2)/2)*t) / (sigma * np.sqrt(t))
        
        else:
            print("No greek provided.")    
