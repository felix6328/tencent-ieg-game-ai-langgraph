# 北境复盘

用一局虚构遥测写赛后建议。外挂、脚本和破解防沉迷会在调用模型前被拒绝。遥测不全时停给人类教练。未成年人账号会附上时段提醒。

设计说明见 [DESIGN.md](DESIGN.md)。样例对局在 `data/telemetry.json`。

```bash
python -m squad_coach.cli demo
```

这不是局内可操纵的 AI 队友。没有客户端，就不模拟移动和射击。
