"""What: `python3 -m traces` entry point.
Why: works before the console script is on PATH.
How: python3 -m traces --help
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
