use crate::{http::Response, Error, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::LazyLock,
    time::{SystemTime, UNIX_EPOCH},
};
use url::Url;

const PROBE: &str = "http://www.msftconnecttest.com/connecttest.txt";
static PORTAL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"https?://[^\s"'<>]+/portal\.do\?[^\s"'<>]+"#).unwrap());

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Config {
    pub account: String,
    pub operator: String,
    pub portal_url: String,
    #[serde(default)]
    pub password: String,
    #[serde(default = "interval")]
    pub interval_seconds: u64,
    #[serde(default)]
    pub auto_start: bool,
    #[serde(default)]
    pub enabled: bool,
}
fn interval() -> u64 {
    10
}
impl Config {
    pub fn validate(&self, configured: bool) -> Result<()> {
        if self.account.is_empty()
            || self.account.len() > 64
            || !self
                .account
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
        {
            return Err(Error::new(
                "config",
                "账号只能包含字母、数字、点、下划线或连字符，长度 1—64。",
            ));
        }
        if !["yd", "lt", "dx", "hsd"].contains(&self.operator.as_str()) {
            return Err(Error::new("config", "运营商必须是 yd、lt、dx 或 hsd。"));
        }
        validate_portal(&self.portal_url)?;
        if !(5..=3600).contains(&self.interval_seconds) {
            return Err(Error::new("config", "检测间隔须为 5—3600 秒。"));
        }
        if self.password.chars().count() > 128
            || (!self.password.is_empty() && self.password.trim().is_empty())
        {
            return Err(Error::new(
                "config",
                "密码须包含非空白字符，最多 128 字符。",
            ));
        }
        if self.password.is_empty() && !configured {
            return Err(Error::new("config", "首次配置必须输入密码。"));
        }
        Ok(())
    }
}

pub fn runtime_dir() -> Result<PathBuf> {
    let path = if let Some(path) = std::env::var_os("HTU_RUNTIME_DIR") {
        PathBuf::from(path)
    } else {
        dirs::data_local_dir()
            .ok_or_else(|| Error::new("config", "无法定位用户数据目录。"))?
            .join("HTUConnect")
    };
    if !path.is_absolute() {
        return Err(Error::new("config", "HTU_RUNTIME_DIR 必须为绝对路径。"));
    }
    Ok(path)
}

pub fn validate_portal(value: &str) -> Result<Url> {
    let error = || {
        Error::new(
            "portal",
            "门户须为 http(s)://10.101.2.194:6060/portal.do，并保留查询参数。",
        )
    };
    let url = Url::parse(value).map_err(|_| error())?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str() != Some("10.101.2.194")
        || url.port() != Some(6060)
        || url.path() != "/portal.do"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || url.query().is_none_or(|query| query.is_empty())
    {
        return Err(error());
    }
    Ok(url)
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct State {
    pub state: String,
    pub online: bool,
    pub authenticated: bool,
    pub checked_at: f64,
    pub message: String,
    pub error_stage: Option<String>,
    pub error: Option<String>,
    pub portal_url: Option<String>,
    pub failures: u64,
    pub next_delay: u64,
}
impl State {
    fn new(state: &str, message: &str) -> Self {
        Self {
            state: state.into(),
            online: state == "online",
            authenticated: false,
            checked_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            message: message.into(),
            error_stage: None,
            error: None,
            portal_url: None,
            failures: 0,
            next_delay: 0,
        }
    }
    fn failed(error: Error) -> Self {
        let mut result = Self::new("error", &error.message);
        result.error = Some(error.message);
        result.error_stage = Some(error.stage);
        result
    }
}
type Transport<'a> = dyn FnMut(&str, bool, u64) -> Result<Response> + 'a;
fn send(
    transport: &mut Transport<'_>,
    url: &str,
    post: bool,
    timeout: u64,
    stage: &str,
) -> Result<Response> {
    transport(url, post, timeout).map_err(|error| Error::new(stage, &error.message))
}

pub fn check(transport: &mut Transport<'_>) -> Result<State> {
    let response = send(transport, PROBE, false, 4, "probe")?;
    if response.code == 200 && response.body == b"Microsoft Connect Test" {
        return Ok(State::new("online", "网络在线。"));
    }
    let body = String::from_utf8_lossy(&response.body);
    let candidate = if !response.location.is_empty() {
        Some(response.location.as_str())
    } else {
        PORTAL.find(&body).map(|value| value.as_str())
    };
    if let Some(value) = candidate {
        let portal = value.replace("&amp;", "&");
        validate_portal(&portal)?;
        let mut result = State::new("captive", "校园网等待认证。");
        result.portal_url = Some(portal);
        return Ok(result);
    }
    Err(Error::new("probe", "探针响应与预期不符，未确认校园门户。"))
}

pub fn login(config: &Config, transport: &mut Transport<'_>) -> Result<State> {
    config.validate(false)?;
    let portal = validate_portal(&config.portal_url)?;
    let mut params: BTreeMap<String, String> = portal
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let mut metadata_url = portal.clone();
    metadata_url.set_path("/PortalJsonAction.do");
    metadata_url
        .query_pairs_mut()
        .append_pair("viewStatus", "1");
    let metadata = parse_json(
        send(transport, metadata_url.as_str(), false, 6, "metadata")?,
        "metadata",
    )?;
    for (source, key, target) in [
        ("serverForm", "serverip", "wlanacIp"),
        ("serverForm", "portalVer", "version"),
        ("portalconfig", "id", "portalpageid"),
        ("portalconfig", "timestamp", "timestamp"),
        ("portalconfig", "uuid", "uuid"),
    ] {
        let value = match &metadata[source][key] {
            Value::String(value) if !value.is_empty() => value.clone(),
            Value::Number(value) => value.to_string(),
            _ => return Err(Error::new("metadata", "门户元数据缺少认证所需字段。")),
        };
        params.insert(target.into(), value);
    }
    params.insert(
        "userid".into(),
        format!("{}@{}", config.account, config.operator),
    );
    params.insert("passwd".into(), config.password.clone());
    for (key, value) in [
        ("wlanuseripv6", ""),
        ("ssid", ""),
        ("portaltype", "0"),
        ("hostname", "HTU-Connect"),
        ("validateCode", ""),
        ("bindCtrlId", ""),
    ] {
        params.entry(key.into()).or_insert_with(|| value.into());
    }
    let mut auth = portal;
    auth.set_path("/quickauth.do");
    auth.set_query(None);
    auth.query_pairs_mut().extend_pairs(params.iter());
    let json = parse_json(send(transport, auth.as_str(), false, 8, "auth")?, "auth")?;
    if json["code"] != "0" && json["code"] != 0 {
        return Err(Error::new(
            "auth",
            "校园网认证失败，请检查账号、密码和运营商。",
        ));
    }
    let mut result = match check(transport) {
        Ok(mut state) => {
            state.message = if state.online {
                "登录成功，网络在线。"
            } else {
                "认证已接受，网络仍待认证。"
            }
            .into();
            state
        }
        Err(error) => {
            let mut state = State::failed(error);
            state.message = "认证已接受，联网检测失败。".into();
            state
        }
    };
    result.authenticated = true;
    Ok(result)
}
fn parse_json(response: Response, stage: &str) -> Result<Value> {
    if response.code != 200 {
        return Err(Error::new(
            stage,
            &format!("门户请求返回 HTTP {}。", response.code),
        ));
    }
    serde_json::from_slice(&response.body).map_err(|_| Error::new(stage, "门户响应不是有效 JSON。"))
}
pub fn logout(transport: &mut Transport<'_>) -> Result<State> {
    let response = send(transport, "http://10.101.2.205/loginOut", true, 4, "logout")?;
    if parse_json(response, "logout")?["result"] != 1 {
        return Err(Error::new("logout", "校园网登出失败。"));
    }
    Ok(State::new("unknown", "已登出校园网。"))
}
pub fn tick(config: &Config, failures: u64, transport: &mut Transport<'_>) -> State {
    let result = check(transport).and_then(|state| {
        if state.state == "captive" {
            login(config, transport)
        } else {
            Ok(state)
        }
    });
    let mut state = result.unwrap_or_else(State::failed);
    state.failures = if state.online {
        0
    } else {
        failures.saturating_add(1)
    };
    state.next_delay = (config.interval_seconds * (1 << state.failures.saturating_sub(1).min(3)))
        .min(config.interval_seconds.max(60));
    state
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn response(code: u32, body: Value) -> Response {
        Response {
            code,
            body: body.to_string().into_bytes(),
            location: String::new(),
        }
    }
    fn config() -> Config {
        serde_json::from_value(json!({"account":"example","operator":"hsd","portalUrl":"http://10.101.2.194:6060/portal.do?ip=1","password":"test-secret"})).unwrap()
    }
    fn metadata() -> Value {
        json!({"serverForm":{"serverip":"1","portalVer":"2"},"portalconfig":{"id":3,"timestamp":4,"uuid":"u"}})
    }
    #[test]
    fn portal_rejects_other_destinations_and_missing_parameters() {
        assert!(validate_portal(&config().portal_url).is_ok());
        for url in [
            "http://8.8.8.8:6060/portal.do?q=1",
            "http://10.101.2.194/portal.do?q=1",
            "http://u:p@10.101.2.194:6060/portal.do?q=1",
            "http://10.101.2.194:6060/portal.do",
        ] {
            assert!(validate_portal(url).is_err());
        }
    }
    #[test]
    fn configuration_is_strict() {
        let mut value = config();
        value.account = "example@lt".into();
        assert!(value.validate(true).is_err());
        value = config();
        value.interval_seconds = 1;
        assert!(value.validate(true).is_err());
        value = config();
        value.password.clear();
        assert!(value.validate(false).is_err());
        assert!(value.validate(true).is_ok());
    }
    #[test]
    fn check_is_read_only_and_requires_expected_content() {
        let mut count = 0;
        let state = check(&mut |url, post, _| {
            count += 1;
            assert_eq!(url, PROBE);
            assert!(!post);
            Ok(Response {
                code: 200,
                body: b"Microsoft Connect Test".to_vec(),
                location: String::new(),
            })
        })
        .unwrap();
        assert!(state.online);
        assert!(!state.authenticated);
        assert_eq!(count, 1);
        assert!(check(&mut |_, _, _| Ok(response(200, json!("unrecognized page")))).is_err());
    }
    #[test]
    fn invalid_probe_does_not_trigger_authentication() {
        let mut count = 0;
        let state = tick(&config(), 0, &mut |url, _, _| {
            count += 1;
            assert_eq!(url, PROBE);
            Ok(response(503, json!({})))
        });
        assert_eq!(state.error_stage.as_deref(), Some("probe"));
        assert_eq!(count, 1);
        assert_eq!(state.failures, 1);
    }
    #[test]
    fn metadata_failure_stops_before_authentication() {
        let mut count = 0;
        let error = login(&config(), &mut |url, _, _| {
            count += 1;
            assert!(url.contains("PortalJsonAction.do"));
            Ok(response(200, json!({})))
        })
        .unwrap_err();
        assert_eq!(error.stage, "metadata");
        assert_eq!(count, 1);
        assert!(!error.message.contains("test-secret"));
    }
    #[test]
    fn authentication_and_online_are_separate_and_query_is_encoded() {
        let mut count = 0;
        let result = login(&config(), &mut |url, post, _| {
            count += 1;
            assert!(!post);
            match count {
                1 => Ok(response(200, metadata())),
                2 => {
                    let url = Url::parse(url).unwrap();
                    let q: BTreeMap<_, _> = url.query_pairs().collect();
                    assert_eq!(q["userid"], "example@hsd");
                    assert_eq!(q["passwd"], "test-secret");
                    assert_eq!(q["portalpageid"], "3");
                    Ok(response(200, json!({"code":0})))
                }
                3 => Err(Error::new("http", "probe unavailable")),
                _ => panic!("unexpected request"),
            }
        })
        .unwrap();
        assert!(result.authenticated);
        assert!(!result.online);
        assert_eq!(result.error_stage.as_deref(), Some("probe"));
        assert_eq!(count, 3);
    }
    #[test]
    fn authentication_failure_does_not_echo_remote_secrets() {
        let mut count = 0;
        let error = login(&config(), &mut |_, _, _| {
            count += 1;
            Ok(response(
                200,
                if count == 1 {
                    metadata()
                } else {
                    json!({"code":"1","message":"test-secret"})
                },
            ))
        })
        .unwrap_err();
        assert_eq!(error.stage, "auth");
        assert!(!error.message.contains("test-secret"));
        assert_eq!(count, 2);
    }
    #[test]
    fn logout_uses_only_the_supported_post_endpoint() {
        let state = logout(&mut |url, post, _| {
            assert_eq!(url, "http://10.101.2.205/loginOut");
            assert!(post);
            Ok(response(200, json!({"result":1})))
        })
        .unwrap();
        assert_eq!(state.state, "unknown");
    }
    #[test]
    fn captive_tick_uses_one_login_and_bounded_delay() {
        let mut count = 0;
        let state = tick(&config(), 30, &mut |_, _, _| {
            count += 1;
            Ok(Response {
                code: 302,
                body: Vec::new(),
                location: config().portal_url,
            })
        });
        assert_eq!(count, 2);
        assert_eq!(state.error_stage.as_deref(), Some("metadata"));
        assert_eq!(state.next_delay, 60);
    }
}
