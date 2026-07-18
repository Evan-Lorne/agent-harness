from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv, set_key

from harness.config.loader import CONFIG_FILE

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _ask(question: str) -> str:
    print(question)
    return input("  > ")


def run_init() -> None:
    load_dotenv(Path(".env"))
    print("\n  Agent Harness 初始化向导\n")
    path = Path(CONFIG_FILE)
    if path.exists() and _ask(f"  {CONFIG_FILE} 已存在，覆盖? (y/N): ").lower() != "y":
        print("  已取消\n")
        return
    print(
        "  选择模型:\n\n    1. gpt-5.6-terra   (推荐，均衡)\n    2. gpt-5.6-luna    (快速，便宜)\n    3. gpt-5.6-sol     (最强，贵)\n"
    )
    model = {"1": "gpt-5.6-terra", "2": "gpt-5.6-luna", "3": "gpt-5.6-sol"}.get(
        _ask("  模型 [1]: ") or "1", "gpt-5.6-terra"
    )
    api_key = _ask("\n API Key (留空则从环境变量 OPENAI_API_KEY 读取): ")
    enable_feishu = _ask("\n  启用飞书 Channel? (y/N): ").lower() == "y"
    app_id = _ask("  飞书 App ID: ") if enable_feishu else ""
    app_secret = _ask("  飞书 App Secret: ") if enable_feishu else ""
    try:
        maximum = int(_ask("\n  子 Agent 最大并发数 [3]: ") or "3")
    except ValueError:
        maximum = 3
    config = {
        "version": "1.0",
        "model": {
            "provider": "dashscope",
            "name": model,
            "baseURL": "${OPENAI_BASE_URL}" if os.getenv("OPENAI_BASE_URL") else DEFAULT_BASE_URL,
            "apiKey": "${OPENAI_API_KEY}",
        },
        "plugins": [{"name": "supabase", "enabled": False, "config": {}}],
        "channels": {
            "feishu": {
                "enabled": enable_feishu,
                "appId": "${FEISHU_APP_ID}" if enable_feishu else "",
                "appSecret": "${FEISHU_APP_SECRET}" if enable_feishu else "",
                "port": 3000,
            }
        },
        "agents": {"maxSpawnDepth": 1, "maxConcurrent": maximum, "defaultTimeout": 60000},
        "security": {"defaultRole": "owner", "auditLog": True, "bashTimestamp": True},
        "memory": {"dataDir": "."},
        "rag": {
            "enabled": True,
            "docsDir": "docs",
            "apiKey": "${ALIYUN_API_KEY}",
            "store": "memory",
            "databasePath": "knowledge.db",
        },
        "mcpServers": [],
        "cron": {"enabled": True, "dataDir": "."},
        "session": {"id": "default"},
        "usage": {"trackingFile": ".usage/today.jsonl"},
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n  ✓ {CONFIG_FILE} 已生成")
    env_values: dict[str, str] = {}
    if api_key:
        env_values["OPENAI_API_KEY"] = api_key
    if enable_feishu and app_id:
        env_values.update({"FEISHU_APP_ID": app_id, "FEISHU_APP_SECRET": app_secret})
    env_path = Path(".env")
    if env_values:
        env_path.touch(exist_ok=True)
        for name, value in env_values.items():
            set_key(str(env_path), name, value, quote_mode="always")
        print("  ✓ .env 已生成")
    if env_path.exists():
        env_path.chmod(0o600)
    print("\n  启动 Agent: uv run agent-harness\n")
