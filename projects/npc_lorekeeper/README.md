# 墨影同行

虚构《墨影江湖》的 NPC 沈照夜。图先做安全和脱敏，再检索记忆与人物小传，生成、审查、必要时重写，通过后才写记忆。改写正史会停下来等人。

设计说明见 [DESIGN.md](DESIGN.md)。

```bash
python -m npc_lorekeeper.cli demo
python -m npc_lorekeeper.cli chat --text "介绍你自己"
```

默认 mock，不需要密钥。`npc_lorekeeper.api:create_app` 提供 `POST /v1/turns`，同一 `thread_id` 可以用 `resume` 恢复人工审阅。
