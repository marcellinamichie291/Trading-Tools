import websocket
from datetime import datetime, timedelta
import json
import time
import secrets
import hmac
import hashlib
import threading
import traceback
import sys
import pytz
import logging

class WSClient:
    
    """
    This class does several things:
    1. The Websocket client is set up and run.
    2. It contains different methods to handle incoming messages
    3. It runs a series of functions to authenticate the program with the exchange, 
        and subscribe to all sorts of channels.
    4. It sends incoming messages to the message_processor module
    """
    
    def __init__(self, feed, delta_hedger, api_key, api_secret):
        
        self.feed = feed
        self.delta_hedger = delta_hedger
        self.logger = logging.getLogger("deribit")
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://www.deribit.com/ws/api/v2"
        
        self.do_not_reconnect = False
        
        self.error_counter = 0
        self.ping_interval = 5
        self.ping_timeout = 2
        
        self.api_call_id_counter = 0 # unique, ascending ID to match response with received message
        self.api_call_types = ["public/get_instruments", "public/subscribe", 
                               "public/auth", "private/subscribe", 
                               "private/get_positions", "private/buy", 
                               "private/get_open_orders_by_currency"] # different types of requests that need to be handled differently
        
        self.api_call_ids = dict() # will contain all IDs per call type in order to distribute incoming message efficiently to correct function
        
        self.build_api_call_ids() # build the previous dictionary (just above)
        self.active_contracts_list = [] # will contain all active options contracts once they have been received
        
        self.connected = False        
        self.authenticated = False # True as soon as authentication confirmation is received
        self.got_active_contracts = False # True as soon as program knows all active options contracts
        self.subscribed_public = False # True as soon as subscription confirmations for options orderbooks are received
        self.subscribed_private = False 
        
        self.public_subscription_count = 0
        self.private_subscription_count = 0
        
        self.connection_age = datetime.now(pytz.UTC)
        
        
        
    def create_ws_connection(self):
        self.logger.info("Connecting to Websocket.")
        self.ws = websocket.WebSocketApp(self.ws_url, 
                                         on_open=self.on_open, 
                                         on_message=self.on_message, 
                                         on_error=self.on_error, 
                                         on_close=self.on_close, 
                                         on_ping=self.on_ping, 
                                         on_pong=self.on_pong)
        
        self.t1 = threading.Thread(target=lambda: self.ws.run_forever(
            skip_utf8_validation=True, 
            ping_interval=self.ping_interval, 
            ping_timeout=self.ping_timeout))
        
        self.t1.start()
        
        self.wait_for_connection()
        self.initiate_streams()
        
    
    def on_open(self, placeholder):
        self.connected = True
        self.logger.info("Connected to Websocket: {}.".format(self.connected))
        self.connection_age = datetime.now(pytz.UTC)
        
        
    def on_message(self, placeholder, data):
        try:
            self.message_distribution(data)
        except KeyboardInterrupt:
            self.shutdown()
        
        
    def on_error(self, placeholder, error):
        self.connected = False
        self.error_counter += 1
        self.logger.info("({}) - Error: {}. Closing Websocket connection and "
                         "reconnecting shortly.".format(self.error_counter, 
                                                        error))

        self.close_ws()
        
        wait_time = 0
        if self.error_counter <= 3:
            wait_time = 1
        elif self.error_counter > 3 and self.error_counter < 10:
            wait_time = 5
        else:
            wait_time = 15
        self.logger.debug("Waiting {}s before attempting reconnection.".format(wait_time))
        time.sleep(wait_time)
        
        if not self.do_not_reconnect:
            if not self.connected:
                self.logger.info("Reconnecting to Websocket.")
                self.create_ws_connection()
    
    
    def on_close(self, placeholder, status, message):
        self.connected = False
        self.logger.info("Closing Websocket.")

        
    
    def on_ping(self, placeholder, msg):
        pass
    
    
    def on_pong(self, placeholder, msg):
        self.connected = True
        now = datetime.now(pytz.UTC)
        if (now - self.connection_age).total_seconds() > 60:
            self.error_counter = 0
    
    
    def shutdown(self):
        self.do_not_reconnect = True
        self.delta_hedger.stop_hedger = True
        self.logger.info("KeyboardInterrupt. Disabling reconnection attempts.")
        self.close_ws()
    
            
    def close_ws(self):
        self.reset_vars()
        self.ws.close()
        
        
    def reset_vars(self):
        self.connected = False
        self.authenticated = False
        self.active_contracts_list = []
        self.got_active_contracts = False
        self.subscribed_public = False
        self.subscribed_private = False
        self.public_subscription_count = 0
        self.private_subscription_count = 0
        
    
    def send_to_ws(self, data, call_type):        
        call_id = self.api_call_id_counter
        message_to_send = {"jsonrpc" : "2.0", 
                           "id" : call_id, 
                           "method" : call_type, 
                           "params" : data}
        
        json_message_to_send = json.dumps(message_to_send)
        self.ws.send(json_message_to_send)
        self.add_api_call_id(call_type, call_id)
        
    
    def authenticate(self):
        
        clientId = self.api_key
        clientSecret = self.api_secret

        call_type = "public/auth"
        timestamp = round(datetime.now().timestamp() * 1000)
        nonce = secrets.token_hex(32)
        data = ""
        signature = hmac.new(
            bytes(clientSecret, "latin-1"),
            msg=bytes('{}\n{}\n{}'.format(timestamp, nonce, data), "latin-1"),
            digestmod=hashlib.sha256
        ).hexdigest().lower()
        
        message = {"grant_type": "client_signature", "client_id": clientId, 
                   "timestamp": timestamp, "nonce": nonce, "data": data, 
                   "signature": signature}
        
        self.send_to_ws(message, call_type)
        
        
    def get_instruments(self):
        call_type = "public/get_instruments"
        message = {"currency" : "BTC", "kind" : "option", "expired" : False}
        self.send_to_ws(message, call_type)
        
    
    def build_subscriptions(self, contracts):
        mid = round(len(contracts) / 2)
        ob_channels_1 = ["book." + str(contract) + ".raw" for contract in contracts[:mid]]
        ob_channels_2 = ["book." + str(contract) + ".raw" for contract in contracts[mid:]]
        oi_channels_1 = ["ticker." + str(contract) + ".raw" for contract in contracts[:mid]]
        oi_channels_2 = ["ticker." + str(contract) + ".raw" for contract in contracts[mid:]]
        
        private_channels = ["user.orders.any.any.raw", "user.portfolio.btc", 
                          "user.trades.any.any.raw"]
        public_channels = ["book.BTC-PERPETUAL.none.1.100ms", "trades.BTC-PERPETUAL.raw"]
        
        channels = [ob_channels_1, ob_channels_2, oi_channels_1, oi_channels_2, 
                    private_channels, public_channels]
        
        for channel in channels:
            if channel == private_channels:
                call_type = "private/subscribe"
            else:
                call_type = "public/subscribe"            
            message = {"channels": channel}
            self.send_to_ws(message, call_type)
            time.sleep(0.2)
            
            
    def get_positions(self):
        call_type = "private/get_positions"
        currency = "BTC"
        kind = ["future", "option"]
        for k in kind:
            message = {"currency":currency, "kind":k}
            self.send_to_ws(message, call_type)
    
    
    def get_open_orders(self):
        call_type = "private/get_open_orders_by_currency"
        currency = "BTC"
        typ = "all"
        message = {"currency":currency, "type":typ}
        self.send_to_ws(message, call_type)
    
    
    def wait_for_connection(self):
        while True:
            if self.connected:
                return True
            else:
                time.sleep(0.1)
    
    
    def wait_for_auth(self):
        while True:
            if self.authenticated:
                return True
            else:
                time.sleep(0.1)
        
        
    def wait_for_instruments(self):
        while True:
            if self.got_active_contracts:
                return True
            else:
                time.sleep(0.1)
        
        
    def wait_for_subscriptions(self):
        while True:
            if self.subscribed_public and self.subscribed_private:
                self.logger.info("Authenticated and subscribed. Systems ready.")
                return True
            else:
                time.sleep(0.1)
    
    
    def initiate_streams(self):
        try:
            if not self.authenticated:
                self.authenticate()
                
            self.wait_for_auth()
            
            self.get_open_orders()
            self.get_positions()
            
            if not self.got_active_contracts:
                self.get_instruments()
                
            self.wait_for_instruments()
            
            if ((not self.subscribed_public) and (not self.subscribed_private)):
                self.build_subscriptions(self.active_contracts_list)
                
            self.wait_for_subscriptions()
            
        except KeyboardInterrupt:
            self.shutdown()
            
        
    def message_distribution(self, reply):
        reply = json.loads(reply)
        
        if "id" in reply:
            if "result" in reply:
                # Ensures that messages from channel subscriptions do not use up time to check for IDs, since they just need to be processed in the book build
                # Except for own account channel !!!!!!!!!!
                if reply["id"] in self.api_call_ids["public/get_instruments"]:
                    self.collect_active_contracts(reply)

                elif reply["id"] in self.api_call_ids["public/auth"]:
                    if reply["result"]["token_type"] == "bearer":
                        self.authenticated = True
                        self.logger.info("Authentication successful: {}".format(self.authenticated))
                    else:
                        self.authenticated = False
                        
                elif reply["id"] in self.api_call_ids["public/subscribe"]:
                    self.public_subscription_count += 1
                    if self.public_subscription_count == 5:
                        self.subscribed_public = True
                        
                elif reply["id"] in self.api_call_ids["private/subscribe"]:
                    self.private_subscription_count += 1
                    if self.private_subscription_count == 1:
                        self.subscribed_private = True
                    
                elif reply["id"] in self.api_call_ids["private/get_positions"]:
                    self.feed.initial_positions(reply["result"])
                    
                elif reply["id"] in self.api_call_ids["private/get_open_orders_by_currency"]:
                    self.feed.initial_open_orders(reply["result"])
                
                else:
                    self.logger.info("Unhandled reply: {}".format(reply))
            else:
                self.logger.info("Unhandled reply: {}".format(reply))
        elif "method" not in reply:
            self.logger.info("Unhandled reply: {}".format(reply))
                
        
        if "method" in reply:
            
            if reply["method"] == "subscription":
                if "params" in reply:
                    if "channel" in reply["params"]:
                        if "data" in reply["params"]:
                            if reply["params"]["channel"] == "book.BTC-PERPETUAL.none.1.100ms":
                                self.feed.btcusd_best_bid = reply["params"]["data"]["bids"][0][0]
                                self.feed.btcusd_best_ask = reply["params"]["data"]["asks"][0][0]
                                
                            elif reply["params"]["channel"][:9] == "book.BTC-":
                                if "type" in reply["params"]["data"]:
                                    if reply["params"]["data"]["type"] == "snapshot":
                                        self.feed.build_ob_from_snapshots(reply["params"]["data"])
                                    
                                    elif reply["params"]["data"]["type"] == "change":
                                        self.feed.update_ob(reply["params"]["data"])
                            
                            elif reply["params"]["channel"][:11] == "ticker.BTC-":
                                self.feed.manage_option_oi(reply["params"]["data"])                            
                            
                            elif reply["params"]["channel"] == "user.orders.any.any.raw":
                                self.feed.manage_orders(reply["params"]["data"])
                                
                            elif reply["params"]["channel"] == "user.portfolio.btc":
                                self.feed.manage_portfolio(reply["params"]["data"])
                                self.delta_hedger.check_deltas(self.send_to_ws)
                                
                                
                            elif reply["params"]["channel"] == "user.trades.any.any.raw":
                                self.feed.update_positions(reply["params"]["data"])
                                self.delta_hedger.check_deltas(self.send_to_ws)
                                
                                
                            # if "timestamp" in reply["params"]["data"]:
                            #     self.convert_ts(reply["params"]["data"]["timestamp"])
        
    
    def build_api_call_ids(self):
        for i in self.api_call_types:
            self.api_call_ids[i] = []
            
                    
    def add_api_call_id(self, call_type, call_id):
        self.api_call_ids[call_type].append(call_id)
        self.api_call_id_counter += 1
    
    
    def collect_active_contracts(self, data):
        for i in range(len(data["result"])):
            self.active_contracts_list.append(data["result"][i]["instrument_name"])
            
        if len(self.active_contracts_list) > 0:
            self.feed.update_contracts(self.active_contracts_list)                    
            self.got_active_contracts = True        
        
        
    def convert_ts(self, tsunix):
        millis = int(str(tsunix)[-3:])
        ts = int(str(tsunix)[:-3])
        ts = datetime.fromtimestamp(ts, tz=pytz.UTC)
        ts = ts + timedelta(milliseconds=millis)
        
