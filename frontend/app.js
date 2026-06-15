const { useMemo, useRef, useState, useEffect } = React;

const examples = [
  "手机签收八天了还能退吗？",
  "查一下订单 202606150001",
  "我想退货，订单号 202606150002",
];

function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "你好，我是电商 Agent Workbench。你可以问我订单、售后规则和退货资格。",
    },
  ]);
  const [input, setInput] = useState("手机签收八天了还能退吗？");
  const [loading, setLoading] = useState(false);
  const [lastResponse, setLastResponse] = useState(null);
  const [toolDefinitions, setToolDefinitions] = useState([]);
  const scrollRef = useRef(null);

  useEffect(() => {
    fetch("/api/tools")
      .then((response) => response.json())
      .then(setToolDefinitions)
      .catch(() => setToolDefinitions([]));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function send(text = input) {
    const value = text.trim();
    if (!value || loading) return;
    setLoading(true);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: value }]);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: value,
          user_id: "1001",
          session_id: "demo-session",
        }),
      });
      const data = await response.json();
      setLastResponse(data);
      setMessages((prev) => [...prev, { role: "assistant", content: data.answer }]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `请求失败：${error.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const traceJson = useMemo(() => {
    if (!lastResponse) return "暂无链路数据";
    return JSON.stringify(lastResponse.tool_results, null, 2);
  }, [lastResponse]);

  return (
    React.createElement("div", { className: "app" },
      React.createElement("section", { className: "main" },
        React.createElement("header", { className: "header" },
          React.createElement("h1", null, "Agent Harness Workbench"),
          React.createElement("p", null, "项目A升级版：Planner（规划器）+ Tool Registry（工具注册中心）+ Audit Trace（审计链路）")
        ),
        React.createElement("main", { className: "messages", ref: scrollRef },
          messages.map((message, index) =>
            React.createElement("div", {
              key: index,
              className: `message ${message.role}`,
            }, message.content)
          )
        ),
        React.createElement("footer", { className: "composer" },
          React.createElement("input", {
            value: input,
            placeholder: "输入：手机签收八天了还能退吗？",
            onChange: (event) => setInput(event.target.value),
            onKeyDown: (event) => {
              if (event.key === "Enter") send();
            },
          }),
          React.createElement("button", { disabled: loading, onClick: () => send() },
            loading ? "执行中" : "发送"
          )
        )
      ),
      React.createElement("aside", { className: "side" },
        React.createElement("div", { className: "panel" },
          React.createElement("h2", null, "快捷测试"),
          React.createElement("div", { className: "quick" },
            examples.map((item) =>
              React.createElement("button", {
                key: item,
                onClick: () => send(item),
                disabled: loading,
              }, item)
            )
          )
        ),
        React.createElement("div", { className: "panel" },
          React.createElement("h2", null, "Tool Registry（工具注册中心）"),
          toolDefinitions.length
            ? toolDefinitions.map((tool) =>
                React.createElement(ToolCard, { key: tool.name, tool })
              )
            : React.createElement("div", { className: "step" }, "工具定义加载中。")
        ),
        React.createElement("div", { className: "panel" },
          React.createElement("h2", null, "Memory（记忆）"),
          lastResponse?.memory
            ? React.createElement(MemoryPanel, { memory: lastResponse.memory })
            : React.createElement("div", { className: "step" }, "发送消息后展示记忆路由。")
        ),
        React.createElement("div", { className: "panel" },
          React.createElement("h2", null, "Task Timeline（任务时间线）"),
          lastResponse?.plan?.length
            ? lastResponse.plan.map((step) =>
                React.createElement("div", { className: "step", key: step.id },
                  React.createElement("div", { className: "step-title" },
                    React.createElement("span", null, step.title),
                    React.createElement("span", { className: `badge ${step.status}` }, step.status)
                  ),
                  React.createElement("div", { className: "step-reason" }, step.reason)
                )
              )
            : React.createElement("div", { className: "step" }, "暂无任务，发送一条消息后展示。")
        ),
        React.createElement("div", { className: "panel" },
          React.createElement("h2", null, "Tool Results（工具结果）"),
          React.createElement("pre", null, traceJson)
        )
      )
    )
  );
}

function MemoryPanel({ memory }) {
  const decision = memory.router_decision || {};
  const session = memory.session_state || {};
  const activeFlow = memory.active_flow;
  const longTerm = memory.long_term_memories || [];

  return React.createElement("div", { className: "memory-box" },
    React.createElement("div", { className: "memory-section" },
      React.createElement("div", { className: "memory-title" }, "Memory Router（记忆路由器）"),
      React.createElement("div", { className: "memory-row" },
        React.createElement("span", null, "是否查长期记忆"),
        React.createElement("strong", null, decision.should_query_long_term ? "是" : "否")
      ),
      React.createElement("p", null, decision.reason || "-"),
      React.createElement("div", { className: "chips" },
        (decision.signals || []).map((signal) =>
          React.createElement("code", { key: signal }, signal)
        )
      )
    ),
    React.createElement("div", { className: "memory-section" },
      React.createElement("div", { className: "memory-title" }, "Redis（缓存数据库）：当前会话状态"),
      React.createElement("div", { className: "memory-row" },
        React.createElement("span", null, "active_intent（当前意图）"),
        React.createElement("strong", null, session.active_intent || "-")
      ),
      React.createElement("div", { className: "memory-row" },
        React.createElement("span", null, "turn_count（轮次）"),
        React.createElement("strong", null, String(session.turn_count ?? 0))
      ),
      React.createElement("pre", { className: "mini-pre" }, JSON.stringify(session.slots || {}, null, 2))
    ),
    React.createElement("div", { className: "memory-section" },
      React.createElement("div", { className: "memory-title" }, "MySQL（关系型数据库）：未完成业务流程"),
      activeFlow
        ? React.createElement("pre", { className: "mini-pre" }, JSON.stringify(activeFlow, null, 2))
        : React.createElement("p", null, "暂无未完成流程。")
    ),
    React.createElement("div", { className: "memory-section" },
      React.createElement("div", { className: "memory-title" }, "Vector DB（向量数据库）：长期偏好和历史摘要"),
      longTerm.length
        ? longTerm.map((item) =>
            React.createElement("div", { className: "memory-hit", key: item.id },
              React.createElement("div", { className: "memory-row" },
                React.createElement("span", null, item.kind),
                React.createElement("strong", null, `score ${item.score}`)
              ),
              React.createElement("p", null, item.text)
            )
          )
        : React.createElement("p", null, "本轮未查询长期记忆。")
    )
  );
}

function schemaFields(schema) {
  return Object.keys(schema?.properties || {});
}

function ToolCard({ tool }) {
  return React.createElement("div", { className: "tool-card" },
    React.createElement("div", { className: "tool-card-head" },
      React.createElement("span", null, tool.name),
      React.createElement("span", { className: "scope" }, tool.permission?.scope || "unknown")
    ),
    React.createElement("p", null, tool.description),
    React.createElement("div", { className: "tool-meta" },
      React.createElement("span", null, `permission（权限）：${tool.permission?.allowed_roles?.join(", ") || "-"}`),
      React.createElement("span", null, `retry（重试）：${tool.retry?.max_attempts || 1} 次`),
      React.createElement("span", null, `timeout（超时）：${tool.timeout?.timeout_ms || 0} ms`),
      React.createElement("span", null, `audit_log（审计日志）：${tool.audit_log?.event_name || "-"}`)
    ),
    React.createElement("div", { className: "schema-row" },
      React.createElement("span", null, "input_schema（输入结构）"),
      schemaFields(tool.input_schema).map((field) =>
        React.createElement("code", { key: `input-${field}` }, field)
      )
    ),
    React.createElement("div", { className: "schema-row" },
      React.createElement("span", null, "output_schema（输出结构）"),
      schemaFields(tool.output_schema).map((field) =>
        React.createElement("code", { key: `output-${field}` }, field)
      )
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
