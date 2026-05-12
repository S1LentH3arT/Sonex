import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

def sonex_home() -> Path:
    custom = os.getenv("SONEX_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex"

@dataclass
class ThinkingConfig:
    _model: str
    _api_key: str
    _base_url: str
    _config_path: Path
    _client: Any

    @classmethod
    def init(cls, model: str, config_path: Path = None):
        _load_env_files()

        return cls(
            _model=model,
            _api_key=os.getenv("SONEX_API_KEY"),
            _base_url=os.getenv("SONEX_BASE_URL"),
            _config_path=config_path or _default_config_path(),
            _client=OpenAI(api_key=cls._api_key, base_url=cls._base_url),
        )

    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = OpenAI(api_key=cls._api_key, base_url=cls._base_url)
        return cls._client

    @classmethod
    def get_model(cls):
        if cls._model is None:
            cls._model = "gpt-4o"
        return cls._model


# 默认配置目录
def _default_config_path() -> Path:
    custom = os.getenv("SONEX_CONFIG_PATH")
    if custom:
        return Path(custom).expanduser()
    return sonex_home() / "config.json"

# 加载配置文件
def _load_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

# 保存配置文件
def _save_config_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

# 加载环境文件
def _load_env_files() -> None:
    load_dotenv(override=False)

    project_root = Path(__file__).resolve().parents[2]
    dev_env = project_root / "dev.env"
    if dev_env.exists():
        load_dotenv(dotenv_path=dev_env, override=False)

