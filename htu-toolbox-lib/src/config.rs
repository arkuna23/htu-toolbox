use serde::{Deserialize, Serialize};

use crate::net::Operator;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct NetLoginAccount {
    pub id: String,
    pub password: String,
    pub operator: Operator,
}
