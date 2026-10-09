import { Channel, invoke, isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { ClientEvent, DesktopCommand, DesktopEvent } from "./protocol";

export async function startRuntime(
  receive: (event: DesktopEvent) => void,
): Promise<void> {
  if (!isTauri())
    throw new Error(
      "浏览器仅用于界面开发。请运行 npm run dev 启动 Sonex Desktop 和本地 Runtime。",
    );
  const events = new Channel<DesktopEvent>();
  events.onmessage = receive;
  await invoke("runtime_start", { events });
}
export async function send(
  message: ClientEvent | DesktopCommand,
): Promise<void> {
  await invoke("runtime_send", { message });
}

export async function openMusic(): Promise<void> {
  const path = await open({
    multiple: false,
    filters: [
      {
        name: "音频",
        extensions: ["mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "aiff"],
      },
    ],
  });
  if (path)
    await send({
      type: "desktop",
      action: "player",
      command: "open_file",
      path,
    });
}
