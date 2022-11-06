from datetime import datetime
import logging

class DataFeed:
    
    def __init__(self):
        self.logger = logging.getLogger("deribit")
        self.ob = dict() # THE WHOLE ORDERBOOK
        self.oi = dict()
        self.btcusd_best_bid = 0
        self.btcusd_best_ask = 0
        self.account = {}
        self.orders = {}
        self.trades = {}
        self.positions = {}
        self.contracts = []
    
    def update_contracts(self, contracts):
        self.contracts = contracts
    
    def initial_open_orders(self, data):
        for order in data:
            order["replaced"] = False
            order["original_order_type"] = "limit"
            instrument_name = order["instrument_name"]
            order_id = order["order_id"]
            
            if instrument_name not in self.orders:
                self.orders[instrument_name] = {order_id : order}
            else:
                self.orders[instrument_name][order_id] = order
            
    
    def initial_positions(self, data):
        for position in data:
            instrument_name = position["instrument_name"]
            self.positions[instrument_name] = position
        
        
    def update_positions(self, data):
        
        for i in range(len(data)):
        
            instrument_name = data[i]["instrument_name"]
            side = data[i]["direction"]
            amount = data[i]["amount"]
            entry = data[i]["price"]
            
            if instrument_name not in self.positions:
                self.positions[instrument_name] = data[i]
                
            
            if (side == "buy" and self.positions[instrument_name]["direction"] == "buy") or (side == "sell" and self.positions[instrument_name]["direction"] == "sell"):
                
                prev_amount = self.positions[instrument_name]["size"]
                prev_entry = self.positions[instrument_name]["average_price"]
                
                new_entry = round(prev_entry * (prev_amount / (prev_amount + amount)) + entry * (amount / (prev_amount + amount)), 2)
                
                self.positions[instrument_name]["average_price"] = new_entry
                self.positions[instrument_name]["size"] += amount
                
            else:
                
                if amount > self.positions[instrument_name]["size"]:
                    self.positions[instrument_name]["size"] = abs(amount - self.positions[instrument_name]["size"])
                    self.positions[instrument_name]["direction"] = side
                    
                else:
                    self.positions[instrument_name]["size"] -= amount
            
    
    def manage_orders(self, data):
        instrument_name = data["instrument_name"]
        order_id = data["order_id"]
        
        if data["order_type"] != "rejected":
            
            if data["order_type"] != "market":
                
                if instrument_name not in self.orders.keys():
                    self.orders[instrument_name] = {}
                
                
                if order_id in self.orders[instrument_name].keys():
                    if data["order_state"] == "cancelled": # cancelled orders are taken out of dictionary
                        del self.orders[instrument_name][order_id]
                        
                    elif (data["order_state"] == "filled" and data["filled_amount"] == data["max_show"]): # fully filled orders need to be taken out of the open_orders dictionary
                        del self.orders[instrument_name][order_id]
                    
                    else: # partially filled, and generally open orders which are already in the system
                        self.order[instrument_name][order_id] = data
                        
                else: # open orders which are not in the system yet
                    self.orders[instrument_name][order_id] = data
                    
        else:
            print("ORDER REJECTED! Check margin balance?")
    
    
    
    def manage_portfolio(self, data):
        
        self.account["available_funds"] = data["available_funds"]
        self.account["balance"] = data["balance"]
        self.account["deribit_delta"] = data["delta_total"]
        self.account["initial_margin"] = data["initial_margin"]
        self.account["maintenance_margin"] = data["maintenance_margin"]
        self.account["margin_balance"] = data["margin_balance"]
        
        
    def manage_option_oi(self, msg):
        self.oi[msg["instrument_name"]] = msg["open_interest"]
        
        
    def build_ob_from_snapshots(self, snapshot):
        bids = dict()
        for bid in snapshot["bids"]:
            bids[bid[1]] = bid[2]
        asks = dict()
        for ask in snapshot["asks"]:
            asks[ask[1]] = ask[2]
        self.ob[snapshot["instrument_name"]] = {"bids":bids, "asks":asks}
        
        
    def update_ob(self, msg):
        contract = msg["instrument_name"]
        for side in ["bids", "asks"]:
            if len(msg[side]) > 0:
                for i in msg[side]:
                    if i[0] == "delete":
                        del self.ob[contract][side][i[1]]
                    elif i[0] == "new" or i[0] == "change":
                        self.ob[contract][side][i[1]] = i[2]
                    else:
                        pass        
        
    
    def get_orders(self):
        return self.orders
    
    def get_account_data(self):
        return self.account_data
    
    def get_trades(self):
        return self.trades
    
    def fetch_local_ob(self):
        return self.ob
    
    def fetch_local_oi(self):
        return self.oi
    
