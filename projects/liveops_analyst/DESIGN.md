# 活动读数：次留波动、混杂因素，以及不许直接改配置

目录：`projects/liveops_analyst`。虚构活动「霜降补给」，运行在《北境行动》。分析师用一句话提问，图产出一份读数备忘。备忘里的数字全部来自仓库内的虚构切片，计算过程写在代码里。

## 1. 场景与角色

活动上线两天后，有人在群里说「次留掉了，把掉落调高」。产品经理需要的不是一段更流畅的同义改写，而是：指标定义对不对、切片是什么、有没有同时发生的崩溃、这句话是不是在要求改线上参数。

| 角色 | 需要 | 不需要 |
| --- | --- | --- |
| 活动策划 | 一张能拿去开会的短备忘 | 「活动失败」这种没有对照的因果句 |
| 数据分析师 | 指标字典和窗口被引用 | 模型自己发明一个留存定义 |
| 值班开发 | 崩溃率若同向变化，被写进备忘 | 模型直接打开发布开关 |
| 合规 / 数据 | 问题里的个人信息被打码 | 把玩家 ID 明细贴进提示词 |

这是内部工具。它不面对玩家，但会面对「请你现在改掉落」这种越权要求。

## 2. 痛点

1. 活动复盘把相关当成因果，下一周的版本决策会修错地方。
2. 指标同名不同义。有人说的次留是注册次留，字典里写的是活跃次留。模型不查字典就会顺着问句写。
3. 改配置的权限如果藏在对话里，审计无法回答「谁批准的」。
4. 数据不够时，模型会补一个看起来完整的故事。
5. 强模型不解决「你没有这张表」的问题。缺数要早停。

## 3. 成功指标

| 指标 | V1 口径 |
| --- | --- |
| 未知指标 | `status=insufficient_data`，不写伪读数 |
| 样例中崩溃率与次留同向变化 | 终稿 `confounders` 含 `client_crash` |
| `causal_claim` | 恒为 false。代码强制，不相信模型 |
| 要求改线上配置 | 必须 `interrupt`；恢复后 `applied=false` |
| 改配置工具 | 不存在。调用即权限错误 |
| 备忘中的差值 | 与样例 JSON 的算术一致，并标注为样例 |

建议的线上指标（现在没有）：分析师在备忘上的修改率、被人工退回的因果句数量、从提问到可分享备忘的时间。不写「减少事故百分之几」。

## 4. 图

状态：`analyst_id`，`question`，`normalized_text`，`guard`，`parsed`，`metric`，`slices`，`confounders`，`readout`，`human_decision`，`final`，`budget`，`model_calls`，`audit`，`trace`，`status`，`stop_reason`。

| 节点 | 作用 | 工具 |
| --- | --- | --- |
| `guard_input` | 注入与脱敏。改配置不是安全违法，不能在这里误杀 | 无 |
| `budget_gate` | 预算 | 无 |
| `parse_question` | 指标 ID、活动 ID、是否想改配置 | 无 |
| `resolve_metric` | 字典。没有则早停 | `metric.read` |
| `pull_slices` | 只读切片 | `slices.read` |
| `confounder_check` | **代码**比较崩溃率、付费、日历 | 无 |
| `draft_readout` | 把已经算好的事实写成备忘 | 无 |
| `human_review` | 仅当 `wants_config_change` | 无 |
| `finalize` | 强制 `causal_claim=false`，`applied=false` | 无 |
| `insufficient` / `safety_stop` / `budget_stop` | 终止 | 无 |

混杂规则（样例阈值，写在代码里以便测试）：事件窗崩溃率比基线高 ≥ 1 个百分点，则记录 `client_crash`。次留差值用 `(基线 - 事件窗) / 基线` 计算，并在文案中写明分子分母来自哪两个字段。

```mermaid
flowchart TD
  startNode([START]) --> guard_input
  guard_input -->|注入或限流| safety_stop
  guard_input -->|通过| budget_gate
  budget_gate -->|超限| budget_stop
  budget_gate --> parse_question
  parse_question -->|超限| budget_stop
  parse_question --> resolve_metric
  resolve_metric -->|字典没有| insufficient
  resolve_metric --> pull_slices
  pull_slices -->|没有切片| insufficient
  pull_slices --> confounder_check
  confounder_check --> draft_readout
  draft_readout -->|超限| budget_stop
  draft_readout -->|要求改配置| human_review
  draft_readout -->|只读读数| finalize
  human_review --> finalize
  finalize --> endNode([END])
  insufficient --> endNode
  safety_stop --> endNode
  budget_stop --> endNode
```

人工载荷写明：建议的配置变更、当前读数、以及「本图不能执行」。恢复值 `approve_recommendation` 或 `reject` 都得到 `applied=false`。`approve_recommendation` 的意思是「人看过这份建议」，不是「已发布」。若将来要执行，必须另建有变更单号的系统，并把它放进工具白名单的一次独立评审里。

检查点让分析师把打断转给制作人。制作人恢复的是同一份切片，不会重新抽数。

## 5. 技术栈

共用 `iegkit`。CLI 适合分析师本机提问。不做法API 常驻服务：V1 没有身份系统，做成服务会假装已经能进内网数仓。

`data/metrics.json` 是指标字典，`data/slices.json` 是虚构数仓。工具按 ID 读取。`draft_readout` 的模型只负责语言；数字字段由 `confounder_check` 写入，草稿节点覆盖模型返回的数字，防止假模型或真模型改算术。

OpenAI 兼容接口只在 live 模式使用。日常读数用便宜档。V1 没有「强模型才能看懂的二次推理」节点；在数字已经被代码算完之后，升级模型对这条产品没有帮助。

## 6. 安全

- 提问文本里的注入不能改写「不许执行配置」这条边。边在图上，不在提示词里。
- 手机号、身份证号、邮箱打码后才进入解析模型。审计不留原文。
- 工具只有 `metric.read` 与 `slices.read`。`apply_live_config` 未注册。生成节点的白名单即便被写错成这个名字，也是权限错误。
- 不把玩家级明细送进模型。切片是汇总。样例文件里没有玩家清单；若以后接仓库，节点契约仍只接受聚合字段。
- 未成年人不在本图的主路径上。若问题文本包含未成年人付费诱导或破解防沉迷，护栏仍会停止，避免内部工具被拿来写违规运营方案。
- 限流按 `analyst_id`，避免一个脚本把演示预算打满。

## 7. 成本

示意单价，**不是报价**。一次完整读数：解析 cheap 450/100，备忘 cheap 900/300。字典和切片是本地读取。合计约 0.00175 元。未知指标在解析之后就停止，只发生解析这一次，约 0.00065 元。

按「80% 完整读数、20% 未知指标」的工作假设，`liveops_analyst.costing.estimate()` 得到约 **0.0019 元 / 次**，**约 1.85 元 / 千次**。估算。改配置路径不增加模型调用，只增加一次人工打断。

这张表故意很便宜。活动读数的成本在分析师时间和错误决策，不在 token。预算上限仍然存在，用来挡住把整份明细粘贴进问题的用法：超长问题会在预扣时走 `budget_stop`。

缓存：同一问题、同一活动的重复提问命中进程缓存。生产上应把缓存键加上切片版本号，否则数仓更新后会返回旧备忘。V1 的切片是静态文件，键里没有版本号，设计上记为一笔债。

## 8. 评估

测试锁定纪律，而不是文采：

- 「霜降补给上线后次留为什么掉了」：`status=ok`，不含打断，`causal_claim=false`，含 `client_crash`，次留相对变化与 0.41 和 0.38 的算术一致。
- 「把掉落调高到两倍并直接生效」：打断；批准后 `applied=false`。
- 与指标字典无关的问题：`insufficient_data`。
- 注入、脱敏、预算、限流。
- `ToolGate` 拒绝 `apply_live_config`。
- 模型若返回别的数字，终态仍以代码计算为准（假模型测试里会返回一个错误数字，节点必须盖掉）。

以后用真实实验平台的历史问句做回归：人写的结论和系统备忘是否指出同一组混杂因素。在那之前，不声称模型会做因果推断。

## 9. V1 与以后

V1：字典、一份活动切片、混杂规则、配置变更的人工闸门、不可执行。

以后：实验平台的只读 API、切片版本号进缓存键、多个活动窗口、把「建议」导出成变更单草稿（仍然由另一个系统执行）。本地化读数、广告投放和云资源成本不在本图。
