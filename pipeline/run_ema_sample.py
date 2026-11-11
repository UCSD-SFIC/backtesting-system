import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main(["run", "--config", "configs/ema_dip.toml", *sys.argv[1:]]))
