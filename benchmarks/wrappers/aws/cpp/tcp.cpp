
#include <string>
#include <iostream>

#include <errno.h>
#include <unistd.h>

#include <tcpunch.h>

#include "tcp.hpp"
#include "utils.hpp"

void TCP::connect_producer(int num_consumers)
{
  _sockets.resize(num_consumers);
  for (int i = 0; i < num_consumers; i++) {
      std::string prod_pairing_key = _pairing_key + "_" + std::to_string(i);
      std::cerr << "Producer begins pairing " << prod_pairing_key << '\n';
      _sockets[i] = pair(prod_pairing_key, _address);
  }
  std::cerr << "Succesful pairing on all consumers" << '\n';
}

void TCP::connect_consumer(int id)
{
  _sockets.resize(1);
  std::string prod_pairing_key = _pairing_key + "_" + std::to_string(id);
  std::cerr << "Begin pairing " << prod_pairing_key << '\n';
  _sockets[0] = pair(prod_pairing_key, _address);
  std::cerr << "Succesful pairing " << prod_pairing_key << '\n';

  struct timeval timeout;      
  timeout.tv_sec = 10;
  timeout.tv_usec = 0;

  if(setsockopt(_sockets[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) < 0)
    std::cerr << "Couldn't set timeout!" << std::endl;

  if(setsockopt(_sockets[0], SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout) < 0)
    std::cerr << "Couldn't set timeout!" << std::endl;
}

TCP::~TCP()
{
  for(int socket : _sockets)
    close(socket);
}

uint64_t TCP::download_file(int id, int size, char* recv_buffer)
{
  uint64_t bef = timeSinceEpochMillisec();
  bool failure = false;
  
  int recv_bytes = 0;
  while (recv_bytes < size) {
      int n = recv(_sockets[id], recv_buffer + recv_bytes, size - recv_bytes, 0);
      if (n > 0) {
          recv_bytes += n;
      }
      if (n == -1) {
          std::cout << "Error: " << errno << std::endl;
          failure = true;
          break;
      }
  }
  uint64_t finishedTime = timeSinceEpochMillisec();

  return failure ? 0 : finishedTime - bef;
}

uint64_t TCP::upload_file(int id, int size, char* pBuf)
{
  uint64_t bef = timeSinceEpochMillisec();
  bool failure = false;

  int sent_bytes = 0;
  while (sent_bytes < size) {
    int bytes = send(_sockets[id], pBuf + sent_bytes, size - sent_bytes, 0);
    sent_bytes += bytes;
    if (bytes == -1) {
      failure = true;
      std::cerr << "Failed sending! " << errno << std::endl;
      break;
    }
  }
  uint64_t finishedTime = timeSinceEpochMillisec();

  return failure ? 0 : finishedTime - bef;
}

