class sampleAlpha:
    def __init__(
        self,
        universe,
        resolution,
        ticker,
        start,
        end,
        short_window=5,
        long_window=20,
    ):
        self.universe = universe
        self.resolution = resolution
        self.ticker = ticker
        self.current_time = start
        self.start = start
        self.end = end

        self.short_window = short_window
        self.long_window = long_window

        self.price_history = []
        self.short_ma = None
        self.long_ma = None
        self.position = 0

    def get_weight(self):
        return self.weight

    def get_ticker(self):
        return self.ticker

    def set_time(self, time):
        self.current_time = time

    def add_prices(self, price):
        """Adds new price data and update moving averages"""
        price = price["SPY_close"][0]
        self.price_history.append(price)

        # Calculate moving averages if we have enough data
        if len(self.price_history) >= self.short_window:
            self.short_ma = (
                sum(self.price_history[-self.short_window :]) / self.short_window
            )

        if len(self.price_history) >= self.long_window:
            self.long_ma = (
                sum(self.price_history[-self.long_window :]) / self.long_window
            )

    def update(self):
        """
        Update the strategy based on current price data
        Returns the current weight/position size
        """

        if self.short_ma is None or self.long_ma is None:
            return [1, 0]

        return [1, 0] if self.short_ma > self.long_ma else [0, 1]
