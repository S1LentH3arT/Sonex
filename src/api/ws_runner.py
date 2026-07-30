"""Backward-compatible import path for the websocket runner.

The implementation lives in :mod:`src.ws.runner`.  This module intentionally
aliases itself to that module so existing imports and test patch paths like
``src.api.ws_runner.search_local_file`` keep targeting the active runtime
module object.
"""

from __future__ import annotations

import sys

from src.ws import runner as _runner

sys.modules[__name__] = _runner
