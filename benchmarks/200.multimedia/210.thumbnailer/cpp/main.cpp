
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>

#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_io.hpp>

#include <iostream>
#include <vector>

#include "function.hpp"
#include "storage.hpp"
#include "utils.hpp"

Aws::Utils::Json::JsonValue function(Aws::Utils::Json::JsonView request)
{
  Storage client_ = Storage::get_client();

  auto bucket_obj = request.GetObject("bucket");
  if (!bucket_obj.IsObject())
  {
    Aws::Utils::Json::JsonValue error;
    error.WithString("error", "Bucket object is not valid.");
    return error;
  }
  auto bucket_name = bucket_obj.GetString("bucket");
  auto input_key_prefix = bucket_obj.GetString("input");
  auto output_key_prefix = bucket_obj.GetString("output");

  auto image_name = request.GetObject("object").GetString("key");
  auto width = request.GetObject("object").GetInteger("width");
  auto height = request.GetObject("object").GetInteger("height");

  std::string body_str;
  uint64_t download_time;
  {
    std::string input_key = input_key_prefix + "/" + image_name;
    auto ans = client_.download_file(bucket_name, input_key);
    body_str = std::get<0>(ans);
    download_time = std::get<1>(ans);

    if (body_str.empty())
    {
      Aws::Utils::Json::JsonValue error;
      error.WithString("error", "Failed to download object from S3: " + input_key);
      return error;
    }
  }

  std::vector<char> vectordata(body_str.begin(), body_str.end());
  cv::Mat image = imdecode(cv::Mat(vectordata), 1);

  // Apply the thumbnailer function and measure the computing time
  cv::Mat image2;
  uint64_t computing_time;
  {
    auto start_time = timeSinceEpochMicrosec();
    thumbnailer(image, width, height, image2);
    computing_time = timeSinceEpochMicrosec() - start_time;
  }

  std::vector<unsigned char> out_buffer;
  cv::imencode(".jpg", image2, out_buffer);

  // Create a unique key name for the output image
  std::string key_name;
  {
    std::string output_key = output_key_prefix + "/" + image_name;
    std::string name, extension;
    if (output_key.find_last_of('.') != std::string::npos)
    {
      name = output_key.substr(0, output_key.find_last_of('.'));
      extension = output_key.substr(output_key.find_last_of('.'));
    }
    else
    {
      name = output_key;
      extension = "";
    }
    key_name = name + "."
        + boost::uuids::to_string(boost::uuids::random_generator()())
        + extension;
  }

  // Upload the resulting image to S3
  // If the upload fails, return an error
  Aws::String upload_data(out_buffer.begin(), out_buffer.end());

  uint64_t upload_time = client_.upload_random_file(
      bucket_name, key_name, true,
      reinterpret_cast<char *>(out_buffer.data()), out_buffer.size());

  if (upload_time == 0)
  {
    Aws::Utils::Json::JsonValue error;
    error.WithString("error", "Failed to upload object to S3: " + key_name);
    return error;
  }


  Aws::Utils::Json::JsonValue val;
  Aws::Utils::Json::JsonValue result;
  Aws::Utils::Json::JsonValue measurements;

  result.WithString("bucket", bucket_name);
  result.WithString("key", key_name);
  val.WithObject("result", result);

  measurements.WithInteger("download_time", download_time);
  measurements.WithInteger("upload_time", upload_time);
  measurements.WithInteger("compute_time", computing_time);
  measurements.WithInteger("download_size", vectordata.size());
  measurements.WithInteger("upload_size", out_buffer.size());
  val.WithObject("measurements", measurements);
  return val;
}