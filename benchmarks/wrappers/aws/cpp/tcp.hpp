
#include <cstdint>
#include <string>
#include <vector>

class TCP
{
  std::string _address;
  std::string _pairing_key;
  std::vector<int> _sockets;
public:

  TCP(std::string hole_puncher_ip, std::string pairing_key):
    _address(hole_puncher_ip),
    _pairing_key(pairing_key)
  {}
  ~TCP();

  void connect_consumer(int id);
  void connect_producer(int consumers);


  uint64_t download_file(int id, int size, char* recv_buffer);

  uint64_t upload_file(int id, int size, char* pBuf);

};

