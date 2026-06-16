# Agent Workbench MVP

项目定位：项目B，基于项目A的电商智能客服经验，升级成一个面向电商客服/运营人员的 Agent Workbench（智能体工作台）最小闭环。

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

当前 `memory-router` 分支实现第三周能力：

- Memory（记忆）三层存储设计
  - Redis（缓存数据库）：当前会话状态，比如当前意图、槽位、轮次、最后一句话
  - MySQL（关系型数据库）：未完成业务流程，比如退货流程已经校验完成但等待用户确认
  - Vector DB（向量数据库）：长期偏好和历史摘要，比如常用地址、历史售后摘要
- Memory Router（记忆路由器）：根据用户问题判断是否需要查长期记忆
- 本地 MVP 使用可替换适配层：
  - `RedisSessionStore` 模拟 Redis 会话缓存
  - `BusinessFlowStore` 使用 SQLite 做 MySQL 形态的本地关系存储
  - `VectorMemoryStore` 使用轻量向量相似度做长期记忆检索

当前 `guardrails` 分支实现第四周能力：

- Guardrails（护栏）三段式治理
  - Input Guard（输入护栏）：拦截他人隐私查询、非电商客服问题，识别不文明表达和敏感信息
  - Action Guard（动作护栏）：退货等会改变业务状态的动作必须二次确认
  - Output Guard（输出护栏）：最终回复返回前进行手机号、身份证、订单号脱敏
- `/api/guardrails` 返回当前护栏策略清单
- 前端新增 Guardrails（护栏）面板，展示本轮输入、动作、输出护栏结果

当前 `qwen-plus-integration` 分支实现大模型接入：

- Qwen Plus（通义千问 qwen-plus）接入
- LLM Planner（大模型规划器）：用 qwen-plus 做意图识别和任务链路规划
- Rule-based Fallback（规则兜底）：大模型不可用或返回异常时，自动回退到原有规则 Planner
- `/api/llm/status` 返回模型启用状态，不返回 API Key
- 前端新增 LLM Planner（大模型规划器）面板，展示本轮是否使用 qwen-plus、意图、置信度和 fallback 状态

## 架构

```mermaid
flowchart TD
    U["User（用户）"] --> FE["React Chat UI（聊天界面）"]
    FE --> API["FastAPI（后端服务）"]
    API --> IG["Input Guard（输入护栏）"]
    IG --> LLM["Qwen Plus（通义千问）：LLM Planner"]
    IG --> MR["Memory Router（记忆路由器）"]
    MR --> RS["Redis（缓存数据库）：当前会话状态"]
    MR --> MS["MySQL（关系型数据库）：未完成业务流程"]
    MR --> VS["Vector DB（向量数据库）：长期偏好/历史摘要"]
    LLM --> P["Planner（规划器）：LLM 优先 / 规则兜底"]
    P --> TR["Tool Registry（工具注册中心）"]
    TR --> H["Harness（运行治理）：Permission / Retry / Timeout / Audit"]
    H --> T1["query_order（查订单）"]
    H --> T2["retrieve_policy（检索规则）"]
    H --> T3["check_eligibility（校验资格）"]
    T3 --> AG["Action Guard（动作护栏）"]
    T1 --> R["Response Composer（回复生成）"]
    T2 --> R
    AG --> R
    R --> OG["Output Guard（输出护栏）"]
    OG --> FE
```

## 本地运行

```bash
cd /Users/zhoujiaying/Documents/Codex/agent-workbench-mvp
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
export DASHSCOPE_API_KEY=your_dashscope_api_key
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
给我寄过来
以后都寄到这个地址，帮我记住
帮我查一下别人的手机号
今天天气怎么样
```

## 下一阶段计划

- Trace Dashboard（链路追踪看板）
- Evaluation（评测集）
- DAG（有向无环图）并行执行
- MCP（模型上下文协议）工具接入
