// No console window next to the app on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{App, AppHandle, Manager, RunEvent, Url, WebviewWindow};

/// boot.py and, through it, the local server; closing its stdin tells it to stop the server.
struct Engine(Mutex<Option<Child>>);

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

fn bundled_python(res: &Path) -> std::path::PathBuf {
    if cfg!(windows) {
        res.join("python").join("python.exe")
    } else {
        res.join("python").join("bin").join("python3.11")
    }
}

fn set_step(win: &WebviewWindow, text: &str) {
    let js = format!("window.setStep && window.setStep({})", serde_json::Value::from(text));
    let _ = win.eval(js.as_str());
}

/// The start page shows the error from its query string, which also works before the page has loaded.
fn show_error(win: &WebviewWindow, text: &str) {
    if let Ok(mut url) = win.url() {
        url.set_path("/index.html");
        url.query_pairs_mut().clear().append_pair("error", text);
        let _ = win.navigate(url);
    }
}

fn start_engine(app: &App, win: WebviewWindow) -> Result<(), Box<dyn std::error::Error>> {
    let res = app.path().resource_dir()?;
    let port = free_port()?;
    let mut cmd = Command::new(bundled_python(&res));
    cmd.args(["-I", "-B", "-X", "utf8"])
        .arg(res.join("app").join("desktop").join("boot.py"))
        .arg("--port")
        .arg(port.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = cmd.spawn()?;
    let stdout = child.stdout.take().ok_or("sortie du moteur indisponible")?;
    *app.state::<Engine>().0.lock().unwrap() = Some(child);
    std::thread::spawn(move || {
        let mut ready = false;
        let mut last_error = String::new();
        let mut reader = BufReader::new(stdout);
        let mut buf = Vec::new();
        // lossy: one badly encoded line must not hide the READY that follows
        while matches!(reader.read_until(b'\n', &mut buf), Ok(n) if n > 0) {
            let text = String::from_utf8_lossy(&buf).into_owned();
            buf.clear();
            let line = text.trim_end();
            if let Some(step) = line.strip_prefix("STEP ") {
                set_step(&win, step);
            } else if let Some(err) = line.strip_prefix("ERROR ") {
                last_error = err.to_string();
            } else if line.starts_with("READY") && !ready {
                ready = true;
                if let Ok(url) = format!("http://127.0.0.1:{port}/").parse::<Url>() {
                    let _ = win.navigate(url);
                }
            }
        }
        if !ready {
            if last_error.is_empty() {
                last_error = "le moteur de calcul s'est arrêté au démarrage".into();
            }
            show_error(&win, &last_error);
        }
    });
    Ok(())
}

fn stop_engine(app: &AppHandle) {
    let Some(mut child) = app.state::<Engine>().0.lock().unwrap().take() else { return };
    drop(child.stdin.take());
    let started = Instant::now();
    while started.elapsed() < Duration::from_secs(6) {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
}

fn main() {
    tauri::Builder::default()
        .manage(Engine(Mutex::new(None)))
        .setup(|app| {
            let win = app.get_webview_window("main").ok_or("fenêtre principale absente")?;
            if let Err(e) = start_engine(app, win.clone()) {
                show_error(&win, &format!("impossible de lancer le moteur de calcul : {e}"));
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Berria Craft n'a pas pu démarrer")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_engine(app);
            }
        });
}
