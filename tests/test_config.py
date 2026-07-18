from __future__ import annotations

import json
import stat

from harness.config.init import DEFAULT_BASE_URL, run_init
from harness.config.loader import load_config
from harness.config.schema import AgentHarnessConfig


def test_config_defaults() -> None:
    config = AgentHarnessConfig()
    assert config.model.provider == "dashscope"
    assert config.agents.max_spawn_depth == 1
    assert config.channels.feishu.enabled is False


def test_load_config_aliases_and_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEST_AGENT_KEY", "secret-value")
    path = tmp_path / "agent-harness.config.json"
    path.write_text(
        json.dumps(
            {
                "model": {"baseURL": "https://example.test/v1", "apiKey": "${TEST_AGENT_KEY}"},
                "agents": {"maxSpawnDepth": 2, "maxConcurrent": 4, "defaultTimeout": 1234},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.model.base_url == "https://example.test/v1"
    assert config.model.api_key == "secret-value"
    assert config.agents.max_spawn_depth == 2
    assert config.agents.max_concurrent == 4


def test_init_keeps_secrets_out_of_config_and_preserves_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / ".env").write_text("EXISTING_KEY='keep-me'\n", encoding="utf-8")
    answers = iter(["1", "entered-secret", "n", "4"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    run_init()

    config_text = (tmp_path / "agent-harness.config.json").read_text(encoding="utf-8")
    config = json.loads(config_text)
    assert config["model"]["apiKey"] == "${OPENAI_API_KEY}"
    assert config["model"]["baseURL"] == DEFAULT_BASE_URL
    assert "entered-secret" not in config_text
    AgentHarnessConfig.model_validate(config)

    env_path = tmp_path / ".env"
    env_text = env_path.read_text(encoding="utf-8")
    assert "EXISTING_KEY='keep-me'" in env_text
    assert "OPENAI_API_KEY='entered-secret'" in env_text
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_mcp_server_config_uses_external_aliases() -> None:
    config = AgentHarnessConfig.model_validate(
        {
            "mcpServers": [
                {
                    "name": "github",
                    "command": "github-mcp-server",
                    "args": ["stdio"],
                    "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                }
            ]
        }
    )

    assert config.mcp_servers[0].command == "github-mcp-server"
    assert config.mcp_servers[0].args == ["stdio"]
