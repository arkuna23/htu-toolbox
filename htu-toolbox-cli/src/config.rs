use std::path::PathBuf;

use console::style;
use eyre::OptionExt;
use htu_toolbox_lib::config::*;
use serde::{Deserialize, Serialize};

use crate::net_login::{self, NetLoginArgs};

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
#[serde(rename_all = "kebab-case")]
pub struct Config {
    pub on_launch: OnLaunchAction,
    pub net_login: Option<NetLoginCfg>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "kebab-case")]
pub struct NetLoginCfg {
    account: NetLoginAccount,
}

impl From<NetLoginCfg> for NetLoginArgs {
    fn from(value: NetLoginCfg) -> Self {
        let NetLoginAccount {
            id,
            password,
            operator,
        } = value.account;
        Self {
            id: Some(id),
            password: Some(password),
            operator: Some(operator.into()),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
#[serde(rename_all = "kebab-case")]
pub enum OnLaunchAction {
    #[default]
    NetLogin,
}

impl Config {
    pub fn into_sub_cmd(mut self) -> eyre::Result<super::SubCmd> {
        match self.on_launch {
            OnLaunchAction::NetLogin => {
                self.ensure_net_login_account()?;
                let Some(account) = self.net_login.map(|r| r.account) else {
                    eyre::bail!("配置缺失")
                };

                Ok(super::SubCmd::NetLogin(NetLoginArgs {
                    id: Some(account.id),
                    password: Some(account.password),
                    operator: Some(account.operator.into()),
                }))
            }
        }
    }

    pub fn cfg_path() -> eyre::Result<PathBuf> {
        Ok(dirs::config_dir()
            .ok_or_eyre("missing config dir")?
            .join("htu-toolbox")
            .join("config.toml"))
    }

    pub fn init() -> eyre::Result<Self> {
        let path = Self::cfg_path()?;
        std::fs::create_dir_all(path.parent().unwrap())?;
        let config;
        if std::fs::exists(&path)? {
            let content = std::fs::read_to_string(path)?;
            config = toml::from_str(&content)?;
        } else {
            config = Config::default();
            std::fs::write(path, toml::to_string_pretty(&config)?)?;
        }
        Ok(config)
    }

    pub fn save(&self) -> eyre::Result<()> {
        let path = Self::cfg_path()?;
        std::fs::create_dir_all(path.parent().unwrap())?;
        let content = toml::to_string_pretty(self)?;
        std::fs::write(path, content)?;
        Ok(())
    }

    pub fn ensure_net_login_account(&mut self) -> eyre::Result<()> {
        if self.net_login.is_none() {
            println!(
                "{}",
                style("未设置校园网账号，进入设置向导").yellow().bold()
            );
            let account = net_login::account_guide()?;
            self.net_login = Some(NetLoginCfg { account });
            self.save()?;
        }

        Ok(())
    }
}
