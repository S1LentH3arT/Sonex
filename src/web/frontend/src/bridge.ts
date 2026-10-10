import type { ClientEvent } from "./protocol";
import type { WebCommand, WebEvent } from "./protocol";

let socket: WebSocket | null = null;
let receiver: ((event: WebEvent) => void) | null = null;
let reconnectTimer = 0;

export function startRuntime(receive: (event: WebEvent) => void): void {
  receiver = receive;
  window.clearTimeout(reconnectTimer);
  socket?.close();
  const connect = () => {
    receiver?.({ type: "runtime_status", status: "starting" });
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const current = new WebSocket(`${protocol}//${window.location.host}/web/ws`);
    socket = current;
    current.onopen = () => {
      if (socket !== current) return;
      receiver?.({ type: "runtime_status", status: "ready" });
      current.send(JSON.stringify({ type: "web", action: "snapshot" }));
    };
    current.onmessage = ({ data }) => {
      try {
        receiver?.(JSON.parse(data) as WebEvent);
      } catch (error) {
        receiver?.({ type: "error", message: `Invalid Runtime event: ${String(error)}` });
      }
    };
    current.onclose = () => {
      if (socket !== current) return;
      socket = null;
      receiver?.({ type: "runtime_status", status: "stopped" });
      reconnectTimer = window.setTimeout(connect, 1000);
    };
  };
  connect();
}

export async function send(message: ClientEvent | WebCommand): Promise<void> {
  if (!socket || socket.readyState !== WebSocket.OPEN)
    throw new Error("Sonex Runtime is reconnecting. Try again in a moment.");
  socket.send(JSON.stringify(message));
}
