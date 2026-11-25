#pragma once
#include <cstddef>
#include <cstdint>

namespace video {
  struct packet_raw_t;
}

namespace remoteplay {
  bool submit_video(void *channel, video::packet_raw_t &packet);
  bool submit_audio(void *channel, const uint8_t *data, size_t size);
  bool active();
  void start();
  void stop();
}  // namespace remoteplay
