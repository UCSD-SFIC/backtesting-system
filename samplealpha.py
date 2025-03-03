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
        # Generate random numbers > 0 for each ticker
        random_weights = np.random.random(len(self.ticker))
        
        # Normalize to make sum = 1
        normalized_weights = random_weights / np.sum(random_weights)
        
        return normalized_weights.tolist()