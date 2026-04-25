import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

@dataclass
class RuntimeConfig:
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config_path: Optional[str] = None

# 默认配置目录
def _default_config_path() -> Path:
    custom = os.getenv("SONEX_CONFIG_PATH")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex" / "config.json"

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

def apply_cli_overrides(
    conf: RuntimeConfig,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> RuntimeConfig:
    next_conf = replace(
        conf,
        model=model or conf.model,
        api_key=api_key or conf.api_key,
        base_url=base_url or conf.base_url,
    )
    return next_conf
