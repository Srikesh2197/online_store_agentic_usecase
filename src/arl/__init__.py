from pathlib import Path

# The repository root. The package is installed in editable mode, so config/ and
# tickets/ are read from the checkout.
ROOT = Path(__file__).resolve().parents[2]
