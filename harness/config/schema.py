from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConfigModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ModelConfig(ConfigModel):
    provider: Literal["dashscope", "openai", "custom"] = "dashscope"
    name: str = "gpt-5.5"
    base_url: str = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        alias="baseURL",
    )
    api_key: str = Field("", alias="apiKey")


class PluginConfig(ConfigModel):
    name: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class FeishuChannelConfig(ConfigModel):
    enabled: bool = False
    app_id: str = Field("", alias="appId")
    app_secret: str = Field("", alias="appSecret")
    port: int = 3000


class ChannelConfig(ConfigModel):
    feishu: FeishuChannelConfig = Field(default_factory=lambda: FeishuChannelConfig.model_validate({}))


class AgentConfig(ConfigModel):
    max_spawn_depth: int = Field(1, ge=0, le=5, alias="maxSpawnDepth")
    max_concurrent: int = Field(3, ge=1, le=10, alias="maxConcurrent")
    default_timeout: int = Field(60000, alias="defaultTimeout")


class SecurityConfig(ConfigModel):
    default_role: Literal["owner", "collaborator", "guest"] = Field("owner", alias="defaultRole")
    audit_log: bool = Field(True, alias="auditLog")
    bash_timestamp: bool = Field(True, alias="bashTimestamp")


class MemoryConfig(ConfigModel):
    data_dir: str = Field(".", alias="dataDir")


class RagConfig(ConfigModel):
    enabled: bool = True
    docs_dir: str = Field("docs", alias="docsDir")
    api_key: str = Field("", alias="apiKey")
    store: Literal["memory", "sqlite"] = "memory"
    database_path: str = Field("knowledge.db", alias="databasePath")


class MCPServerConfig(ConfigModel):
    name: str
    enabled: bool = True
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class CronConfig(ConfigModel):
    enabled: bool = True
    data_dir: str = Field(".", alias="dataDir")


class SessionConfig(ConfigModel):
    id: str = Field("default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UsageConfig(ConfigModel):
    tracking_file: str = Field(".usage/today.jsonl", alias="trackingFile")


class AgentHarnessConfig(ConfigModel):
    version: str = "1.0"
    model: ModelConfig = Field(default_factory=lambda: ModelConfig.model_validate({}))
    plugins: list[PluginConfig] = Field(default_factory=list)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)
    agents: AgentConfig = Field(default_factory=lambda: AgentConfig.model_validate({}))
    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig.model_validate({}))
    memory: MemoryConfig = Field(default_factory=lambda: MemoryConfig.model_validate({}))
    rag: RagConfig = Field(default_factory=lambda: RagConfig.model_validate({}))
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list, alias="mcpServers")
    cron: CronConfig = Field(default_factory=lambda: CronConfig.model_validate({}))
    session: SessionConfig = Field(default_factory=lambda: SessionConfig.model_validate({}))
    usage: UsageConfig = Field(default_factory=lambda: UsageConfig.model_validate({}))
