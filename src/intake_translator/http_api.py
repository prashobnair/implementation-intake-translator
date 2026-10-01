"""Compatibility alias to the loopback-only legacy adapter."""

import sys
from . import http_api_legacy as legacy

if __name__ == "__main__":
    legacy.main()

# Alias the module object so older patch.object(api, ...) callers patch the
# legacy module's globals rather than a stale copy of a constant.
sys.modules[__name__] = legacy
