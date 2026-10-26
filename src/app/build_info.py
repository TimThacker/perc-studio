"""Version of this build.

The release build (`packaging/build_release.py`) stamps `BUILD_COMMIT` in the
copy it bundles; it is empty in a source checkout.
"""

from __future__ import annotations

__version__ = "1.2.0"

BUILD_COMMIT = ""
