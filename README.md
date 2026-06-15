# Agent Workbench MVP

项目定位：基于项目A的电商智能客服经验，升级成一个面向电商客服/运营人员的 Agent Workbench（智能体工作台）最小闭环。

当前版本实现第一周 MVP：

- React Chat UI（聊天界面）
- FastAPI backend（后端服务）
- Planner（规划器）：把用户问题拆成任务链表
- Tool Registry（工具注册中心）：统一注册工具定义
- 三个原子工具：
  - `query_order`：查订单
  - `retrieve_policy`：检索规则
  - `check_eligibility`：校验售后资格
- Task Timeline（任务时间线）
- Tool Call Trace（工具调用链路）

当前 `agent-harness` 分支实现第二周能力：

- Agent Harness（智能体运行治理框架）雏形
- Tool Registry（工具注册中心）标准化工具定义
- 每个工具包含：
  - `name`（名称）
  - `description`（描述）
  - `input_schema`（输入结构）
  - `output_schema`（输出结构）
  - `permission`（权限）
  - `retry`（重试）
  - `timeout`（超时）
  - `audit_log`（审计日志）
- 统一工具执行入口：权限检查、超时控制、失败重试、审计事件生成

## 架构

```mermaid
flowchart TD
    U["User（用户）"] --> FE["React Chat UI（聊天界面）"]
    FE --> API["FastAPI（后端服务）"]
    API --> P["Planner（规划器）"]
    P --> TR["Tool Registry（工具注册中心）"]
    TR --> H["Harness（运行治理）：Permission / Retry / Timeout / Audit"]
    H --> T1["query_order（查订单）"]
    H --> T2["retrieve_policy（检索规则）"]
    H --> T3["check_eligibility（校验资格）"]
    T1 --> R["Response Composer（回复生成）"]
    T2 --> R
    T3 --> R
    R --> FE
```

## 本地运行

```bash
cd /Users/zhoujiaying/Documents/Codex/agent-workbench-mvp
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8020
```

打开：

```text
http://127.0.0.1:8020
```

## 可测试问题

```text
手机签收八天了还能退吗？
查一下订单 202606150001
我想退货，订单号 202606150002
```

## 下一阶段计划

- Memory Router（记忆路由器）
- Guardrail（护栏）：隐私、越权、危险动作确认
- Trace Dashboard（链路追踪看板）
- Evaluation（评测集）
- DAG（有向无环图）并行执行
- MCP（模型上下文协议）工具接入
