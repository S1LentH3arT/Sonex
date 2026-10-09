import { useState } from "react";
import type { ClientEvent, DesktopCommand } from "./protocol";
import type { State } from "./state";
import { Icon } from "./Icon";

export type Send = (message: ClientEvent | DesktopCommand) => void;

export function Setup({
  setup,
  send,
}: {
  setup: NonNullable<State["setup"]>;
  send: Send;
}) {
  const [value, setValue] = useState("");
  const choices =
    setup.type === "auth_setup"
      ? (setup.providers ?? setup.methods ?? setup.models ?? [])
      : [];
  const submit = (text: string) => {
    send({
      type: setup.type === "auth_setup" ? "auth_setup_input" : "setup_input",
      value: text,
    });
    setValue("");
  };
  return (
    <section className="interaction" aria-label="连接设置">
      <div className="eyebrow">CONNECT YOUR PROVIDER</div>
      <h2>{setup.title}</h2>
      <p>{setup.message}</p>
      <div className="choice-list">
        {choices.map((choice) => (
          <button key={choice.value} onClick={() => submit(choice.value)}>
            <span>{choice.label}</span>
            <small>{choice.description}</small>
          </button>
        ))}
      </div>
      {!choices.length && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim()) submit(value);
          }}
        >
          <input
            aria-label={setup.prompt || "连接信息"}
            type={setup.mask ? "password" : "text"}
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={setup.prompt || "输入连接信息"}
          />
          <button className="primary" disabled={!value.trim()}>
            继续
          </button>
        </form>
      )}
      <button className="text-button" onClick={() => submit("__cancel__")}>
        取消设置
      </button>
    </section>
  );
}

export function Confirmation({
  confirm,
  send,
  dismiss,
}: {
  confirm: NonNullable<State["confirm"]>;
  send: Send;
  dismiss: () => void;
}) {
  const [value, setValue] = useState("");
  const choose = (decision: string) => {
    send({ type: "confirm_result", id: confirm.id, decision });
    dismiss();
  };
  const choices = confirm.choices?.length
    ? confirm.choices
    : [
        { value: "allow_once", label: "允许一次" },
        { value: "deny", label: "拒绝" },
      ];
  return (
    <section className="interaction" aria-label="等待确认">
      <div className="eyebrow">YOUR CALL</div>
      <h2>{confirm.message || "需要你的确认"}</h2>
      {confirm.warning && <p className="warning">{confirm.warning}</p>}
      {confirm.commands?.map((command, i) => (
        <pre key={i}>{command}</pre>
      ))}
      <div className="choice-list">
        {choices.map((choice) =>
          choice.input ? (
            <form
              key={choice.value}
              onSubmit={(e) => {
                e.preventDefault();
                if (value.trim())
                  choose(`${choice.value}:${encodeURIComponent(value.trim())}`);
              }}
            >
              <input
                aria-label={choice.label}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={choice.input.placeholder}
              />
              <button disabled={!value.trim()}>{choice.label}</button>
            </form>
          ) : (
            <button
              key={choice.value}
              disabled={choice.disabled}
              title={choice.disabled_reason}
              onClick={() => choose(choice.value)}
            >
              <span>{choice.label}</span>
              <small>{choice.description}</small>
            </button>
          ),
        )}
      </div>
    </section>
  );
}

export function FeaturePanel({
  panel,
  send,
  close,
}: {
  panel: NonNullable<State["panel"]>;
  send: Send;
  close: () => void;
}) {
  const [value, setValue] = useState("");
  const title = "title" in panel ? panel.title : "代理设置";
  return (
    <section className="feature-panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="关闭面板" onClick={close}>
          <Icon name="close" />
        </button>
      </div>
      {"hint" in panel && <p className="muted">{panel.hint}</p>}
      {panel.type === "track_panel" && (
        <div className="track-list">
          {panel.tracks.length ? (
            panel.tracks.map((track, i) => (
              <div className="library-track" key={track.id || track.uri || i}>
                <span className="muted">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{track.title || track.name}</strong>
                  <small>{track.artist}</small>
                </div>
                <button
                  className="icon-button"
                  aria-label={`播放 ${track.title || track.name}`}
                  onClick={() =>
                    send({
                      type: "track_panel_action",
                      action: "play",
                      track,
                      panel: panel.panel,
                      title: panel.title,
                    })
                  }
                >
                  <Icon name="play" />
                </button>
                <button
                  className="icon-button"
                  aria-label="加入队列"
                  onClick={() =>
                    send({
                      type: "track_panel_action",
                      action: "queue_add",
                      track,
                      panel: panel.panel,
                      title: panel.title,
                    })
                  }
                >
                  <Icon name="plus" />
                </button>
              </div>
            ))
          ) : (
            <div className="empty-small">
              还没有曲目。让 Sonex 帮你找到喜欢的音乐。
            </div>
          )}
        </div>
      )}
      {panel.type === "memory_panel" && (
        <>
          <div className="button-row">
            {(["user", "memory", "dump"] as const).map((target, i) => (
              <button
                key={target}
                onClick={() =>
                  send({ type: "memory_panel_action", action: "open", target })
                }
              >
                {["个人偏好", "音乐记忆", "记忆归档"][i]}
              </button>
            ))}
          </div>
          {(panel.entries ?? []).map((entry) => (
            <article className="memory-entry" key={entry.entry_id}>
              <p>{entry.content}</p>
              <small>{entry.source}</small>
            </article>
          ))}
          {!panel.entries?.length && (
            <div className="empty-small">
              选择一个分类，查看保存在本机的音乐偏好。
            </div>
          )}
        </>
      )}
      {panel.type === "extension_panel" && (
        <>
          {panel.extensions.map((extension) => (
            <button
              className="extension-row"
              key={extension.id}
              onClick={() =>
                send({
                  type: "extension_panel_action",
                  action: "open_detail",
                  extension_id: extension.id,
                })
              }
            >
              <Icon name="grid" />
              <span>
                <strong>{extension.name}</strong>
                <small>{extension.description}</small>
              </span>
              <small>{extension.status}</small>
            </button>
          ))}
          <div className="button-row">
            {panel.detail?.actions?.map((action) => (
              <button
                key={action}
                onClick={() =>
                  send({
                    type: "extension_panel_action",
                    action,
                    extension_id: panel.selected_extension ?? undefined,
                    token: panel.detail?.armed_token,
                    revision: panel.detail?.revision,
                  })
                }
              >
                {action}
              </button>
            ))}
          </div>
          {panel.detail?.armed_message && (
            <p className="warning">{panel.detail.armed_message}</p>
          )}
          {panel.setup && (
            <div className="interaction">
              <h3>{panel.setup.title}</h3>
              <p>{panel.setup.body}</p>
              {panel.setup.error && (
                <p className="warning">{panel.setup.error}</p>
              )}
              {panel.setup.dependencies?.map((dependency) => (
                <button
                  key={dependency.id}
                  onClick={() =>
                    send({
                      type: "extension_panel_action",
                      action: "install_dependency",
                      extension_id: panel.setup!.extension_id,
                      dependency_id: dependency.id,
                    })
                  }
                >
                  {dependency.label} · {dependency.state}
                </button>
              ))}
              {panel.setup.input && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    send({ type: "extension_panel_input", value });
                    setValue("");
                  }}
                >
                  <input
                    aria-label={panel.setup.input.placeholder}
                    type={panel.setup.input.mask ? "password" : "text"}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    placeholder={panel.setup.input.placeholder}
                  />
                  <button>保存</button>
                </form>
              )}
            </div>
          )}
        </>
      )}
      {panel.type === "proxy_state" && (
        <>
          <p>当前连接：{panel.mode === "direct" ? "直接连接" : panel.url}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send({ type: "proxy_action", action: "save", value });
            }}
          >
            <input
              aria-label="代理地址"
              placeholder={panel.url || "http://127.0.0.1:7890"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button>保存</button>
          </form>
          <button
            className="text-button"
            onClick={() => send({ type: "proxy_action", action: "direct" })}
          >
            使用直接连接
          </button>
          {panel.error && <p className="warning">{panel.error}</p>}
        </>
      )}
      {panel.type === "help_panel" && (
        <div>
          {panel.commands.map((command) => (
            <article className="memory-entry" key={command.name}>
              <strong>{command.usage}</strong>
              <p>{command.description}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
