import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { Orb, type OrbState } from "@yogesharc/thinking-orbs";
import { startRuntime, send as sendCommand } from "./bridge";
import { ActivityLog } from "./ActivityLog";
import { Icon, type IconName } from "./Icon";
import { Confirmation, FeaturePanel, Setup, type Send } from "./Panels";
import { Player } from "./Player";
import { initialState, reduce } from "./state";
import type { ConversationMessage } from "./protocol";

const emptyMessages: ConversationMessage[] = [];
const Conversation = memo(function Conversation({
  messages,
  sessionId,
  scrollPositions,
}: {
  messages: ConversationMessage[];
  sessionId: string;
  scrollPositions: { current: Record<string, number> };
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useLayoutEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const saved = scrollPositions.current[sessionId];
    el.scrollTop = saved ?? el.scrollHeight;
    follow.current = saved === undefined || el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }, [sessionId, scrollPositions]);
  useEffect(() => {
    if (follow.current) bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);
  return (
    <div
      ref={viewport}
      className="messages"
      onScroll={(e) => {
        const el = e.currentTarget;
        scrollPositions.current[sessionId] = el.scrollTop;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      }}
    >
      {messages.map((message, index) => (
        <article
          className={`message ${message.role} ${message.tone || ""}`}
          key={index}
        >
          <span className="message-label">
            {message.role === "user" ? "You" : "SONEX"}
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
          {message.activities?.length ? (
            <ActivityLog activities={message.activities} />
          ) : null}
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
  const scrollPositions = useRef<Record<string, number>>({});
  const send: Send = useCallback((message) => {
    void sendCommand(message).catch((error) =>
      dispatch({ type: "error", message: String(error) }),
    );
  }, []);
  const connect = useCallback(() => {
    startRuntime(dispatch);
  }, []);
  useEffect(connect, [connect]);
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
  const currentActivity =
    state.activity?.session_id === state.viewedId ? state.activity : null;
  const waiting = !!state.confirm && busy;
  const statusError =
    !!state.error || (currentActivity?.kind === "error" && currentActivity.status === "error");
  const activeStatus = busy || statusError;
  const orbState: OrbState = waiting
    ? "waiting"
    : currentActivity?.kind === "tool" && currentActivity.status === "pending"
      ? /search|find|recommend/i.test(currentActivity.title)
        ? "searching"
        : "working"
      : "reasoning";
  const statusLabel = statusError
    ? "Agent needs attention"
    : waiting
      ? "Waiting for your approval"
      : currentActivity?.kind === "tool" && currentActivity.status === "pending"
        ? currentActivity.title
        : "Thinking";
  const viewedTitle = state.sessions.find(
    (session) => session.id === state.viewedId,
  )?.title;
  const title =
    !viewedTitle || viewedTitle === "New session" ? "New chat" : viewedTitle;
  const messages = state.messages[state.viewedId] ?? emptyMessages;
  const isEmpty = !settings && !state.panel && messages.length === 0;
  const command = (text: string) => {
    setSettings(false);
    send({ type: "web", action: "command", command: text });
  };
  const submit = () => {
    if (!input.trim() || !ready || busy || state.confirm || state.setup) return;
    send({
      type: "web",
      action: "chat",
      session_id: state.viewedId,
      text: input.trim(),
    });
    setInput("");
  };
  const navigation: [
    IconName,
    string,
    string,
    "track_panel" | "memory_panel" | "extension_panel" | "web_library",
  ][] = [
    ["library", "Library", "/library", "web_library"],
    ["memory", "Memory", "/memory", "memory_panel"],
    ["grid", "Extension", "/extension", "extension_panel"],
  ];
  const composer = (
    <div className="composer-area">
      {(activeStatus || waiting) && (
        <div className={`agent-status ${statusError ? "is-error" : waiting ? "is-waiting" : ""}`} role="status">
          {statusError ? (
            <Icon name="error" size={16} />
          ) : (
            <Orb state={orbState} size={18} speed={0.8} label={statusLabel} />
          )}
          <span>{statusLabel}</span>
          {busy && (
            <button
              onClick={() => send({ type: "agent_turn_interrupt", turn_id: state.working!.turnId })}
              aria-label="Stop Agent"
            >
              <Icon name="stop" size={13} />
              Stop
            </button>
          )}
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
          aria-label="Message Sonex"
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe what you want to hear…"
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
          <button
            className="model-badge"
            disabled={!ready || busy}
            onClick={() => command("/model")}
            type="button"
          >
            <i className={state.auth?.ready ? "live-dot" : ""} />
            {state.auth?.model_label || state.auth?.model || "Connect model"}
            <Icon name="down" size={12} />
          </button>
          <span className="runtime-label">
            {ready ? "Running locally" : state.status === "starting" ? "Starting…" : "Disconnected"}
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
            aria-label="Send message"
          >
            <Icon name="arrow" />
          </button>
        </div>
      </form>
      <div className="composer-hint">
        <span>Enter to send · Shift + Enter for a new line</span>
      </div>
    </div>
  );
  const interaction = (state.setup || state.confirm) && (
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
  );
  return (
    <div
      className={`app ${collapsed ? "nav-collapsed" : ""} ${showPlayer ? "show-player" : ""}`}
    >
      <aside className="navigation" aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark">s.</span>
          <span className="brand-name">Sonex</span>
          <button
            className="icon-button collapse"
            aria-label="Collapse sidebar"
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
            send({ type: "web", action: "new_session" });
          }}
        >
          <Icon name="plus" />
          <span>New chat</span>
          <kbd>＋</kbd>
        </button>
        <label className="search-box">
          <Icon name="search" size={15} />
          <input
            aria-label="Search chats"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
          />
        </label>
        <div className="nav-caption">Workspace</div>
        <nav>
          {navigation.map(([icon, label, action, panelType]) => (
            <button
              disabled={!ready || busy}
              className={state.panel?.type === panelType ? "selected" : ""}
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
          Chats <span>{state.sessions.length}</span>
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
                title={
                  session.title === "New session" ? "New chat" : session.title
                }
                onClick={() => {
                  setSettings(false);
                  dispatch({ type: "view", id: session.id });
                  send({
                    type: "web",
                    action: "read_session",
                    session_id: session.id,
                  });
                }}
              >
                <Icon name="chat" size={15} />
                <span>
                  {session.title === "New session" ? "New chat" : session.title}
                </span>
                {state.working?.sessionId === session.id && (
                  <i className="live-dot" />
                )}
              </button>
            ))}
          {!state.sessions.length && (
            <p className="nav-empty">No chats yet.</p>
          )}
        </div>
        <footer className="account">
          <button
            className={settings ? "selected" : ""}
            onClick={() => {
              setSettings(!settings);
              dispatch({ type: "dismiss_panel" });
            }}
            title="Settings"
          >
            <span className="avatar">
              {state.user.slice(0, 1).toUpperCase()}
            </span>
            <span className="account-name">
              {state.user}
              <small>
                Personal workspace
              </small>
            </span>
            <Icon name="settings" size={17} />
          </button>
        </footer>
      </aside>
      <main className={`workspace ${isEmpty ? "empty-session" : ""}`}>
        <header className="workspace-heading">
          {!isEmpty && (
            <h1>
              {settings
                ? "Settings"
                : state.panel
                  ? "title" in state.panel
                    ? state.panel.title
                    : "Proxy settings"
                  : title}
            </h1>
          )}
          <div className="header-actions">
            <button
              className="icon-button mobile-player-toggle"
              aria-label="Toggle player"
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
              aria-label="Dismiss error"
              onClick={() => dispatch({ type: "dismiss_error" })}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        )}
        {isEmpty ? (
          <div className="new-session-body">
            <div className="welcome">
              <h2>What would you like to listen to?</h2>
              <p>Describe a mood, name a song, or ask Sonex to make a playlist.</p>
              <div className="suggestions">
                {[
                  "Music for deep focus",
                  "Recommend something new",
                  "Build a weekend playlist",
                ].map((text) => (
                  <button
                    key={text}
                    onClick={() => {
                      setInput(text);
                      inputRef.current?.focus();
                    }}
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
            {interaction}
            {composer}
          </div>
        ) : settings ? (
          <div className="settings-view">
            <div className="eyebrow">MAKE IT YOURS</div>
            <h2>Your music, your space.</h2>
            <p className="muted">
              Your chats, memories, and playback stay on this device. Connect your own model and music services.
            </p>
            <div className="settings-grid">
              <button
                disabled={!ready || busy}
                onClick={() => command("/login")}
              >
                <Icon name="link" />
                <strong>Model connection</strong>
                <small>{state.auth?.provider || "Set up your model provider"}</small>
              </button>
              <button
                disabled={!ready || busy}
                onClick={() => command("/connect")}
              >
                <Icon name="music" />
                <strong>Music services</strong>
                <small>Connect available music sources</small>
              </button>
              <button
                disabled={!ready || busy}
                onClick={() => command("/proxy")}
              >
                <Icon name="settings" />
                <strong>Network proxy</strong>
                <small>Configure this device's connection</small>
              </button>
            </div>
            <div className="data-location">
              <span>Local data folder</span>
              <code>{state.home || "User folder / .sonex"}</code>
            </div>
            {state.status === "stopped" && (
              <button className="primary" onClick={connect}>
                Restart Runtime
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
          <Conversation
            messages={messages}
            sessionId={state.viewedId}
            scrollPositions={scrollPositions}
          />
        ) : null}
        {!isEmpty && interaction}
        {!isEmpty && composer}
      </main>
      <Player
        player={state.player}
        queue={state.queue}
        revision={state.revision}
        spotify={state.spotify}
        cover={state.cover}
        ready={ready}
        send={send}
      />
    </div>
  );
}
