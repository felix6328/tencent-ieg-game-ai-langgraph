# 社区哨兵

《北境行动》的一个文本入口，分成客服、举报和舆情。高置信活动问答可以自动回复。支付、未成年人和任何处罚建议都要人工。没有封禁工具。

设计说明见 [DESIGN.md](DESIGN.md)。

```bash
python -m community_sentinel.cli demo
```

HTTP：`community_sentinel.api:create_app` 的 `POST /v1/tickets`。
