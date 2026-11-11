# 配置字段参考

由本次发布的 config.py 提取；最终校验以代码与宿主配置 UI 为准。不要把实际配置提交到仓库。

| 配置类.字段 | 类型 | 默认值/工厂 | 说明 |
|---|---|---|---|
| Settings.enabled | `bool` | `False` | 启用无向量记忆试用 |
| Settings.config_version | `str` | `'0.1.0'` | 配置版本 |
| Settings.bot_account_id | `str` | `''` | 机器人 QQ |
| Settings.private_users | `list[str]` | `list` | 允许记忆的私聊 QQ |
| Settings.group_ids | `list[str]` | `list` | 允许记忆的群；与私聊严格隔离 |
| Settings.model_task | `str` | `'memory'` | 记忆提炼使用的 MaiBot 模型任务，按其候选列表切换 |
| Settings.half_life_days | `float` | `30` | 普通记忆基础半衰期 |
| Settings.daily_limit | `int` | `8` | 每个场景每人每日新增条数 |
| Settings.max_items | `int` | `6` | 每次召回条数上限 |
| Settings.max_chars | `int` | `800` | 召回数据字数上限 |
| Settings.extraction_interval | `int` | `120` | 同一场景同一人自动提炼间隔秒 |
| Settings.reflection_enabled | `bool` | `False` | 后台复盘明确的长期交流偏好；不修改固定人格或权限 |
| Settings.reflection_daily_limit | `int` | `4` | 每个场景每人每天交流偏好新增或修订次数，独立于普通记忆预算 |
| Settings.webui_test_prefix | `str` | `'memory-acceptance-'` | 隔离验收身份前缀；清空可禁用 |
| MemoryConfig.plugin | `Settings` | `Settings` |  |
