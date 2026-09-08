//! `ls-api-server` — bind the [`api::router`] to a TCP port.
//!
//! Usage:
//!     ls-api-server                              # listens on 127.0.0.1:8080
//!     ls-api-server --addr 0.0.0.0:3000          # custom bind
//!     ls-api-server --addr 0.0.0.0:3000 --help   # one-shot help text

use std::env;
use std::net::SocketAddr;

fn usage() {
    eprintln!("ls-api-server [--addr <host:port>]");
    eprintln!("  default: 127.0.0.1:8080");
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut addr: SocketAddr = "127.0.0.1:8080".parse().unwrap();
    let args: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--addr" if i + 1 < args.len() => {
                addr = args[i + 1].parse().map_err(|e| {
                    anyhow::anyhow!("invalid --addr `{}`: {e}", args[i + 1])
                })?;
                i += 2;
            }
            "-h" | "--help" => {
                usage();
                return Ok(());
            }
            other => {
                eprintln!("unknown arg: {other}");
                usage();
                std::process::exit(2);
            }
        }
    }

    let app = api::router();
    let listener = tokio::net::TcpListener::bind(addr).await?;
    eprintln!("ls-api-server listening on http://{}", addr);
    eprintln!("  GET  /health");
    eprintln!("  POST /solve     (body: solver::Answers JSON)");
    eprintln!("  POST /draw      (body: building JSON; ?project=&designer=&bcin=&include_ifc=&include_dxf=&obc_dir=)");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    eprintln!("shutdown: ctrl-c received");
}
