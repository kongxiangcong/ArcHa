"""Make the source checkout available to core tests."""
import sys
from pathlib import Path

ARCHA = Path(__file__).resolve().parents[2]
if str(ARCHA) not in sys.path:
    sys.path.insert(0, str(ARCHA))
