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
  const scrollRef = useRef(null);

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
          React.createElement("h1", null, "Agent Workbench MVP"),
          React.createElement("p", null, "项目A升级版：Planner（规划器）+ Tools（工具）+ Trace（链路追踪）")
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

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));

