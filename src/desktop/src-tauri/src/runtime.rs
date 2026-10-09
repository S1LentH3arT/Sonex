use std::{path::PathBuf, process::Stdio, sync::{Arc, atomic::AtomicBool}};
use tauri::{ipc::Channel, Manager};
use serde_json::{json, Value};
use tokio::{io::{AsyncBufReadExt, AsyncWriteExt, BufReader}, process::Command, sync::{mpsc, Mutex, Notify}};
use crate::process_group::ProcessGroup;

#[derive(Default)]
pub struct Runtime {
    sender: Mutex<Option<mpsc::Sender<Value>>>,
    events: Arc<Mutex<Option<Channel<Value>>>>,
    stopped: Arc<Notify>,
    pub exiting: AtomicBool,
}

impl Runtime {
    pub async fn shutdown(&self) {
        let stopped = self.stopped.notified();
        if self.sender.lock().await.take().is_some() {
            let _ = tokio::time::timeout(std::time::Duration::from_secs(5), stopped).await;
        }
    }
}

fn command(app: &tauri::AppHandle) -> Result<Command, String> {
    let mut command;
    if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..").canonicalize().map_err(|e| e.to_string())?;
        let python = root.join(if cfg!(windows) { ".venv/Scripts/python.exe" } else { ".venv/bin/python" });
        if !python.is_file() { return Err("Create the repository .venv and install Sonex's Python dependencies first.".into()); }
        command = Command::new(python);
        command.args(["-m", "src.desktop.runtime"]).current_dir(root);
    } else {
        let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
        let executable = resources.join("runtime").join(if cfg!(windows) { "sonex-runtime.exe" } else { "sonex-runtime" });
        if !executable.is_file() { return Err("The bundled Sonex runtime is missing. Reinstall the application.".into()); }
        command = Command::new(executable);
        let player_dir = resources.join("player");
        let mut paths = vec![player_dir];
        paths.extend(std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()));
        command.env("PATH", std::env::join_paths(paths).map_err(|e| e.to_string())?);
    }
    #[cfg(windows)]
    command.creation_flags(0x08000000); // CREATE_NO_WINDOW; keep pipes for the protocol.
    command.env("PYTHONUTF8", "1").stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit()).kill_on_drop(true);
    Ok(command)
}

#[tauri::command]
pub async fn runtime_start(app: tauri::AppHandle, state: tauri::State<'_, Runtime>, events: Channel<Value>) -> Result<(), String> {
    *state.events.lock().await = Some(events);
    let mut sender = state.sender.lock().await;
    if let Some(existing) = sender.as_ref().filter(|sender| !sender.is_closed()) {
        return existing.send(json!({"type":"desktop","action":"snapshot"})).await.map_err(|e| e.to_string());
    }
    let mut child = command(&app)?.spawn().map_err(|e| e.to_string())?;
    let group = ProcessGroup::attach(child.id().ok_or("Runtime process has no PID")?).map_err(|e| e.to_string())?;
    let mut input = child.stdin.take().ok_or("Runtime stdin is missing")?;
    let output = child.stdout.take().ok_or("Runtime stdout is missing")?;
    let (tx, mut rx) = mpsc::channel::<Value>(64);
    *sender = Some(tx);
    let events = state.events.clone();
    let stopped = state.stopped.clone();
    tauri::async_runtime::spawn(async move {
        let _group = group;
        let mut lines = BufReader::new(output).lines();
        let result: Result<(), String> = async {
            loop {
                tokio::select! {
                    message = rx.recv() => match message {
                        Some(message) => {
                            let mut data = serde_json::to_vec(&message).map_err(|e| e.to_string())?;
                            data.push(b'\n');
                            input.write_all(&data).await.map_err(|e| e.to_string())?;
                            input.flush().await.map_err(|e| e.to_string())?;
                        }
                        None => break,
                    },
                    line = lines.next_line() => match line.map_err(|e| e.to_string())? {
                        Some(line) => {
                            let event: Value = serde_json::from_str(&line).map_err(|_| "Runtime sent an invalid message".to_string())?;
                            if let Some(channel) = events.lock().await.as_ref() { let _ = channel.send(event); }
                        }
                        None => break,
                    },
                }
            }
            Ok(())
        }.await;
        drop(input);
        if tokio::time::timeout(std::time::Duration::from_secs(3), child.wait()).await.is_err() { let _ = child.kill().await; }
        if let Some(channel) = events.lock().await.as_ref() {
            let _ = channel.send(json!({"type":"runtime_status", "status":"stopped", "message":result.err().unwrap_or_else(|| "本地 Runtime 已停止。".into())}));
        }
        stopped.notify_one();
    });
    Ok(())
}

#[tauri::command]
pub async fn runtime_send(state: tauri::State<'_, Runtime>, message: Value) -> Result<(), String> {
    let kind = message.get("type").and_then(Value::as_str).ok_or("Missing message type")?;
    if !["desktop", "agent_turn_interrupt", "confirm_result", "auth_setup_input", "setup_input", "track_panel_action", "memory_panel_action", "extension_panel_action", "extension_panel_input", "proxy_action"].contains(&kind) {
        return Err("Unsupported desktop message".into());
    }
    if serde_json::to_vec(&message).map_err(|e| e.to_string())?.len() > 131_000 { return Err("Message is too large".into()); }
    let sender = state.sender.lock().await.clone().ok_or("Runtime is not connected")?;
    sender.send(message).await.map_err(|e| e.to_string())
}
