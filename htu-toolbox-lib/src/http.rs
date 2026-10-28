use crate::{Error, Result};
use curl::easy::{Easy, List};
use std::time::Duration;

pub struct Response {
    pub code: u32,
    pub body: Vec<u8>,
    pub location: String,
}

/// The only transport used by the core and local API client.
pub fn request(
    url: &str,
    post: Option<&[u8]>,
    headers: &[String],
    timeout: u64,
) -> Result<Response> {
    let result = (|| -> std::result::Result<Response, curl::Error> {
        let mut easy = Easy::new();
        easy.url(url)?;
        easy.proxy("")?;
        easy.follow_location(false)?;
        easy.connect_timeout(Duration::from_secs(3))?;
        easy.timeout(Duration::from_secs(timeout))?;
        easy.useragent("HTU-Connect/2.0")?;
        if let Some(body) = post {
            easy.post(true)?;
            easy.post_fields_copy(body)?;
        }
        let mut list = List::new();
        for header in headers {
            list.append(header)?;
        }
        easy.http_headers(list)?;
        let mut body = Vec::new();
        let mut location = String::new();
        {
            let mut transfer = easy.transfer();
            transfer.write_function(|chunk| {
                if body.len() + chunk.len() > 256 * 1024 {
                    return Ok(0);
                }
                body.extend_from_slice(chunk);
                Ok(chunk.len())
            })?;
            transfer.header_function(|line| {
                if let Ok(line) = std::str::from_utf8(line) {
                    if let Some((name, value)) = line.split_once(':') {
                        if name.eq_ignore_ascii_case("location") {
                            location = value.trim().to_owned();
                        }
                    }
                }
                true
            })?;
            transfer.perform()?;
        }
        Ok(Response {
            code: easy.response_code()?,
            body,
            location,
        })
    })();
    // Do not expose URLs, remote bodies or credentials through errors.
    result.map_err(|_| Error::new("http", "网络请求失败、响应过大或超时。"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };
    #[test]
    fn partial_response_is_an_error() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let server = thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut buffer = [0; 1024];
            assert!(socket.read(&mut buffer).unwrap() > 0);
            socket
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\npartial")
                .unwrap();
        });
        assert!(request(&url, None, &[], 2).is_err());
        server.join().unwrap();
    }
}
