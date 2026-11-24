"""Stand-in for chip2x2/scripts/magic_util.py when an accepted GDS-only script is run from takeover/layout: the accepted
scripts sheet_check.py and amp_straps.py import magic_util only for a default path (TT_PROJECT). The real module is not
imported because importing the v4 copy creates folders in the v4 build area."""
from pathlib import Path
TT_PROJECT = Path("/nonexistent-default-path-always-pass-the-gds")
