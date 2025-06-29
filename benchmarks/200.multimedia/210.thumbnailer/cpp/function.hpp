
#include <opencv2/opencv.hpp>
#include <opencv2/imgcodecs.hpp>

void thumbnailer(cv::Mat &in, int64_t width, int64_t height, cv::Mat &out)
{
  try
  {
    // Calculate thumbnail size while maintaining aspect ratio
    int orig_width = in.cols;
    int orig_height = in.rows;

    double scale_w = static_cast<double>(width) / orig_width;
    double scale_h = static_cast<double>(height) / orig_height;
    double scale = std::min(scale_w, scale_h); // Use smaller scale to fit within bounds

    int new_width = static_cast<int>(orig_width * scale);
    int new_height = static_cast<int>(orig_height * scale);

    // Resize image (equivalent to PIL's thumbnail method)
    cv::resize(in, out, cv::Size(new_width, new_height), cv::INTER_LINEAR);
  }
  catch (const cv::Exception &e)
  {
    std::cerr << "OpenCV error: " << e.what() << std::endl;
  }
}
