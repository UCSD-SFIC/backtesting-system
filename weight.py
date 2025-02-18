import polars as pl
import numpy as np
import pandas as pd

def validate_weights(weights_df, tickers):
    """
    Validates that portfolio weights sum to less than or equal to 1 at each timestamp
    
    """
    # Calculate sum of weights at each timestamp
    weight_sums = weights_df.select([
        pl.col("timestamp"),
        pl.sum_horizontal([pl.col(ticker) for ticker in tickers]).alias("total_weight")
    ])
    
    # Check if any timestamp has total weight > 1
    invalid_weights = weight_sums.filter(pl.col("total_weight") > 1)
    
    if invalid_weights.height > 0:
        error_dates = invalid_weights.select("timestamp").to_series().to_list()
        error_weights = invalid_weights.select("total_weight").to_series().to_list()
        raise ValueError(
            f"Portfolio weights exceed 1 at following timestamps:\n" + 
            "\n".join([f"Date: {date}, Total Weight: {weight:.3f}" 
                      for date, weight in zip(error_dates, error_weights)])
        )
    
def gen_weight():
    """
    Generates a DataFrame of portfolio weights over time.

    """
    stock1 = "NVDA"
    stock2 = "UVXY"
    tickers = [stock1, stock2]      
    weights = pl.DataFrame(
        {
            stock1: [0.9, 0],
            stock2: [0.1, 1],
            "timestamp": pl.Series(
                ["01/01/2024 17:00:00.000", "06/06/2024 17:00:00.000"]
            ).str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S%.3f"),
        }
    )
    validate_weights(weights, tickers)
    return weights,tickers