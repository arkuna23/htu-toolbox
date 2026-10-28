use serde::Serialize;
use serde_json::{json, Value};
use std::{
    ffi::{c_char, CStr, CString},
    panic::{catch_unwind, AssertUnwindSafe},
};

pub mod http;
pub mod net;

#[derive(Debug, Serialize)]
pub struct Error {
    pub stage: String,
    pub message: String,
}
impl Error {
    pub fn new(stage: &str, message: &str) -> Self {
        Self {
            stage: stage.into(),
            message: message.into(),
        }
    }
}
pub type Result<T> = std::result::Result<T, Error>;

fn dispatch(input: &str) -> Result<Value> {
    let input: Value =
        serde_json::from_str(input).map_err(|_| Error::new("input", "请求格式无效。"))?;
    let op = input["op"]
        .as_str()
        .ok_or_else(|| Error::new("input", "缺少操作。"))?;
    if op == "runtime-dir" {
        return Ok(json!({"path": net::runtime_dir()?}));
    }
    let config = || -> Result<net::Config> {
        serde_json::from_value(input["config"].clone())
            .map_err(|_| Error::new("config", "配置字段或类型无效。"))
    };
    let mut transport = |url: &str, post: bool, timeout: u64| {
        http::request(url, post.then_some(&[][..]), &[], timeout)
    };
    match op {
        "validate" => {
            let config = config()?;
            config.validate(input["passwordConfigured"].as_bool().unwrap_or(false))?;
            Ok(json!(config))
        }
        "check" => Ok(json!(net::check(&mut transport)?)),
        "detect-portal" => {
            let result = net::check(&mut transport)?;
            result
                .portal_url
                .map(|portal| json!({"portalUrl": portal}))
                .ok_or_else(|| Error::new("portal", "未发现校园门户，请连接校园网后重试。"))
        }
        "login" => Ok(json!(net::login(&config()?, &mut transport)?)),
        "logout" => Ok(json!(net::logout(&mut transport)?)),
        "tick" => {
            let config = config()?;
            config.validate(true)?;
            Ok(json!(net::tick(
                &config,
                input["failures"].as_u64().unwrap_or(0).min(1000),
                &mut transport
            )))
        }
        _ => Err(Error::new("input", "未知操作。")),
    }
}

/// # Safety
/// input must point to a NUL-terminated UTF-8 string. Free the returned Rust
/// allocation exactly once with htu_free.
#[no_mangle]
pub unsafe extern "C" fn htu_call(input: *const c_char) -> *mut c_char {
    let result = catch_unwind(AssertUnwindSafe(|| {
        if input.is_null() {
            return Err(Error::new("input", "请求为空。"));
        }
        let text = CStr::from_ptr(input)
            .to_str()
            .map_err(|_| Error::new("input", "请求编码无效。"))?;
        dispatch(text)
    }));
    let payload = match result {
        Ok(Ok(data)) => json!({"ok":true,"data":data}),
        Ok(Err(error)) => json!({"ok":false,"error":error}),
        Err(_) => json!({"ok":false,"error":{"stage":"core","message":"核心操作失败。"}}),
    };
    CString::new(payload.to_string())
        .expect("JSON has no raw NUL")
        .into_raw()
}

/// # Safety
/// value must be a live allocation returned by htu_call, freed only once.
#[no_mangle]
pub unsafe extern "C" fn htu_free(value: *mut c_char) {
    if !value.is_null() {
        drop(CString::from_raw(value));
    }
}
