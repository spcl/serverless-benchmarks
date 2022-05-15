
#include <aws/core/Aws.h>
#include <aws/core/utils/logging/LogLevel.h>
#include <aws/core/utils/logging/ConsoleLogSystem.h>
#include <aws/core/utils/logging/LogMacros.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/core/utils/HashingUtils.h>
#include <aws/core/platform/Environment.h>
#include <aws/s3/S3Client.h>
#include <aws/lambda-runtime/runtime.h>

#include <vector>
#include <thread>
#include <cstdint>
#include <iostream>
#include <tuple>

#include "storage.hpp"
#include "tcp.hpp"
#include "utils.hpp"

template<typename T>
std::tuple<char*, size_t> to_string(const std::vector<T> & data)
{

  std::stringstream ss;
  ss << data.size() << '\n';
  for(int i = 0; i < data.size(); ++i)
    ss << data[i] << '\n';
  auto data_str = ss.str();
  char* string_data = new char[data_str.length() + 1];
  strcpy(string_data, data_str.c_str());

  return std::make_tuple(string_data, data_str.length());
}

std::tuple<Aws::Utils::Json::JsonValue, int> function(Aws::Utils::Json::JsonView json)
{
  Storage client = Storage::get_client();

  auto bucket = json.GetString("bucket");
  auto key = json.GetString("key");
  auto role = json.GetString("role"); // producer or consumer
  auto size = json.GetInteger("size");
  auto invoc = json.GetObject("invocations");
  int reps = invoc.GetInteger("invocations");
  int iteration = invoc.GetInteger("iteration");
  int warmup_reps = invoc.GetInteger("warmup");
  int offset = invoc.GetInteger("offset");
  std::cout << "Invoked handler for role " << role << " with file size " << size
    << " and " << reps << " messages per lambda " << std::endl;

  auto tcp_cfg = json.GetObject("tcpuncher");
  std::string address = tcp_cfg.GetString("address");
  std::string pairing_key = tcp_cfg.GetString("pairing_key");
  int id = tcp_cfg.GetInteger("id");

  char* recv_buffer = new char[size];
  char* pBuf = new char[size];
  memset(pBuf, 'A', sizeof(char)*size);

  TCP channel_client{address, pairing_key};
  if (role == "producer") {
    channel_client.connect_producer(1);
  } else {
    channel_client.connect_consumer(id);
  }

  std::string data_key = client.key_join({key, "messages"});
  std::string results_key = client.key_join({key, "results"});

  std::vector<uint64_t> times;

  if (role == "producer") {

    for(int i = 0; i < warmup_reps; ++i) {

      int upload_ret = channel_client.upload_file(0, size, pBuf);
      int download_ret = channel_client.download_file(0, size, recv_buffer);

      if(upload_ret == 0 || download_ret == 0) {
        std::cerr << "Failed processing " << i << '\n';
        break;
      }


    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      auto beg = timeSinceEpochMillisec();
      int upload_ret = channel_client.upload_file(0, size, pBuf);
      int download_ret = channel_client.download_file(0, size, recv_buffer);
      auto end = timeSinceEpochMillisec();

      times.push_back(end - beg);

      if(upload_ret == 0 || download_ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }

    } 

    {
      auto data = to_string(times);
      std::string new_key = client.key_join({results_key, "producer_times_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

  } else if (role == "consumer") {

    for(int i = 0; i < warmup_reps; ++i) {

      int download_ret = channel_client.download_file(0, size, recv_buffer);
      int upload_ret = channel_client.upload_file(0, size, pBuf);

      if(download_ret == 0 || upload_ret == 0) {
        std::cerr << "Failed processing " << i << '\n';
        break;
      }


    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      int download_ret = channel_client.download_file(0, size, recv_buffer);
      int upload_ret = channel_client.upload_file(0, size, pBuf);

      if(download_ret == 0 || upload_ret == 0) {
        std::cerr << "Failed processing " << i << '\n';
        break;
      }


    } 

  }

  delete[] pBuf;
  delete[] recv_buffer;

  Aws::Utils::Json::JsonValue val;
  val.WithObject("result", std::to_string(size));
  return std::make_tuple(val, 0);
}

