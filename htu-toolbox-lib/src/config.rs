use serde::{Deserialize, Serialize};

use crate::login::Operator;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct NetLoginAccount {
    pub id: String,
    pub password: String,
    pub operator: Operator,
}
