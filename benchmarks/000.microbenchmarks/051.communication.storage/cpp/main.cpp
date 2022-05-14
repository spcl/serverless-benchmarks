
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
#include "utils.hpp"

std::tuple<Aws::Utils::Json::JsonValue, int> function(Aws::Utils::Json::JsonView json)
{
  Storage client = Storage::get_client();

  auto bucket = json.GetString("bucket");
  auto key = json.GetString("key");
  auto role = json.GetString("role"); // producer or consumer
  auto file_size = json.GetInteger("size");
  auto invoc = json.GetObject("invocations");
  int reps = invoc.GetInteger("invocations");
  int offset = invoc.GetInteger("offset");
  int warmup_reps = invoc.GetInteger("warmup");
  bool with_backoff = invoc.GetBool("with_backoff");
  std::cout << "Invoked handler for role " << role << " with file size " << file_size << std::endl;

  char* pBuf = new char[file_size];
  memset(pBuf, 'A', sizeof(char)*file_size);

  std::string data_key = client.key_join({key, "messages"});
  std::string results_key = client.key_join({key, "results"});

  std::vector<uint64_t> times;
  std::vector<uint64_t> retries_times;
  int retries = 0;
  if (role == "producer") {

    for(int i = 0; i < warmup_reps; ++i) {

      std::string new_key = client.key_join({data_key, std::to_string(i + offset)});
      std::string new_key_response = client.key_join({data_key, std::to_string(i + offset) + "_response"});
      client.upload_file(bucket, new_key, file_size, pBuf);
      int ret = client.download_file(bucket, new_key_response, retries, with_backoff);
      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }
    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      std::string new_key = client.key_join({data_key, std::to_string(i + offset)});
      std::string new_key_response = client.key_join({data_key, std::to_string(i + offset) + "_response"});
      auto beg = timeSinceEpochMillisec();
      client.upload_file(bucket, new_key, file_size, pBuf);
      int ret = client.download_file(bucket, new_key_response, retries, with_backoff);
      auto end = timeSinceEpochMillisec();
      times.push_back(end - beg);
      retries_times.push_back(retries);

      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }
    } 

    std::stringstream ss;
    ss << times.size() << '\n';
    for(size_t i = 0; i < times.size(); ++i)
      ss << times[i] << '\n';
    std::stringstream ss2;
    ss2 << retries_times.size() << '\n';
    for(size_t i = 0; i < retries_times.size(); ++i)
      ss2 << retries_times[i] << '\n';

    auto times_str = ss.str();
    char* data = new char[times_str.length()];
    strcpy(data, times_str.c_str());

    auto retries_times_str = ss2.str();
    char* data2 = new char[retries_times_str.length()];
    strcpy(data2, retries_times_str.c_str());

    std::string new_key = client.key_join({results_key, "producer_times_" + std::to_string(reps) + "_" + std::to_string(offset)});
    client.upload_file(bucket, new_key, times_str.length(), data);
    new_key = client.key_join({results_key, "producer_retries_" + std::to_string(reps) + "_" + std::to_string(offset)});
    client.upload_file(bucket, new_key, retries_times_str.length(), data2);

    delete[] data;
    delete[] data2;
  } else if (role == "consumer") {

    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    for(int i = 0; i < warmup_reps; ++i) {

      std::string new_key = client.key_join({data_key, std::to_string(i + offset)});
      std::string new_key_response = client.key_join({data_key, std::to_string(i + offset) + "_response"});
      int ret = client.download_file(bucket, new_key, retries, with_backoff);
      client.upload_file(bucket, new_key_response, file_size, pBuf);
      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }
    } 

    for(int i = warmup_reps; i < reps + warmup_reps; ++i) {

      std::string new_key = client.key_join({data_key, std::to_string(i + offset)});
      std::string new_key_response = client.key_join({data_key, std::to_string(i + offset) + "_response"});
      int ret = client.download_file(bucket, new_key, retries, with_backoff);
      client.upload_file(bucket, new_key_response, file_size, pBuf);
      retries_times.push_back(retries);
      if(ret == 0) {
        std::cerr << "Failed download " << i << '\n';
        break;
      }

    } 

    std::stringstream ss2;
    ss2 << retries_times.size() << '\n';
    for(int i = 0; i < retries_times.size(); ++i)
      ss2 << retries_times[i] << '\n';
    auto retries_times_str = ss2.str();
    char* data = new char[retries_times_str.length()];
    strcpy(data, retries_times_str.c_str());
    std::string new_key = client.key_join({results_key, "consumer_retries_" + std::to_string(reps) + "_" + std::to_string(offset)});
    client.upload_file(bucket, new_key, retries_times_str.length(), data);
    delete[] data;
  }

  delete[] pBuf;

  Aws::Utils::Json::JsonValue val;
  val.WithObject("result", std::to_string(file_size));
  return std::make_tuple(val, 0);
}

