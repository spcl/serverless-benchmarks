// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
#include <chrono>
#include <cstdlib>
#include <iostream>

#ifdef SEBS_USE_AWS_SDK
#include <aws/core/Aws.h>
#endif
#include <aws/lambda-runtime/runtime.h>

#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>

#include "utils.hpp"

// Global variables that are retained across function invocations
bool cold_execution = true;
std::string container_id = "";
std::string cold_start_var = "";

rapidjson::Document function(const rapidjson::Value& req);

aws::lambda_runtime::invocation_response handler(
    aws::lambda_runtime::invocation_request const &req
) {
  rapidjson::Document json;
  json.Parse(req.payload.c_str());
  if(json.HasParseError()) {
    return aws::lambda_runtime::invocation_response::failure("Invalid JSON", "application/json");
  }

  // HTTP trigger with API Gateway sends payload as a serialized JSON
  // stored under key 'body' in the main JSON
  // The SDK trigger converts everything for us
  if (json.HasMember("body") && json["body"].IsString()) {
    rapidjson::Document body_doc;
    body_doc.Parse(json["body"].GetString());
    if(body_doc.HasParseError()) {
      return aws::lambda_runtime::invocation_response::failure("Invalid JSON", "application/json");
    }

    json = std::move(body_doc);
  }

  const auto begin = std::chrono::system_clock::now();
  auto ret = function(json);
  const auto end = std::chrono::system_clock::now();

  auto b = std::chrono::duration_cast<std::chrono::microseconds>(begin.time_since_epoch()).count() / 1000.0 / 1000.0;
  auto e = std::chrono::duration_cast<std::chrono::microseconds>(end.time_since_epoch()).count() / 1000.0 / 1000.0;

  rapidjson::Document body;
  body.SetObject();
  auto& alloc = body.GetAllocator();

  body.AddMember("result", ret, alloc);
  body.AddMember("begin", b, alloc);
  body.AddMember("end", e, alloc);
  body.AddMember("results_time", e - b, alloc);
  body.AddMember("request_id", rapidjson::Value(req.request_id.c_str(), alloc), alloc);
  body.AddMember("is_cold", cold_execution, alloc);
  body.AddMember("container_id", rapidjson::Value(container_id.c_str(), alloc), alloc);
  body.AddMember("cold_start_var", rapidjson::Value(cold_start_var.c_str(), alloc), alloc);

  // Switch cold execution after the first one.
  if (cold_execution)
    cold_execution = false;

  rapidjson::Document final_result;
  final_result.SetObject();
  final_result.AddMember("body", body, final_result.GetAllocator());

  rapidjson::StringBuffer buffer;
  rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
  final_result.Accept(writer);

  return aws::lambda_runtime::invocation_response::success(buffer.GetString(), "application/json");
}

int main() {
#ifdef SEBS_USE_AWS_SDK
  Aws::SDKOptions options;
  Aws::InitAPI(options);
#endif

  const char *cold_var = std::getenv("cold_start");
  if (cold_var)
    cold_start_var = cold_var;
  container_id = boost::uuids::to_string(boost::uuids::random_generator()());

  aws::lambda_runtime::run_handler(handler);

#ifdef SEBS_USE_AWS_SDK
  Aws::ShutdownAPI(options);
#endif
  return 0;
}
