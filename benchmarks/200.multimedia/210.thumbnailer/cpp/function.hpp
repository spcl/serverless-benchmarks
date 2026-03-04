
#include <opencv2/opencv.hpp>
#include <opencv2/imgcodecs.hpp>

#include <turbojpeg.h>

void thumbnailer(const std::vector<char>& jpeg_data, int64_t width, int64_t height, cv::Mat &out)
{
  try
  {
    // auto t1 = std::chrono::high_resolution_clock::now();
    cv::Mat in = cv::imdecode(jpeg_data, cv::IMREAD_COLOR);
    // auto t2 = std::chrono::high_resolution_clock::now();

    //std::cout
    //    << "Slow decode to "
    //    << std::chrono::duration_cast<std::chrono::milliseconds>(t2 - t1).count()
    //  << "ms\n";

    // Calculate thumbnail size while maintaining aspect ratio
    int orig_width = in.cols;
    int orig_height = in.rows;

    double scale_w = static_cast<double>(width) / orig_width;
    double scale_h = static_cast<double>(height) / orig_height;
    double scale = std::min(scale_w, scale_h); // Use smaller scale to fit within bounds

    int new_width = static_cast<int>(orig_width * scale);
    int new_height = static_cast<int>(orig_height * scale);

    // Resize image (equivalent to PIL's thumbnail method)
    cv::resize(in, out, cv::Size(new_width, new_height), 0, 0, cv::INTER_LINEAR);
  }
  catch (const cv::Exception &e)
  {
    std::cerr << "OpenCV error: " << e.what() << std::endl;
  }
}

void thumbnailer_fast(const std::vector<char>& jpeg_data, int target_width, int target_height, cv::Mat &out) 
{
  static tjhandle tj_handle = tjInitDecompress();

  int orig_width, orig_height, subsamp, colorspace;
  tjDecompressHeader3(
    tj_handle, reinterpret_cast<const unsigned char *>(jpeg_data.data()),
    jpeg_data.size(), &orig_width, &orig_height, &subsamp, &colorspace
  );

  // Calculate scaling factor (1, 2, 4, or 8)
  // Find the largest possible factor that works for our message
  int scale_num = 1, scale_denom = 1;
  for (int denom : {8, 4, 2, 1}) {
    if (orig_width / denom >= target_width &&
        orig_height / denom >= target_height) {
      scale_denom = denom;
      break;
    }
  }

  // libjpeg-turbo supports these exact fractional scales during decode
  tjscalingfactor sf = {scale_num, scale_denom};
  int scaled_width = TJSCALED(orig_width, sf);
  int scaled_height = TJSCALED(orig_height, sf);

  std::vector<unsigned char> buffer(scaled_width * scaled_height * 3);

  //auto t1 = std::chrono::high_resolution_clock::now();

  tjDecompress2(
    tj_handle, reinterpret_cast<const unsigned char *>(jpeg_data.data()),
    jpeg_data.size(), buffer.data(), scaled_width, 0, scaled_height,
    TJPF_BGR, TJFLAG_FASTDCT | TJFLAG_FASTUPSAMPLE
  );

  //auto t2 = std::chrono::high_resolution_clock::now();
  //std::cout
  //    << "Fast decode to " << scaled_width << "x" << scaled_height << ": "
  //    << std::chrono::duration_cast<std::chrono::milliseconds>(t2 - t1).count()
  //    << "ms\n";

  double scale_w = static_cast<double>(target_width) / orig_width;
  double scale_h = static_cast<double>(target_height) / orig_height;
  double scale = std::min(scale_w, scale_h); // Use smaller scale to fit within bounds

  target_width = static_cast<int>(orig_width * scale);
  target_height = static_cast<int>(orig_height * scale);

  cv::Mat temp(scaled_height, scaled_width, CV_8UC3, buffer.data());
  // Final scaling
  if (scaled_width != target_width || scaled_height != target_height) {
    cv::resize(temp, out, cv::Size(target_width, target_height), 0, 0, cv::INTER_LINEAR);
  }
}
