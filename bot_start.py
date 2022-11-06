from datetime import datetime
import pytz
import psycopg2
import threading
import time
from sqlalchemy import create_engine
import logging

from ws_client import WSClient
from save_top_of_book import SaveBBO
from data_feed import DataFeed
from hedger import DeltaHedge
import configparser


class Bot:
    
    """ Instantiates some other modules and sets them in motion """
    
    def __init__(self):
        self.logger = logging.getLogger("deribit")
        config = configparser.RawConfigParser()
        config.read_file(open("settings.txt"))
        
        self.api_information = dict(config.items("API"))
        self.database_information = dict(config.items("PostgreSQL"))
        
        database = self.database_information["database"]
        user = self.database_information["user"]
        password = self.database_information["password"]
        host = self.database_information["host"]
        port = self.database_information["port"]
        if host == "localhost":
            host_numeric = "127.0.0.1"
        else:
            host_numeric = host
        
        self.conn = psycopg2.connect(database=database, 
                                     user=user, 
                                     password=password, 
                                     host=host, 
                                     port=port)
        
        self.c = self.conn.cursor()
        self.db_connection_url = "postgresql://{}:{}@{}:{}/{}".format(database, 
                                                                      password, 
                                                                      host_numeric, 
                                                                      port,
                                                                      user)
        self.engine = create_engine(self.db_connection_url)
        
        db_connection = {"c":self.c, "conn":self.conn, "engine":self.engine}
        
        self.api_key = self.api_information["api_key"]
        self.api_secret = self.api_information["api_secret"]
        
        self.feed = DataFeed()
        
        self.delta_hedger = DeltaHedge(self.feed)
        
        self.client = WSClient(self.feed, self.delta_hedger, 
                               self.api_key, self.api_secret)
        
        self.save_bbo = SaveBBO(self.feed, db_connection)
        
        
        
    def run(self):
        
        if not self.client.connected:
            self.logger.info("Starting websocket-client.")
            self.client.create_ws_connection()
            
        """ Create separate thread to periodically store top-of-the-book 
        snapshots to a local database"""
        
        self.logger.info("Starting BBO scheduling thread.")
        self.save_bbo_thread = threading.Thread(target=lambda: self.save_bbo.schedule_snapshot())
        self.save_bbo_thread.start()
        
        """ Reconnect every day at around 8:00 AM UTC 
        in order to subscribe to newly introduced contracts """
        
        while True:
            try:
                now = datetime.now(pytz.UTC)
                if (now.hour == 8 and now.minute == 0 and now.second == 0):
                    self.client.close_ws()
                    time.sleep(1)
                    self.client.create_ws_connection()
                else:
                    time.sleep(0.4)
                    
            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt - Shutting down.")
                self.save_bbo.stop_taking_snapshots = True
                self.client.do_not_reconnect = True
                self.client.shutdown()
                time.sleep(2)
                break
            
            
