from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from harness.config.schema import AgentHarnessConfig

CONFIG_FILE = "agent-harness.config.json"
ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _substitute_env_vars(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            env_value = os.getenv(name)
            if env_value is None:
                print(f"  ⚠ 环境变量 {name} 未设置，保留原值")
                return match.group(0)
            return env_value

        return ENV_VAR_RE.sub(replace, value)
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    if isinstance(value, dict):
        return {key: _substitute_env_vars(item) for key, item in value.items()}
    return value


def load_config(path: str | Path = CONFIG_FILE) -> AgentHarnessConfig:
    config_path = Path(path)
    load_dotenv(config_path.with_name(".env"))
    if not config_path.exists():
        print(f"  未找到 {config_path}，使用默认配置")
        print("  运行 uv run agent-harness init 生成配置文件\n")
        return AgentHarnessConfig()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"  ✗ 解析 {config_path} 失败: {error}") from error

    try:
        config = AgentHarnessConfig.model_validate(_substitute_env_vars(raw))
    except ValidationError as error:
        lines = ["  ✗ 配置文件校验失败:"]
        for issue in error.errors():
            lines.append(f"    {'.'.join(str(p) for p in issue['loc'])}: {issue['msg']}")
        raise SystemExit("\n".join(lines)) from error

    print(f"  ✓ 已加载 {config_path}")
    return config
