import { memo, useEffect, useState } from "react";
import { Icon } from "./Icon";
import type { State } from "./state";
import { clock, position } from "./state";
import type { Send } from "./Panels";
import { openMusic } from "./bridge";

export const Player = memo(function Player({
  player,
  queue,
  revision,
  spotify,
  cover,
  ready,
  send,
  onError,
}: Pick<State, "player" | "queue" | "revision" | "spotify" | "cover"> & {
  ready: boolean;
  send: Send;
  onError: (message: string) => void;
}) {
  const [now, setNow] = useState(Date.now());
  const [seeking, setSeeking] = useState<number | null>(null);
  const [volume, setVolume] = useState(70);
  const [dragged, setDragged] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (player?.volume_percent != null) setVolume(player.volume_percent);
  }, [player?.volume_percent]);
  const control = (command: string, value?: number) =>
    send({ type: "desktop", action: "player", command, value });
  const edit = (command: string, entry_id: string, destination?: number) =>
    send({
      type: "desktop",
      action: "queue",
      command,
      entry_id,
      destination,
      revision,
    });
  const progress = player ? position(player, now) : 0;
  const active = ready && !!player && !player.ended;
  const seek = () => {
    if (seeking != null) {
      control("seek", seeking);
      setSeeking(null);
    }
  };
  const safeArtwork = cover?.data;
  return (
    <aside className="player-sidebar" aria-label="播放器">
      <header className="rail-heading">
        <span>正在播放</span>
        <span className="eyebrow">NOW PLAYING</span>
      </header>
      <div className="now-playing">
        <div className={`record-sleeve ${safeArtwork ? "has-cover" : ""}`}>
          {safeArtwork ? (
            <img
              src={safeArtwork}
              referrerPolicy="no-referrer"
              alt={`${player?.album || player?.name} 封面`}
            />
          ) : (
            <>
              <div className="record">
                <div className="record-label">
                  <span>s.</span>
                </div>
              </div>
              <span className="sleeve-caption">
                SONEX / YOUR LISTENING ROOM
              </span>
            </>
          )}
        </div>
        <div className="track-meta">
          <h2>
            {player?.name && player.name !== "-"
              ? player.name
              : "等待下一首心动"}
          </h2>
          <p>
            {player?.artist && player.artist !== "-"
              ? player.artist
              : "从一句话，开始聆听。"}
          </p>
        </div>
        <input
          className="progress"
          aria-label="播放进度"
          type="range"
          min="0"
          max={player?.duration_ms || 1}
          step="1000"
          value={seeking ?? progress}
          disabled={!active || spotify || !player?.duration_ms}
          onChange={(e) => setSeeking(Number(e.target.value))}
          onPointerUp={seek}
          onKeyUp={seek}
        />
        <div className="time-row">
          <span>{clock(seeking ?? progress)}</span>
          <span>{clock(player?.duration_ms || 0)}</span>
        </div>
        <div className="transport-controls">
          <button
            className="icon-button"
            disabled={!active || !spotify}
            title={spotify ? "上一首" : "当前本地播放器暂不支持上一首"}
            aria-label="上一首"
            onClick={() => control("previous")}
          >
            <Icon name="previous" size={21} />
          </button>
          <button
            className="play-button"
            disabled={!active}
            aria-label={player?.is_playing ? "暂停" : "继续播放"}
            onClick={() => control(player?.is_playing ? "pause" : "resume")}
          >
            <Icon name={player?.is_playing ? "pause" : "play"} size={25} />
          </button>
          <button
            className="icon-button"
            disabled={!ready || (!spotify && !queue.length)}
            aria-label="下一首"
            onClick={() => control("next")}
          >
            <Icon name="next" size={21} />
          </button>
        </div>
        <div className="volume-row">
          <Icon name="volume" size={16} />
          <input
            aria-label="音量"
            type="range"
            min="0"
            max="100"
            value={volume}
            disabled={!active || spotify}
            onChange={(e) => setVolume(Number(e.target.value))}
            onPointerUp={() => control("volume", volume)}
            onKeyUp={() => control("volume", volume)}
          />
          <span>{volume}%</span>
        </div>
        <div className="source-label">
          <i className={active ? "live-dot" : ""} />
          {spotify ? "Spotify Connect" : "SONEX PLAYER"}
          <span>
            {player?.paused_for_cache
              ? "缓冲中"
              : player?.progress_sync_lost
                ? "正在同步"
                : "本地运行"}
          </span>
        </div>
      </div>
      <section className="queue-section">
        <div className="rail-heading">
          <span>
            接下来 <small>{queue.length.toString().padStart(2, "0")}</small>
          </span>
          <Icon name="queue" />
        </div>
        <ol className="queue-list">
          {queue.map((track, index) => (
            <li
              key={track.entry_id}
              draggable={ready}
              onDragStart={() => setDragged(track.entry_id)}
              onDragOver={(e) => e.preventDefault()}
              onDragEnd={() => setDragged(null)}
              onDrop={(e) => {
                e.preventDefault();
                if (dragged && dragged !== track.entry_id)
                  edit("move", dragged, index);
                setDragged(null);
              }}
            >
              <button
                className="queue-track"
                disabled={!ready}
                onClick={() => edit("play", track.entry_id)}
              >
                <span className="track-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>
                  <strong>{track.name || track.title || "未命名曲目"}</strong>
                  <small>{track.artist || track.provider}</small>
                </span>
              </button>
              <div className="queue-actions">
                <button
                  className="icon-button"
                  disabled={!ready || index === 0}
                  aria-label="上移曲目"
                  onClick={() => edit("move", track.entry_id, index - 1)}
                >
                  <Icon name="up" size={13} />
                </button>
                <button
                  className="icon-button"
                  disabled={!ready}
                  aria-label="从队列移除"
                  onClick={() => edit("remove", track.entry_id)}
                >
                  <Icon name="close" size={13} />
                </button>
              </div>
            </li>
          ))}
        </ol>
        {!queue.length && (
          <div className="empty-queue">
            <Icon name="music" size={28} />
            <p>好音乐，值得排队。</p>
            <span>
              让 Sonex 推荐几首，
              <br />
              或从音乐库加入曲目。
            </span>
          </div>
        )}
        <button
          className="open-local text-button"
          disabled={!ready}
          onClick={() => {
            void openMusic().catch((error) => onError(String(error)));
          }}
        >
          <Icon name="plus" size={14} />
          打开本地音乐
        </button>
      </section>
      <footer className="player-footer">LISTEN AT YOUR OWN PACE.</footer>
    </aside>
  );
});
