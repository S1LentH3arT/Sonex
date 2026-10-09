import {
  memo,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { startRuntime, send as sendCommand } from "./bridge";
import { Icon, type IconName } from "./Icon";
import { Confirmation, FeaturePanel, Setup, type Send } from "./Panels";
import { Player } from "./Player";
import { initialState, reduce } from "./state";
import type { ChatTranscriptMessage } from "./protocol";

const emptyMessages: ChatTranscriptMessage[] = [];
const Conversation = memo(function Conversation({
  messages,
}: {
  messages: ChatTranscriptMessage[];
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useEffect(() => {
    if (follow.current) bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);
  return (
    <div
      className="messages"
      onScroll={(e) => {
        const el = e.currentTarget;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      }}
    >
      {messages.map((message, index) => (
        <article
          className={`message ${message.role} ${message.tone || ""}`}
          key={index}
        >
          <span className="message-label">
            {message.role === "user" ? "你" : "SONEX"}
          </span>
          <div className="message-content">
            {message.document?.blocks ? (
              message.document.blocks.map((block, i) => {
                if (block.type === "spacer")
                  return <div className="spacer" key={i} />;
                if (block.type === "code_block")
                  return (
                    <pre key={i}>
                      <code>{block.text}</code>
                    </pre>
                  );
                const spans = block.spans.map((span, j) =>
                  span.style === "strong" ? (
                    <strong key={j}>{span.text}</strong>
                  ) : (
                    <span key={j}>{span.text}</span>
                  ),
                );
                return block.type === "heading" ? (
                  <h3 key={i}>{spans}</h3>
                ) : (
                  <p key={i}>
                    {block.type === "list_item" ? `${block.marker} ` : ""}
                    {spans}
                  </p>
                );
              })
            ) : (
              <p>{message.content}</p>
            )}
          </div>
        </article>
      ))}
      <div ref={bottom} />
    </div>
  );
});

export function App() {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [settings, setSettings] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const send: Send = useCallback((message) => {
    void sendCommand(message).catch((error) =>
      dispatch({ type: "error", message: String(error) }),
    );
  }, []);
  const connect = useCallback(() => {
    dispatch({ type: "runtime_status", status: "starting" });
    void startRuntime(dispatch).catch((error) =>
      dispatch({
        type: "runtime_status",
        status: "stopped",
        message: String(error),
      }),
    );
  }, []);
  useEffect(connect, [connect]);
  const onError = useCallback(
    (message: string) => dispatch({ type: "error", message }),
    [],
  );
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const ready = state.status === "ready";
  const busy = !!state.working;
  const title =
    state.sessions.find((session) => session.id === state.viewedId)?.title ||
    "新会话";
  const messages = state.messages[state.viewedId] ?? emptyMessages;
  const command = (text: string) => {
    setSettings(false);
    send({ type: "desktop", action: "command", command: text });
  };
  const submit = () => {
    if (!input.trim() || !ready || busy || state.confirm || state.setup) return;
    send({
      type: "desktop",
      action: "chat",
      session_id: state.viewedId,
      text: input.trim(),
    });
    setInput("");
  };
  const navigation: [IconName, string, string][] = [
    ["music", "音乐库", "/playlist"],
    ["memory", "音乐记忆", "/memory"],
    ["grid", "扩展", "/extension"],
  ];
  return (
    <div
      className={`app ${collapsed ? "nav-collapsed" : ""} ${showPlayer ? "show-player" : ""}`}
    >
      <aside className="navigation" aria-label="主导航">
        <div className="brand">
          <span className="brand-mark">s.</span>
          <span className="brand-name">
            sonex<span>DESKTOP</span>
          </span>
          <button
            className="icon-button collapse"
            aria-label="折叠侧边栏"
            onClick={() => setCollapsed(!collapsed)}
          >
            <Icon name="collapse" size={16} />
          </button>
        </div>
        <button
          className="new-chat"
          disabled={!ready || busy || !!state.confirm || !!state.setup}
          onClick={() => {
            setSettings(false);
            send({ type: "desktop", action: "new_session" });
          }}
        >
          <Icon name="plus" />
          <span>新会话</span>
          <kbd>＋</kbd>
        </button>
        <label className="search-box">
          <Icon name="search" size={15} />
          <input
            aria-label="搜索会话"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索会话"
          />
        </label>
        <div className="nav-caption">你的空间</div>
        <nav>
          {navigation.map(([icon, label, action]) => (
            <button
              disabled={!ready || busy}
              key={action}
              onClick={() => command(action)}
              title={label}
            >
              <Icon name={icon} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="nav-caption history-caption">
          最近会话 <span>{state.sessions.length}</span>
        </div>
        <div className="session-list">
          {state.sessions
            .filter((session) =>
              session.title
                .toLocaleLowerCase()
                .includes(query.toLocaleLowerCase()),
            )
            .map((session) => (
              <button
                key={session.id}
                className={
                  state.viewedId === session.id && !settings ? "selected" : ""
                }
                title={session.title}
                onClick={() => {
                  setSettings(false);
                  dispatch({ type: "view", id: session.id });
                  send({
                    type: "desktop",
                    action: "read_session",
                    session_id: session.id,
                  });
                }}
              >
                <Icon name="chat" size={15} />
                <span>{session.title}</span>
                {state.working?.sessionId === session.id && (
                  <i className="live-dot" />
                )}
              </button>
            ))}
          {!state.sessions.length && (
            <p className="nav-empty">你的音乐故事，从这里开始。</p>
          )}
        </div>
        <footer className="account">
          <button
            className={settings ? "selected" : ""}
            onClick={() => {
              setSettings(!settings);
              dispatch({ type: "dismiss_panel" });
            }}
            title="设置"
          >
            <span className="avatar">
              {state.user.slice(0, 1).toUpperCase()}
            </span>
            <span className="account-name">
              {state.user}
              <small>
                <i className={ready ? "live-dot" : ""} />
                {ready
                  ? "本地运行"
                  : state.status === "starting"
                    ? "正在启动"
                    : "已断开"}
              </small>
            </span>
            <Icon name="settings" size={17} />
          </button>
        </footer>
      </aside>
      <main className="workspace">
        <header className="workspace-heading">
          <div>
            <span className="eyebrow">YOUR PERSONAL MUSIC AGENT</span>
            <h1>
              {settings
                ? "设置"
                : state.panel
                  ? "title" in state.panel
                    ? state.panel.title
                    : "代理设置"
                  : title}
            </h1>
          </div>
          <div className="header-actions">
            <button
              className="model-badge"
              disabled={!ready || busy}
              onClick={() => command("/model")}
            >
              <i className={state.auth?.ready ? "live-dot" : ""} />
              {state.auth?.model_label || state.auth?.model || "连接模型"}
            </button>
            <button
              className="icon-button mobile-player-toggle"
              aria-label="切换播放器"
              onClick={() => setShowPlayer(!showPlayer)}
            >
              <Icon name="music" />
            </button>
          </div>
        </header>
        {state.error && (
          <div className="error-banner" role="alert">
            <span>{state.error}</span>
            <button
              className="icon-button"
              aria-label="关闭错误提示"
              onClick={() => dispatch({ type: "dismiss_error" })}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        )}
        {settings ? (
          <div className="settings-view">
            <div className="eyebrow">MAKE IT YOURS</div>
            <h2>你的音乐，你的空间。</h2>
            <p className="muted">
              会话、记忆与播放状态保存在本机。模型和在线音乐服务使用你自己的连接。
            </p>
            <div className="settings-grid">
              <button
                disabled={!ready || busy}
                onClick={() => command("/login")}
              >
                <Icon name="link" />
                <strong>模型连接</strong>
                <small>{state.auth?.provider || "配置你的模型服务"}</small>
              </button>
              <button
                disabled={!ready || busy}
                onClick={() => command("/connect")}
              >
                <Icon name="music" />
                <strong>音乐服务</strong>
                <small>连接可用的音乐来源</small>
              </button>
              <button
                disabled={!ready || busy}
                onClick={() => command("/proxy")}
              >
                <Icon name="settings" />
                <strong>网络代理</strong>
                <small>配置本机网络连接</small>
              </button>
            </div>
            <div className="data-location">
              <span>本地数据目录</span>
              <code>{state.home || "用户目录 / .sonex"}</code>
            </div>
            {state.status === "stopped" && (
              <button className="primary" onClick={connect}>
                重新启动 Runtime
              </button>
            )}
          </div>
        ) : state.panel ? (
          <FeaturePanel
            key={state.panel.type}
            panel={state.panel}
            send={send}
            close={() => dispatch({ type: "dismiss_panel" })}
          />
        ) : messages.length ? (
          <Conversation messages={messages} />
        ) : (
          <div className="welcome">
            <div className="welcome-symbol">
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
            <div className="eyebrow">
              A LITTLE LESS NOISE. A LITTLE MORE MUSIC.
            </div>
            <h2>
              把此刻，
              <br />
              <em>交给音乐。</em>
            </h2>
            <p>
              聊聊你的心情，或者说出想听的那首歌。
              <br />
              Sonex 会陪你找到合适的声音。
            </p>
            <div className="suggestions">
              {[
                "找一些适合专注的音乐",
                "根据我的喜好推荐几首歌",
                "帮我整理一个周末歌单",
              ].map((text) => (
                <button
                  key={text}
                  onClick={() => {
                    setInput(text);
                    inputRef.current?.focus();
                  }}
                >
                  <Icon name="music" size={15} />
                  {text}
                  <Icon name="arrow" size={14} />
                </button>
              ))}
            </div>
          </div>
        )}
        {(state.setup || state.confirm) && (
          <div className="interaction-scroll">
            {state.setup && (
              <Setup
                key={`${state.setup.type}-${state.setup.step}`}
                setup={state.setup}
                send={send}
              />
            )}
            {state.confirm && (
              <Confirmation
                key={state.confirm.id}
                confirm={state.confirm}
                send={send}
                dismiss={() => dispatch({ type: "dismiss_confirm" })}
              />
            )}
          </div>
        )}
        <div className="composer-area">
          {busy && (
            <div className="working" role="status">
              <i className="live-dot" />
              <span>{state.activity || "Sonex 正在处理…"}</span>
              <button
                onClick={() =>
                  send({
                    type: "agent_turn_interrupt",
                    turn_id: state.working!.turnId,
                  })
                }
              >
                <Icon name="stop" size={12} />
                停止
              </button>
            </div>
          )}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <textarea
              ref={inputRef}
              aria-label="发送给 Sonex 的消息"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="今天，想听点什么？"
              disabled={!ready || busy || !!state.setup || !!state.confirm}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <div className="composer-bottom">
              <span>
                <i className={ready ? "live-dot" : ""} />
                {ready
                  ? "Agent · 本地执行"
                  : state.status === "starting"
                    ? "Runtime 启动中…"
                    : "Runtime 未连接"}
              </span>
              <button
                className="send-button"
                type="submit"
                disabled={
                  !ready ||
                  busy ||
                  !input.trim() ||
                  !!state.setup ||
                  !!state.confirm
                }
                aria-label="发送消息"
              >
                <Icon name="arrow" />
              </button>
            </div>
          </form>
          <div className="composer-hint">
            <span>Enter 发送 · Shift + Enter 换行</span>
            <span>音乐会继续，随时聊。</span>
          </div>
        </div>
      </main>
      <Player
        player={state.player}
        queue={state.queue}
        revision={state.revision}
        spotify={state.spotify}
        cover={state.cover}
        ready={ready}
        send={send}
        onError={onError}
      />
    </div>
  );
}
