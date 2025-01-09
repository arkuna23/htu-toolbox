use clap::Parser;
use config::Config;
use console::{style, Emoji};
use eyre::Context;
use htu_toolbox_lib::login::Operator;
use net_login::NetLoginArgs;

mod config;
mod net_login;

#[derive(Debug, Clone, clap::Parser)]
struct Args {
    #[clap(subcommand)]
    cmd: Option<SubCmd>,
}

#[derive(Debug, Clone, clap::Subcommand)]
enum SubCmd {
    /// 登录校园网
    NetLogin(NetLoginArgs),
    /// 登出校园网
    NetLogout,
}

impl SubCmd {
    pub fn execute(self) -> eyre::Result<()> {
        match self {
            SubCmd::NetLogin(NetLoginArgs {
                id: Some(id),
                password: Some(pwd),
                operator: Some(operator),
            }) => {
                println!(
                    "{} {}",
                    Emoji::new("🔍", "[?]",),
                    style("获取登录页路径...")
                );
                let req = htu_toolbox_lib::login::AuthRequest::create(None)
                    .with_context(|| "登录页请求失败")?;
                let opr: Operator = operator.into();

                println!("{} {}", Emoji::new("🔌", "[+]",), style("登录校园网..."));
                let result = req
                    .quick_auth(id, pwd, opr)
                    .with_context(|| "校园网登录时发生错误")?;

                if !result.success() {
                    eyre::bail!(
                        "校园网登录失败, 错误码 {}, 错误消息: {}",
                        result.code,
                        result.message
                    )
                }
            }
            SubCmd::NetLogout => {
                println!("{} {}", Emoji::new("🔌", "[-]",), style("登出校园网..."));
                let resp = htu_toolbox_lib::login::logout().with_context(|| "登出请求失败")?;

                if !resp.success() {
                    eyre::bail!(
                        "校园网登出失败, 错误码 {}, 错误消息: {}",
                        resp.result,
                        resp.msg,
                    )
                }
            }
            _ => eyre::bail!("wrong cmd args"),
        }

        Ok(())
    }
}

fn main() -> eyre::Result<()> {
    color_eyre::install()?;
    let args = Args::parse();
    let mut cfg = Config::init().with_context(|| "配置文件加载失败")?;
    let processed = if let Some(arg) = args.cmd {
        match arg {
            SubCmd::NetLogin(mut net_login_args) => {
                if net_login_args.id.is_none() {
                    cfg.ensure_net_login_account()
                        .with_context(|| "配置文件创建失败")?;
                    net_login_args = cfg.net_login.unwrap().into();
                }
                SubCmd::NetLogin(net_login_args)
            }
            cmd => cmd,
        }
    } else {
        cfg.into_sub_cmd()?
    };
    processed.execute().with_context(|| "指令执行失败")
}
