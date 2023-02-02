
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
#include "key-value.hpp"
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
  KeyValue channel_client;

  auto bucket = json.GetString("bucket");
  auto key = json.GetString("key");
  auto role = json.GetString("role"); // producer or consumer
  auto size = json.GetInteger("size");
  auto invoc = json.GetObject("invocations");
  int reps = invoc.GetInteger("invocations");
  int iteration = invoc.GetInteger("iteration");
  int warmup_reps = invoc.GetInteger("warmup");
  bool with_backoff = invoc.GetBool("with_backoff");
  int offset = invoc.GetInteger("offset");
  std::cout << "Invoked handler for role " << role << " with file size " << size
    << " and " << reps << " messages per lambda " << std::endl;

  unsigned char* pBuf = new unsigned char[size];
  memset(pBuf, 'A', sizeof(unsigned char)*size);

  std::string data_key = client.key_join({key, "messages"});
  std::string results_key = client.key_join({key, "results"});

  std::vector<uint64_t> times;
  std::vector<uint64_t> retries_times;
  std::vector<double> read_capacity_units;
  std::vector<double> write_capacity_units;

  int retries = 0;
  double read_units = 0;
  double write_units = 0;

  if (role == "producer") {

    for(int i = 0; i < warmup_reps; ++i) {

      std::string prefix = std::to_string(size) + "_" + std::to_string(i + offset);
      std::string new_key = client.key_join({data_key, prefix});
      std::string new_key_response = client.key_join({data_key, prefix + "_response"});

      channel_client.upload_file(bucket, new_key, write_units, size, pBuf);
      int ret = channel_client.download_file(bucket, new_key_response, retries, read_units, with_backoff);

      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }

    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      std::string prefix = std::to_string(size) + "_" + std::to_string(i + offset);
      std::string new_key = client.key_join({data_key, prefix});
      std::string new_key_response = client.key_join({data_key, prefix + "_response"});

      auto beg = timeSinceEpochMillisec();
      channel_client.upload_file(bucket, new_key, write_units, size, pBuf);
      int ret = channel_client.download_file(bucket, new_key_response, retries, read_units, with_backoff);
      auto end = timeSinceEpochMillisec();

      times.push_back(end - beg);
      retries_times.push_back(retries);
      read_capacity_units.push_back(read_units);
      write_capacity_units.push_back(write_units);

      if(ret == 0) {
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

    {
      auto data = to_string(retries_times);
      std::string new_key = client.key_join({results_key, "producer_retries_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

    {
      auto data = to_string(write_capacity_units);
      std::string new_key = client.key_join({results_key, "producer_write_units_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

    {
      auto data = to_string(read_capacity_units);
      std::string new_key = client.key_join({results_key, "producer_read_units_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

  } else if (role == "consumer") {

    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    for(int i = 0; i < warmup_reps; ++i) {

      std::string prefix = std::to_string(size) + "_" + std::to_string(i + offset);
      std::string new_key = client.key_join({data_key, prefix});
      std::string new_key_response = client.key_join({data_key, prefix + "_response"});

      int ret = channel_client.download_file(bucket, new_key, retries, read_units, with_backoff);
      channel_client.upload_file(bucket, new_key_response, write_units, size, pBuf);

      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }

    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      std::string prefix = std::to_string(size) + "_" + std::to_string(i + offset);
      std::string new_key = client.key_join({data_key, prefix});
      std::string new_key_response = client.key_join({data_key, prefix + "_response"});

      int ret = channel_client.download_file(bucket, new_key, retries, read_units, with_backoff);
      channel_client.upload_file(bucket, new_key_response, write_units, size, pBuf);

      retries_times.push_back(retries);
      read_capacity_units.push_back(read_units);
      write_capacity_units.push_back(write_units);

      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }

    } 

    {
      auto data = to_string(retries_times);
      std::string new_key = client.key_join({results_key, "consumer_retries_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

    {
      auto data = to_string(write_capacity_units);
      std::string new_key = client.key_join({results_key, "consumer_write_units_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }

    {
      auto data = to_string(read_capacity_units);
      std::string new_key = client.key_join({results_key, "consumer_read_units_" + std::to_string(size) + "_" + std::to_string(iteration) + ".txt"});
      client.upload_file(bucket, new_key, std::get<1>(data), std::get<0>(data));
      delete[] std::get<0>(data);
    }
  }

  delete[] pBuf;

  Aws::Utils::Json::JsonValue val;
  val.WithObject("result", std::to_string(size));
  return std::make_tuple(val, 0);
}

