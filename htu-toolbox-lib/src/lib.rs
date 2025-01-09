use std::{fmt::Display, string::FromUtf8Error};

pub mod http;
pub mod login;
pub mod config;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Curl(#[from] curl::Error),
    #[error(transparent)]
    UrlParse(#[from] url::ParseError),
    #[error("invalid index page({0})")]
    InvalidIndexContent(String),
    #[error(transparent)]
    FromUtf8(#[from] FromUtf8Error),
    #[error("{0}")]
    Other(String),
}

impl Error {
    pub fn other<T: Display>(e: T) -> Self {
        Self::Other(e.to_string())
    }
}

pub type Result<T> = core::result::Result<T, Error>;
