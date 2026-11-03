import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main(["run", "--config", "configs/sma_crossover.toml", *sys.argv[1:]]))
