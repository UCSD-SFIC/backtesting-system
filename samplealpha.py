import polars as pl
import numpy as np  


class sampleAlpha():
    def __init__(self,universe,resolution,weight,ticker,start,end):
        self.universe=universe
        self.resolution=resolution
        self.weight=weight
        self.ticker=ticker
        self.current_time=start
        self.start=start
        self.end=end

    def get_weight(self):
        return self.weight
    
    def get_ticker(self):
        return self.ticker
    
    def set_time(self,time):
        self.current_time=time

    def update(self):
        return self.weight