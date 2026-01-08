use serde::{Deserialize, Serialize};
use std::thread;
use std::time::Duration;

#[derive(Deserialize)]
pub struct RequestPayload {
    pub sleep: Option<f64>,
}

#[derive(Serialize)]
pub struct FunctionResponse {
    pub result: f64,
}

pub fn handler(event: RequestPayload) -> FunctionResponse {
    let sleep_time = event.sleep.unwrap_or(0.0);
    if sleep_time > 0.0 {
        thread::sleep(Duration::from_secs_f64(sleep_time));
    }
    
    FunctionResponse {
        result: sleep_time,
    }
}
