use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, RequestPayloadExt, Response};
use serde::Serialize;
use std::time::{SystemTime, UNIX_EPOCH};

mod function;
pub mod storage;
pub mod nosql;

use function::{RequestPayload, FunctionResponse};

#[derive(Serialize)]
struct ResponsePayload {
    result: serde_json::Value,
    begin: f64,
    end: f64,
    is_cold: bool,
    request_id: String,
}

static mut IS_COLD: bool = true;

async fn handler(event: Request) -> Result<Response<Body>, Error> {
    let begin = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    
    let is_cold = unsafe {
        let cold = IS_COLD;
        IS_COLD = false;
        cold
    };

    let request_id = event
        .lambda_context_ref()
        .map(|ctx| ctx.request_id.clone())
        .unwrap_or_else(|| "unknown".to_string());

    // Parse Body
    let payload: RequestPayload = match event.payload() {
        Ok(Some(p)) => p,
        Ok(None) => {
            return Ok(Response::builder()
                .status(400)
                .body(Body::from("Missing request body"))
                .unwrap());
        }
        Err(e) => {
            return Ok(Response::builder()
                .status(400)
                .body(Body::from(format!("Invalid JSON: {}", e)))
                .unwrap());
        }
    };

    // Call the benchmark function (sync)
    let function_result: FunctionResponse = function::handler(payload);

    let end = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();

    // Convert result to Value
    let result_value = serde_json::to_value(&function_result.result)?;

    let response_payload = ResponsePayload {
        result: result_value,
        begin,
        end,
        is_cold,
        request_id,
    };

    let response_json = serde_json::to_string(&response_payload)?;

    Ok(Response::builder()
        .status(200)
        .header("Content-Type", "application/json")
        .body(Body::from(response_json))
        .unwrap())
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    run(service_fn(handler)).await
}
