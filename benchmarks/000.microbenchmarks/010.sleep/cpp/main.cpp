
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/lambda-runtime/runtime.h>

#include <thread>
#include <iostream>

Aws::Utils::Json::JsonValue function(aws::lambda_runtime::invocation_request const &req)
{
  Aws::Utils::Json::JsonValue json(req.payload);
  std::cerr << req.payload << std::endl;
  auto v = json.View();
  std::cerr << v.KeyExists("sleep") << std::endl;
  std::cerr << v.GetObject("sleep").IsObject() << std::endl;
  std::cerr << v.GetObject("sleep").IsString() << std::endl;
  std::cerr << v.GetObject("sleep").IsBool() << std::endl;
  std::cerr << v.GetObject("sleep").IsIntegerType() << std::endl;
  int sleep = v.GetInteger("sleep");

  std::chrono::seconds timespan(sleep);
  std::this_thread::sleep_for(timespan);

  //std::string res_json = "{ \"result\": " + std::to_string(sleep) + "}";
  //return aws::lambda_runtime::invocation_response::success(res_json, "application/json");
  Aws::Utils::Json::JsonValue val;
  val.WithObject("result", std::to_string(sleep));
  return val;
}

