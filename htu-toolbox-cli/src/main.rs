use clap::{Parser, Subcommand};
use htu_toolbox_lib::{http, net};
use serde_json::{json, Value};
use std::{
    io::{self, IsTerminal, Read},
    path::PathBuf,
    process::ExitCode,
};

#[derive(Parser)]
#[command(version, about = "HTU Connect 本机服务客户端")]
struct Args {
    /// 与桌面服务使用相同的数据目录
    #[arg(long)]
    runtime_dir: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Net {
        #[command(subcommand)]
        command: Net,
    },
}
#[derive(Subcommand)]
enum Net {
    Status,
    Check,
    Login,
    Logout,
    Start,
    Stop,
    DetectPortal,
    /// 从 stdin 读取配置 JSON；不会启动自动登录
    Set,
    Logs {
        #[arg(long, default_value_t = 250)]
        tail: u16,
    },
}

fn run() -> Result<(), String> {
    let args = Args::parse();
    let directory = args
        .runtime_dir
        .map(Ok)
        .unwrap_or_else(|| net::runtime_dir().map_err(|e| e.message))?;
    let session: Value = serde_json::from_str(
        &std::fs::read_to_string(directory.join("session.json"))
            .map_err(|_| "桌面服务未运行或数据目录不正确。请先启动服务。")?,
    )
    .map_err(|_| "本机服务会话无效，请重启服务。")?;
    let port = session["port"]
        .as_u64()
        .filter(|port| (1024..=65535).contains(port))
        .ok_or("服务端口无效。")?;
    let token = session["token"]
        .as_str()
        .filter(|token| {
            !token.is_empty()
                && token.len() <= 256
                && token
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
        })
        .ok_or("服务令牌无效。")?;
    let Command::Net { command } = args.command;
    let (path, payload) = match command {
        Net::Status => ("/api/status".into(), None),
        Net::DetectPortal => ("/api/detect-portal".into(), None),
        Net::Logs { tail } => (format!("/api/logs?tail={tail}"), None),
        Net::Set => {
            if io::stdin().is_terminal() {
                return Err("请通过 stdin 提供配置 JSON。".into());
            }
            let mut text = String::new();
            io::stdin()
                .take(64 * 1024 + 1)
                .read_to_string(&mut text)
                .map_err(|_| "无法读取配置。")?;
            if text.len() > 64 * 1024 {
                return Err("配置请求过大。".into());
            }
            let payload: Value =
                serde_json::from_str(&text).map_err(|_| "配置必须是 JSON 对象。")?;
            if !payload.is_object() {
                return Err("配置必须是 JSON 对象。".into());
            }
            ("/api/config".into(), Some(payload))
        }
        action => {
            let name = match action {
                Net::Check => "check",
                Net::Login => "login",
                Net::Logout => "logout",
                Net::Start => "start",
                Net::Stop => "stop",
                _ => unreachable!(),
            };
            ("/api/action".into(), Some(json!({"action":name})))
        }
    };
    let body = payload.map(|p| p.to_string().into_bytes());
    let response = http::request(
        &format!("http://127.0.0.1:{port}{path}"),
        body.as_deref(),
        &[
            format!("X-HTU-Token: {token}"),
            "Content-Type: application/json".into(),
        ],
        30,
    )
    .map_err(|e| e.message)?;
    let reply: Value =
        serde_json::from_slice(&response.body).map_err(|_| "本机服务没有返回有效 JSON。")?;
    if response.code != 200 || reply["ok"] != true {
        return Err(reply["error"]
            .as_str()
            .unwrap_or("本机服务操作失败。")
            .into());
    }
    println!(
        "{}",
        serde_json::to_string_pretty(&reply).map_err(|_| "无法输出结果。")?
    );
    if let Some(error) = reply["data"]["error"].as_str() {
        return Err(error.into());
    }
    Ok(())
}
fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
