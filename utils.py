import polars as pl
from time import time


def validate_weights(weights_df, tickers):
    """
    Validates that portfolio weights sum to less than or equal to 1 at each timestamp

    Parameters:
    weights_df (pl.DataFrame): DataFrame containing weights for each ticker
    tickers (list): List of ticker symbols

    Raises:
    ValueError: If weights sum to more than 1 at any timestamp
    """
    # Calculate sum of weights at each timestamp
    weight_sums = weights_df.select(
        [
            pl.col("timestamp"),
            pl.sum_horizontal([pl.col(ticker) for ticker in tickers]).alias(
                "total_weight"
            ),
        ]
    )

    # Check if any timestamp has total weight > 1, using a small tolerance
    tolerance = 1e-10  # Allow for small floating point errors
    invalid_weights = weight_sums.filter(pl.col("total_weight") > (1.0 + tolerance))

    if invalid_weights.height > 0:
        error_dates = invalid_weights.select("timestamp").to_series().to_list()
        error_weights = invalid_weights.select("total_weight").to_series().to_list()
        raise ValueError(
            "Portfolio weights exceed 1 at following timestamps:\n"
            + "\n".join(
                [
                    f"Date: {date}, Total Weight: {weight:.3f}"
                    for date, weight in zip(error_dates, error_weights)
                ]
            )
        )

    # Optionally, check for weights that sum to significantly less than 1
    underweight = weight_sums.filter(pl.col("total_weight") < (1.0 - tolerance))
    if underweight.height > 0:
        print("Warning: Some timestamps have total weights less than 1.0")


def sample_weight():
    """
    Generates a DataFrame of portfolio weights over time.

    """
    stock1 = "NVDA"
    stock2 = "UVXY"
    tickers = [stock1, stock2]
    weights = [0.1, 0.9]
    return weights, tickers


def timeit(func):
    def wrapper(*args, **kwargs):
        start = time()
        result = func(*args, **kwargs)
        end = time()
        print(f"{func.__name__} took {end - start:.2f} seconds")
        return result

    return wrapper
