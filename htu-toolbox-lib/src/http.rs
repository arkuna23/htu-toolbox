use std::time::Duration;

use curl::easy::Easy;
use serde::de::DeserializeOwned;

#[derive(Debug, Default)]
pub enum Method<'a> {
    #[default]
    Get,
    Post(&'a [u8]),
    Put(&'a [u8]),
}

#[derive(Debug, Default)]
pub struct Request<'a> {
    pub url: &'a str,
    pub method: Method<'a>,
    pub timeout: Option<Duration>,
    pub ignore_timeout: bool,
}

impl Request<'_> {
    pub fn builder(url: &str) -> RequestBuilder {
        RequestBuilder::url(url)
    }
}

#[derive(Debug)]
pub struct RequestBuilder<'a> {
    url: &'a str,
    method: Option<Method<'a>>,
    timeout: Option<Duration>,
    ignore_timeout: bool,
}

impl<'a> RequestBuilder<'a> {
    pub fn url(url: &'a str) -> Self {
        Self {
            url,
            method: None,
            timeout: None,
            ignore_timeout: false,
        }
    }

    pub fn method(mut self, method: Method<'a>) -> Self {
        self.method = Some(method);
        self
    }

    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    pub fn ignore_timeout(mut self) -> Self {
        self.ignore_timeout = true;
        self
    }

    pub fn build(self) -> Request<'a> {
        Request {
            url: self.url,
            method: self.method.unwrap_or_default(),
            timeout: self.timeout,
            ignore_timeout: self.ignore_timeout,
        }
    }
}

impl<'a> From<RequestBuilder<'a>> for Request<'a> {
    fn from(val: RequestBuilder<'a>) -> Self {
        val.build()
    }
}

impl<'a> From<&'a str> for Request<'a> {
    fn from(val: &'a str) -> Self {
        Request::builder(val).build()
    }
}

pub struct HttpResponse<D = Vec<u8>> {
    pub code: u32,
    pub data: D,
}

pub fn curl<'a>(req: impl Into<Request<'a>>) -> crate::Result<HttpResponse> {
    let mut easy = Easy::new();
    let req: Request = req.into();
    easy.url(req.url)?;
    match req.method {
        Method::Get => {}
        Method::Post(data) => {
            easy.post(true)?;
            easy.post_fields_copy(data)?;
        }
        Method::Put(data) => {
            easy.put(true)?;
            easy.post_fields_copy(data)?;
        }
    }
    if let Some(dur) = req.timeout {
        easy.timeout(dur)?;
    }

    let mut data = vec![];
    {
        let mut transfer = easy.transfer();
        transfer.write_function(|new_data| {
            data.extend(new_data);
            Ok(new_data.len())
        })?;
        if let Err(e) = transfer.perform() {
            if !e.is_operation_timedout() {
                return Err(e.into());
            }
        };
    }

    Ok(HttpResponse {
        code: easy.response_code()?,
        data,
    })
}

pub fn curl_json<'a, D: DeserializeOwned>(
    req: impl Into<Request<'a>>,
) -> crate::Result<HttpResponse<D>> {
    let response = curl(req)?;
    let data: D = serde_json::from_slice(&response.data)?;
    Ok(HttpResponse {
        code: response.code,
        data,
    })
}
