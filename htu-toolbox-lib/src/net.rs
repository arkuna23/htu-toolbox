use core::str;
use std::{str::FromStr, sync::LazyLock, time::Duration};

use serde::{Deserialize, Serialize};
use url::Url;

use crate::{
    http::{self, Request},
    Result,
};

pub static INDEX_URL_REGEX: LazyLock<regex::Regex> =
    LazyLock::new(|| regex::Regex::new(r#""(http://.*)&url=""#).unwrap());

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
pub enum Operator {
    #[serde(rename = "yd")]
    Mobie,
    #[serde(rename = "lt")]
    Unicom,
    #[serde(rename = "dx")]
    Telecom,
}

impl AsRef<str> for Operator {
    fn as_ref(&self) -> &str {
        match self {
            Operator::Mobie => "yd",
            Operator::Unicom => "lt",
            Operator::Telecom => "dx",
        }
    }
}

impl FromStr for Operator {
    type Err = ();

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        match s {
            "yd" => Ok(Operator::Mobie),
            "lt" => Ok(Operator::Unicom),
            "dx" => Ok(Operator::Telecom),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct AuthResponse {
    pub code: String,
    pub message: String,
}

impl AuthResponse {
    pub fn success(&self) -> bool {
        self.code == "0"
    }
}

pub struct AuthRequest {
    base_url: String,
    params: Vec<(String, String)>,
}

impl AuthRequest {
    pub fn create(index_url: Option<&str>) -> Result<Self> {
        let index_data = http::curl(
            Request::builder(index_url.unwrap_or("http://192.168.1.1"))
                .timeout(Duration::from_millis(100))
                .ignore_timeout(),
        )?;
        let index_content = String::from_utf8(index_data.data)?;
        let redirect_url = match INDEX_URL_REGEX
            .captures(index_content.as_ref())
            .and_then(|caps| caps.get(1).map(|m| m.as_str().trim_matches('"')))
        {
            Some(r) => r,
            None => return Err(crate::Error::InvalidIndexContent(index_content)),
        };
        let url = Url::parse(redirect_url)?;
        Ok(Self {
            base_url: format!(
                "{}://{}:{}",
                url.scheme(),
                url.host_str().ok_or(url::ParseError::EmptyHost)?,
                url.port().unwrap_or(80)
            ),
            params: url
                .query_pairs()
                .map(|(key, value)| (key.into_owned(), value.into_owned()))
                .collect(),
        })
    }

    pub fn quick_auth(
        &self,
        userid: impl AsRef<str>,
        passwd: impl AsRef<str>,
        operator: impl AsRef<str>,
    ) -> crate::Result<AuthResponse> {
        let mut url = Url::from_str(&format!("{}/quickauth.do", self.base_url))?;
        let mut userid = userid.as_ref().to_owned();
        userid.push('@');
        userid.push_str(operator.as_ref());
        url.query_pairs_mut()
            .extend_pairs(&self.params)
            .append_pair("userid", &userid)
            .append_pair("passwd", passwd.as_ref());

        let resp = http::curl_json(url.as_str())?;
        Ok(resp.data)
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct LogoutResponse {
    pub result: i32,
    pub msg: String,
}

impl LogoutResponse {
    pub fn success(&self) -> bool {
        self.result == 1
    }
}

pub fn ping() -> bool {
    http::curl(Request::builder("www.baidu.com").timeout(Duration::from_millis(500))).is_ok()
}

pub fn logout() -> Result<LogoutResponse> {
    Ok(http::curl_json(
        Request::builder("http://10.101.2.205/loginOut")
            .method(http::Method::Post(&[]))
            .timeout(Duration::from_secs(2)),
    )?
    .data)
}
