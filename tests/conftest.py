"""Suite-wide test environment setup.

Must run before any test module imports ``app.main``: the tests hammer the
real app through one TestClient (dozens of signups per run), so rate limiting
is disabled for the whole suite. ``tests/test_rate_limit.py`` re-enables it
per-test by flipping the settings singleton.
"""

import os

os.environ["RATE_LIMIT_ENABLED"] = "false"
