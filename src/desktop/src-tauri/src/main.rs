#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod process_group;
mod runtime;
use tauri::{Manager, menu::{Menu, MenuItem}, tray::TrayIconBuilder};

fn show(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show(app)))
        .plugin(tauri_plugin_dialog::init())
        .manage(runtime::Runtime::default())
        .invoke_handler(tauri::generate_handler![runtime::runtime_start, runtime::runtime_send])
        .setup(|app| {
            let open = MenuItem::with_id(app, "open", "打开 Sonex", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出 Sonex", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            let mut tray = TrayIconBuilder::new().tooltip("Sonex · 本地音乐 Agent").menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() { "open" => show(app), "quit" => app.exit(0), _ => {} });
            if let Some(icon) = app.default_window_icon() { tray = tray.icon(icon.clone()); }
            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event { api.prevent_close(); let _ = window.hide(); }
        })
        .build(tauri::generate_context!())
        .expect("Sonex Desktop could not start")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                let state = app.state::<runtime::Runtime>();
                if !state.exiting.swap(true, std::sync::atomic::Ordering::SeqCst) {
                    api.prevent_exit();
                    let app = app.clone();
                    tauri::async_runtime::spawn(async move {
                        app.state::<runtime::Runtime>().shutdown().await;
                        app.exit(0);
                    });
                }
            }
        });
}
