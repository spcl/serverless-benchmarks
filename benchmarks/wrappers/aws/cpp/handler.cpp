
#include <aws/core/Aws.h>
#include <aws/lambda-runtime/runtime.h>
#include <aws/s3/S3Client.h>

#include "utils.hpp"

bool cold_execution = true;
std::string container_id = "";
std::string cold_start_var = "";

Aws::Utils::Json::JsonValue function(aws::lambda_runtime::invocation_request const &req);

aws::lambda_runtime::invocation_response handler(aws::lambda_runtime::invocation_request const &req)
{
  const auto begin = std::chrono::system_clock::now();
  auto ret = function(req);
  const auto end = std::chrono::system_clock::now();

  Aws::Utils::Json::JsonValue body;
  body.WithObject("result", ret);

  // Switch cold execution after the first one.
  if(cold_execution)
    cold_execution = false;

  auto b = std::chrono::duration_cast<std::chrono::microseconds>(begin.time_since_epoch()).count() / 1000.0 / 1000.0;
  auto e = std::chrono::duration_cast<std::chrono::microseconds>(end.time_since_epoch()).count() / 1000.0 / 1000.0;
  body.WithDouble("begin", b);
  body.WithDouble("end", e);
  body.WithDouble("results_time", e - b);
  body.WithString("request_id", req.request_id);
  body.WithBool("is_cold", cold_execution);
  body.WithString("container_id", container_id);
  body.WithString("cold_start_var", cold_start_var);

  Aws::Utils::Json::JsonValue final_result;
  final_result.WithObject("body", body);
  return aws::lambda_runtime::invocation_response::success(final_result.View().WriteReadable(), "application/json");
}

int main()
{
  Aws::SDKOptions options;
  Aws::InitAPI(options);

  const char * cold_var = std::getenv("cold_start");
  if(cold_var)
    cold_start_var = cold_var;
  // FIXME: uuid - Boost
  container_id = "random";

  aws::lambda_runtime::run_handler(handler);

  Aws::ShutdownAPI(options);
  return 0;
}

