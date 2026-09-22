from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.network.proxy import DIRECT, ProxyConfigError, load_saved_proxy, resolve_startup_proxy, save_and_apply, save_proxy, validate_proxy_url
from src.network import proxy as proxy_module


def test_validate_proxy_url_accepts_supported_hosts_and_rejects_auth() -> None:
    assert validate_proxy_url("HTTP://Proxy.Example:8080") == "http://proxy.example:8080"
    assert validate_proxy_url("socks5://[2001:db8::1]:1080") == "socks5://[2001:db8::1]:1080"
    with pytest.raises(ProxyConfigError):
        validate_proxy_url("http://user:pass@example:8080")


def test_saved_proxy_round_trip_and_environment_precedence(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"SONEX_HOME": str(tmp_path), "SONEX_PROXY": ""}, clear=False):
        save_proxy(proxy_module.ProxyConfig(mode="proxy", url="http://file.example:8080", source="test"))
        assert load_saved_proxy().url == "http://file.example:8080"
        with patch.dict("os.environ", {"SONEX_PROXY": "socks5://env.example:1080"}, clear=False):
            resolved = resolve_startup_proxy()
        assert resolved.source == "environment"
        assert resolved.url == "socks5://env.example:1080"
        payload = json.loads((tmp_path / "proxy.json").read_text())
        assert payload["url"] == "http://file.example:8080"


def test_direct_mode_retains_saved_address(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"SONEX_HOME": str(tmp_path), "SONEX_PROXY": ""}, clear=False):
        save_proxy(proxy_module.ProxyConfig(mode="proxy", url="http://file.example:8080", source="test"))
        save_and_apply(DIRECT)
        assert json.loads((tmp_path / "proxy.json").read_text())["url"] == "http://file.example:8080"
