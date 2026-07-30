import subprocess
import sys


def test_api_ws_runner_aliases_ws_runner_module() -> None:
    code = (
        "import src.api.ws_runner as api_ws_runner;"
        "import src.ws.runner as ws_runner;"
        "raise SystemExit(0 if api_ws_runner is ws_runner else 1)"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
