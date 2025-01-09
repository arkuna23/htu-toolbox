use dialoguer::{theme::ColorfulTheme, Input, Password, Select};
use htu_toolbox_lib::{config::NetLoginAccount, login::Operator};

#[derive(Debug, Clone, clap::Args)]
pub struct NetLoginArgs {
    #[clap(long, short, requires_all = ["password", "operator"])]
    pub id: Option<String>,
    #[clap(long, short)]
    pub password: Option<String>,
    #[clap(long, short)]
    pub operator: Option<OperatorArg>,
}

#[derive(Debug, Clone, Copy, clap::ValueEnum)]
pub enum OperatorArg {
    #[clap(name = "yd")]
    Mobie,
    #[clap(name = "lt")]
    Unicom,
    #[clap(name = "dx")]
    Telecom,
}

impl From<Operator> for OperatorArg {
    fn from(operator: Operator) -> Self {
        match operator {
            Operator::Mobie => OperatorArg::Mobie,
            Operator::Unicom => OperatorArg::Unicom,
            Operator::Telecom => OperatorArg::Telecom,
        }
    }
}

impl From<OperatorArg> for Operator {
    fn from(operator_arg: OperatorArg) -> Self {
        match operator_arg {
            OperatorArg::Mobie => Operator::Mobie,
            OperatorArg::Unicom => Operator::Unicom,
            OperatorArg::Telecom => Operator::Telecom,
        }
    }
}

pub fn account_guide() -> eyre::Result<NetLoginAccount> {
    let theme = ColorfulTheme::default();
    let id: String = Input::with_theme(&theme).with_prompt("学号").interact()?;
    let password: String = Password::with_theme(&theme)
        .with_prompt("密码")
        .interact()?;
    let idx = Select::with_theme(&theme)
        .with_prompt("运营商")
        .items(&["中国移动", "中国联通", "中国电信"])
        .default(0)
        .interact()?;
    let operator = match idx {
        0 => Operator::Mobie,
        1 => Operator::Unicom,
        2 => Operator::Telecom,
        _ => panic!("Invalid operator selection"),
    };

    Ok(NetLoginAccount {
        id,
        password,
        operator,
    })
}
