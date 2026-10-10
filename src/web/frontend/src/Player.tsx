import { memo, useEffect, useState } from "react";
import { Icon } from "./Icon";
import type { State } from "./state";
import { clock, position } from "./state";
import type { Send } from "./Panels";

export const Player = memo(function Player({
  player,
  queue,
  revision,
  spotify,
  cover,
  ready,
  send,
}: Pick<State, "player" | "queue" | "revision" | "spotify" | "cover"> & {
  ready: boolean;
  send: Send;
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
    send({ type: "web", action: "player", command, value });
  const edit = (command: string, entry_id: string, destination?: number) =>
    send({
      type: "web",
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
    <aside className="player-sidebar" aria-label="Music player">
      <header className="rail-heading">
        <span>Now playing</span>
        <span className="player-source">{spotify ? "Spotify" : "Local"}</span>
      </header>
      <div className="now-playing">
        <div className={`album-art ${safeArtwork ? "has-cover" : ""}`}>
          {safeArtwork ? (
            <img
              src={safeArtwork}
              referrerPolicy="no-referrer"
              alt={`Cover art for ${player?.album || player?.name}`}
            />
          ) : (
            <div className="album-placeholder" aria-hidden="true">
              <Icon name="music" size={28} />
              <span>SONEX</span>
            </div>
          )}
        </div>
        <div className="track-meta">
          <h2>
            {player?.name && player.name !== "-"
              ? player.name
              : "Ready when you are"}
          </h2>
          <p>
            {player?.artist && player.artist !== "-"
              ? player.artist
              : "Tell Sonex what you feel like hearing."}
          </p>
        </div>
        <input
          className="progress"
          aria-label="Playback position"
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
            title={
              spotify
                ? "Previous track"
                : "Previous track is unavailable for local playback"
            }
            aria-label="Previous track"
            onClick={() => control("previous")}
          >
            <Icon name="previous" size={21} />
          </button>
          <button
            className="play-button"
            disabled={!active}
            aria-label={player?.is_playing ? "Pause" : "Resume playback"}
            onClick={() => control(player?.is_playing ? "pause" : "resume")}
          >
            <Icon name={player?.is_playing ? "pause" : "play"} size={25} />
          </button>
          <button
            className="icon-button"
            disabled={!ready || (!spotify && !queue.length)}
            aria-label="Next track"
            onClick={() => control("next")}
          >
            <Icon name="next" size={21} />
          </button>
        </div>
        <div className="volume-row">
          <Icon name="volume" size={16} />
          <input
            aria-label="Volume"
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
              ? "Buffering"
              : player?.progress_sync_lost
                ? "Syncing"
                : "On this device"}
          </span>
        </div>
      </div>
      <section className="queue-section">
        <div className="rail-heading">
          <span>
            Up next <small>{queue.length.toString().padStart(2, "0")}</small>
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
                  <strong>
                    {track.name || track.title || "Untitled track"}
                  </strong>
                  <small>{track.artist || track.provider}</small>
                </span>
              </button>
              <div className="queue-actions">
                <button
                  className="icon-button"
                  disabled={!ready || index === 0}
                  aria-label="Move track up"
                  onClick={() => edit("move", track.entry_id, index - 1)}
                >
                  <Icon name="up" size={13} />
                </button>
                <button
                  className="icon-button"
                  disabled={!ready}
                  aria-label="Remove from queue"
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
            <p>Good music is worth the wait.</p>
            <span>
              Ask Sonex for a few picks,
              <br />
              or add tracks from your library.
            </span>
          </div>
        )}
        <button
          className="open-local text-button"
          disabled={!ready}
          onClick={() => send({ type: "web", action: "command", command: "/library" })}
        >
          <Icon name="plus" size={14} />
          Open music library
        </button>
      </section>
    </aside>
  );
});
