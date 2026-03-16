// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#include <thread>
#include <chrono>

rapidjson::Document function(const rapidjson::Value& json)
{
  int sleep_time = json["sleep"].GetInt();

  std::chrono::seconds timespan(sleep_time);
  std::this_thread::sleep_for(timespan);

  rapidjson::Document val;
  val.SetObject();
  val.AddMember(
    "result",
    rapidjson::Value(
      std::to_string(sleep_time).c_str(),
      val.GetAllocator()
    ),
    val.GetAllocator()
  );
  return val;
}
