#![cfg_attr(
  all(not(debug_assertions), target_os = "windows"),
  windows_subsystem = "windows"
)]

use tauri::api::process::Command;
use tauri::Manager;

fn main() {
  tauri::Builder::default()
    .setup(|app| {
      println!("Booting Tauri wrapper shell... 🚀");
      
      // Spawn python FastAPI sidecar background server
      let (mut rx, mut child) = Command::new_sidecar("gstack-backend")
        .expect("Failed to initialize python backend sidecar service")
        .spawn()
        .expect("Failed to spawn python backend sidecar child process");

      println!("Python FastAPI sidecar successfully launched!");

      // Optional: Stream child process logs in background async runtime
      tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
          if let tauri::api::process::CommandEvent::Stdout(line) = event {
            println!("[sidecar-stdout] {}", line);
          } else if let tauri::api::process::CommandEvent::Stderr(line) = event {
            eprintln!("[sidecar-stderr] {}", line);
          }
        }
      });

      // Bind callback to cleanly kill sidecar on application destruction using Arc<Mutex> wrapper
      let child_shared = std::sync::Arc::new(std::sync::Mutex::new(Some(child)));
      let child_clone = child_shared.clone();
      
      let app_handle = app.handle();
      app_handle.listen_global("tauri://destroyed", move |_| {
        println!("Tauri shell closing, killing backend sidecar child process... 🛑");
        if let Ok(mut guard) = child_clone.lock() {
          if let Some(c) = guard.take() {
            c.kill().expect("Failed to terminate sidecar process cleanly");
            println!("Sidecar process terminated!");
          }
        }
      });

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("Error occurred while running tauri application");
}
