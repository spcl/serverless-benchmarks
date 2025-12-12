use lambda_runtime::{service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Deserialize)]
struct Request {
    sleep: Option<f64>,
}

#[derive(Serialize)]
struct Response {
    result: f64,
    begin: f64,
    end: f64,
    is_cold: bool,
    request_id: String,
}

static mut IS_COLD: bool = true;

async fn handler(event: LambdaEvent<Request>) -> Result<Response, Error> {
    let (payload, context) = event.into_parts();
    
    let begin = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    
    // Get the cold start status
    let is_cold = unsafe {
        let cold = IS_COLD;
        IS_COLD = false;
        cold
    };
    
    // Get sleep time from event
    let sleep_time = payload.sleep.unwrap_or(0.0);
    
    // Sleep for the specified time
    if sleep_time > 0.0 {
        tokio::time::sleep(Duration::from_secs_f64(sleep_time)).await;
    }
    
    let end = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    
    Ok(Response {
        result: sleep_time,
        begin,
        end,
        is_cold,
        request_id: context.request_id,
    })
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    lambda_runtime::run(service_fn(handler)).await
}
