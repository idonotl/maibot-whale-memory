from maibot_sdk import Field, PluginConfigBase


class Settings(PluginConfigBase):
    enabled: bool = Field(default=False, description="启用无向量记忆试用")
    config_version: str = Field(default="0.1.0", description="配置版本")
    bot_account_id: str = Field(default="", description="机器人 QQ")
    private_users: list[str] = Field(default_factory=list, description="允许记忆的私聊 QQ")
    group_ids: list[str] = Field(default_factory=list, description="允许记忆的群；与私聊严格隔离")
    model_name: str = Field(default="deepseek-flash-affect", description="记忆提炼使用已有非思考模型别名")
    half_life_days: float = Field(default=30, ge=1, le=365, description="普通记忆基础半衰期")
    daily_limit: int = Field(default=8, ge=1, le=30, description="每个场景每人每日新增条数")
    max_items: int = Field(default=6, ge=1, le=10, description="每次召回条数上限")
    max_chars: int = Field(default=800, ge=200, le=2000, description="召回数据字数上限")
    extraction_interval: int = Field(default=120, ge=30, le=600, description="同一场景同一人自动提炼间隔秒")
    reflection_enabled: bool = Field(default=True, description="后台复盘明确的长期交流偏好；不修改固定人格或权限")
    reflection_daily_limit: int = Field(default=4, ge=1, le=12, description="每个场景每人每天交流偏好新增或修订次数，独立于普通记忆预算")
    webui_test_prefix: str = Field(default="memory-acceptance-", description="隔离验收身份前缀；清空可禁用")


class MemoryConfig(PluginConfigBase):
    plugin: Settings = Field(default_factory=Settings)
