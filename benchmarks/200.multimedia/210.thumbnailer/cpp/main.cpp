
#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>

#include <opencv2/core/core.hpp>
#include <opencv2/opencv.hpp>

#include <turbojpeg.h>

#include <string>
#include <iostream>
#include <vector>

#include "function.hpp"
#include "storage.hpp"
#include "utils.hpp"

bool opencv_initialized = false;


rapidjson::Document function(const rapidjson::Value& request)
{
  auto process_start = timeSinceEpochMicrosec();
  static sebs::Storage client_ = sebs::Storage::get_client();
  auto process_end = timeSinceEpochMicrosec();

  if (!request.HasMember("bucket") || !request["bucket"].IsObject()) {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember("error", "Bucket object is not valid.", error.GetAllocator());
    return error;
  }
  const auto& bucket_obj = request["bucket"];
  std::string bucket_name = bucket_obj["bucket"].GetString();
  std::string input_key_prefix = bucket_obj["input"].GetString();
  std::string output_key_prefix = bucket_obj["output"].GetString();

  std::string image_name = request["object"]["key"].GetString();
  int width = request["object"]["width"].GetInt();
  int height = request["object"]["height"].GetInt();

  std::string body_str;
  uint64_t download_time;
  {
    std::string input_key = input_key_prefix + "/" + image_name;
    auto ans = client_.download_file(bucket_name, input_key);
    body_str = std::get<0>(ans);
    download_time = std::get<1>(ans);

    if (body_str.empty()) {
      rapidjson::Document error;
      error.SetObject();
      error.AddMember(
        "error",
        rapidjson::Value(("Failed to download object from S3: " + input_key).c_str(),
        error.GetAllocator()
      ),
      error.GetAllocator());
      return error;
    }
  }

  std::vector<char> vectordata(body_str.begin(), body_str.end());

  uint64_t computing_time;
  cv::Mat out_image;
  {
    auto start_time = timeSinceEpochMicrosec();
    //thumbnailer(vectordata, width, height, out_image);
    thumbnailer_fast(vectordata, width, height, out_image);
    computing_time = timeSinceEpochMicrosec() - start_time;
  }

  std::vector<unsigned char> out_buffer;
  cv::imencode(".jpg", out_image, out_buffer);

  // Create a unique key name for the output image
  std::string key_name;
  std::string key_name2;
  {
    std::string output_key = output_key_prefix + "/" + image_name;
    std::string name, extension;
    if (output_key.find_last_of('.') != std::string::npos) {
      name = output_key.substr(0, output_key.find_last_of('.'));
      extension = output_key.substr(output_key.find_last_of('.'));
    } else {
      name = output_key;
      extension = "";
    }
    key_name = name + "." +
               boost::uuids::to_string(boost::uuids::random_generator()()) +
               extension;
    key_name2 = name + ".tmp." +
                boost::uuids::to_string(boost::uuids::random_generator()()) +
                extension;
  }

  uint64_t upload_time = client_.upload_random_file(
    bucket_name, key_name, true, reinterpret_cast<char *>(out_buffer.data()),
    out_buffer.size()
  );

  if (upload_time == 0) {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember(
      "error",
      rapidjson::Value(
        ("Failed to upload object to S3: " + key_name).c_str(),
        error.GetAllocator()
      ),
      error.GetAllocator()
    );
    return error;
  }

  rapidjson::Document val;
  val.SetObject();
  auto& alloc = val.GetAllocator();

  rapidjson::Value result(rapidjson::kObjectType);
  result.AddMember("bucket", rapidjson::Value(bucket_name.c_str(), alloc), alloc);
  result.AddMember("key", rapidjson::Value(key_name.c_str(), alloc), alloc);
  val.AddMember("result", result, alloc);

  rapidjson::Value measurements(rapidjson::kObjectType);
  measurements.AddMember("download_time", (int64_t)download_time, alloc);
  measurements.AddMember("upload_time", (int64_t)upload_time, alloc);
  measurements.AddMember("compute_time", (int64_t)computing_time, alloc);
  measurements.AddMember("download_size", (int64_t)vectordata.size(), alloc);
  measurements.AddMember("upload_size", (int64_t)out_buffer.size(), alloc);
  val.AddMember("measurement", measurements, alloc);

  return val;
}
