
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/lambda-runtime/runtime.h>

#include <thread>
#include <iostream>
#include <tuple>

std::tuple<Aws::Utils::Json::JsonValue, int> function(Aws::Utils::Json::JsonView json)
{
  int sleep = json.GetInteger("sleep");

  std::chrono::seconds timespan(sleep);
  std::this_thread::sleep_for(timespan);

  Aws::Utils::Json::JsonValue val;
  val.WithObject("result", std::to_string(sleep));
  return std::make_tuple(val, 0);
}

