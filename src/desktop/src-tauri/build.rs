fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["runtime_start", "runtime_send"]),
        ),
    ).expect("failed to build Sonex desktop resources");
}
