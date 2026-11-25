// Direct Remote Play media output. No GameStream client, RTP hop, or audio transcoder.
#include "remoteplay.h"

#include "audio.h"
#include "config.h"
#include "display_device.h"
#include "globals.h"
#include "input.h"
#include "logging.h"
#include "platform/common.h"
#include "process.h"
#include "rtsp.h"
#include "video.h"

#include <array>
#include <atomic>
#include <condition_variable>
#include <filesystem>
#include <moonlight-common-c/src/Input.h>
#include <mutex>
#include <Python.h>
#include <thread>
#include <vector>
#include <winsock2.h>
#include <ws2tcpip.h>

using namespace std::chrono_literals;

namespace remoteplay {
  namespace {
    std::atomic_bool stopping {false};
    std::atomic_bool busy {false};
    std::thread control_thread;
    std::mutex lifecycle;
    using GKNew = void *(*)(unsigned char, const unsigned char *, const unsigned char *);
    using GKFree = void (*)(void *);
    using GKCrypt = int (*)(void *, uint64_t, unsigned char *, size_t);
    using GKMac = int (*)(void *, uint64_t, const unsigned char *, size_t, unsigned char *);
    GKNew gk_new;
    GKFree gk_free;
    GKCrypt gk_crypt;
    GKMac gk_mac;
    HMODULE crypto_module;

    std::filesystem::path root() {
      wchar_t p[32768];
      GetModuleFileNameW(nullptr, p, 32768);
      return std::filesystem::path(p).parent_path();
    }

    struct Context {
      std::mutex media;
      safe::mail_t mail = std::make_shared<safe::mail_raw_t>();
      std::shared_ptr<input::input_t> input;
      std::thread video_thread, audio_thread;
      std::atomic<uint64_t> position {0};
      void *keys = nullptr;
      SOCKET socket = INVALID_SOCKET;
      sockaddr_in peer {};
      bool ps5 = false, sending = false, wait_idr = true, platform_started = false;
      uint16_t frame = 0, video_seq = 0, audio_seq = 0;
      std::vector<uint8_t> header;
      uint64_t frames = 0, audio_packets = 0, send_errors = 0, packetize_us = 0, max_packetize_us = 0;
    };

    Context context;  // Stable identity, never a pointer to a GameStream session.

    void put16(std::vector<uint8_t> &b, size_t p, uint16_t v) {
      b[p] = v >> 8;
      b[p + 1] = v;
    }

    void put32(std::vector<uint8_t> &b, size_t p, uint32_t v) {
      b[p] = v >> 24;
      b[p + 1] = v >> 16;
      b[p + 2] = v >> 8;
      b[p + 3] = v;
    }

    uint8_t multiply(uint8_t a, uint8_t b) {
      uint8_t r = 0;
      while (b) {
        if (b & 1) {
          r ^= a;
        }
        bool high = a & 128;
        a <<= 1;
        if (high) {
          a ^= 0x1d;
        }
        b >>= 1;
      }
      return r;
    }

    auto make_tables() {
      std::array<std::array<uint8_t, 256>, 255> t {};
      for (int j = 0; j < 255; ++j) {
        uint8_t a = j + 1, inv = 1;
        for (int k = 0; k < 254; ++k) {
          inv = multiply(inv, a);
        }
        for (int x = 0; x < 256; ++x) {
          t[j][x] = multiply(inv, x);
        }
      }
      return t;
    }

    const auto tables = make_tables();

    bool send(std::vector<uint8_t> &packet, size_t header) {
      auto pos = context.position.fetch_add(((packet.size() - header + 31) / 16) * 16);
      if (pos > 0xfffff000ULL) {
        return false;  // End before the protocol's 32-bit key position wraps.
      }
      put32(packet, 14, static_cast<uint32_t>(pos));
      if (gk_crypt(context.keys, pos + 16, packet.data() + header, packet.size() - header) || gk_mac(context.keys, pos, packet.data(), packet.size(), packet.data() + 10)) {
        return false;
      }
      int sent = sendto(context.socket, reinterpret_cast<char *>(packet.data()), static_cast<int>(packet.size()), 0, reinterpret_cast<sockaddr *>(&context.peer), sizeof(context.peer));
      if (sent != packet.size()) {
        ++context.send_errors;
        return false;
      }
      return true;
    }

    std::vector<uint8_t> headers(const std::vector<uint8_t> &b) {
      std::vector<uint8_t> out;
      size_t i = 0;
      while (i + 3 < b.size()) {
        size_t start = i;
        while (start + 3 < b.size() && !(b[start] == 0 && b[start + 1] == 0 && (b[start + 2] == 1 || (b[start + 2] == 0 && b[start + 3] == 1)))) {
          ++start;
        }
        if (start + 3 >= b.size()) {
          break;
        }
        size_t nal = start + (b[start + 2] == 1 ? 3 : 4), end = nal + 1;
        while (end + 3 < b.size() && !(b[end] == 0 && b[end + 1] == 0 && (b[end + 2] == 1 || (b[end + 2] == 0 && b[end + 3] == 1)))) {
          ++end;
        }
        if (end + 3 >= b.size()) {
          end = b.size();
        }
        if ((b[nal] & 31) == 7 || (b[nal] & 31) == 8) {
          out.insert(out.end(), {0, 0, 0, 1});
          out.insert(out.end(), b.begin() + nal, b.begin() + end);
        }
        i = end;
      }
      return out;
    }
  }  // namespace

  bool active() {
    return busy.load();
  }

  bool submit_video(void *channel, video::packet_raw_t &packet) {
    if (channel != &context) {
      return false;
    }
    auto started = std::chrono::steady_clock::now();
    std::lock_guard lock(context.media);
    std::vector<uint8_t> frame(packet.data(), packet.data() + packet.data_size());
    if (packet.replacements) {
      for (auto &r : *packet.replacements) {
        if (r.old.empty()) {
          continue;
        }
        auto it = std::search(frame.begin(), frame.end(), r.old.begin(), r.old.end());
        if (it != frame.end()) {
          auto offset = it - frame.begin();
          frame.erase(it, it + r.old.size());
          frame.insert(frame.begin() + offset, r._new.begin(), r._new.end());
        }
      }
    }
    if (packet.is_idr()) {
      context.header = headers(frame);
      context.wait_idr = false;
    }
    if (!context.sending || context.wait_idr) {
      return true;
    }
    size_t count = (frame.size() + 1101) / 1102;
    if (!count || count > 255) {
      context.wait_idr = true;
      context.mail->event<bool>(mail::idr)->raise(true);
      return true;
    }
    std::array<uint8_t, 1104> parity {};
    bool ok = true;
    for (size_t unit = 0; unit <= count; ++unit) {
      size_t length = unit < count ? std::min(size_t(1102), frame.size() - unit * 1102) : 1104;
      std::vector<uint8_t> p(21 + (unit < count ? length + 2 : 1104), 0);
      p[0] = 2;
      put16(p, 1, context.video_seq++);
      put16(p, 3, context.frame);
      put32(p, 5, (unit << 21) | (count << 10) | 1);
      if (unit < count) {
        put16(p, 21, 1102 - length);
        std::copy_n(frame.data() + unit * 1102, length, p.data() + 23);
        for (size_t j = 0; j < length + 2; ++j) {
          parity[j] ^= tables[unit][p[21 + j]];
        }
      } else {
        std::copy(parity.begin(), parity.end(), p.begin() + 21);
      }
      ok = send(p, 21) && ok;
    }
    ++context.frame;
    ++context.frames;
    auto us = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - started).count();
    context.packetize_us += us;
    context.max_packetize_us = std::max(context.max_packetize_us, uint64_t(us));
    if (!ok) {
      context.wait_idr = true;
      context.mail->event<bool>(mail::idr)->raise(true);
    }
    return true;
  }

  bool submit_audio(void *channel, const uint8_t *data, size_t size) {
    if (channel != &context) {
      return false;
    }
    std::lock_guard lock(context.media);
    if (!context.sending) {
      return true;
    }
    size_t h = context.ps5 ? 20 : 19;
    std::vector<uint8_t> p(h + size, 0);
    p[0] = 3;
    p[9] = 5;
    put16(p, 1, context.audio_seq);
    put16(p, 3, context.audio_seq++);
    put32(p, 5, (size << 8) | 1);
    std::copy_n(data, size, p.begin() + h);
    send(p, h);
    ++context.audio_packets;
    return true;
  }
}  // namespace remoteplay

#define RP_EXPORT extern "C" __declspec(dllexport)

RP_EXPORT int rp_direct_stopping() {
  return remoteplay::stopping.load();
}

RP_EXPORT uint64_t rp_direct_reserve(unsigned size) {
  return remoteplay::context.position.fetch_add(((uint64_t(size) + 31) / 16) * 16);
}

RP_EXPORT int rp_direct_configure(uint64_t sock, const char *ip, int port, int ps5, const unsigned char *handshake, const unsigned char *secret, uint64_t position) {
  using namespace remoteplay;
  std::lock_guard guard(lifecycle);
  if (busy.exchange(true)) {
    return -1;
  }
  if (rtsp_stream::session_count()) {
    busy = false;
    return -2;
  }
  if (!crypto_module) {
    crypto_module = LoadLibraryW((root() / L"remoteplay/build/rpcrypt.dll").c_str());
    if (!crypto_module) {
      busy = false;
      return -3;
    }
    gk_new = reinterpret_cast<GKNew>(GetProcAddress(crypto_module, "rp_gk_new"));
    gk_free = reinterpret_cast<GKFree>(GetProcAddress(crypto_module, "rp_gk_free"));
    gk_crypt = reinterpret_cast<GKCrypt>(GetProcAddress(crypto_module, "chiaki_gkcrypt_decrypt"));
    gk_mac = reinterpret_cast<GKMac>(GetProcAddress(crypto_module, "chiaki_gkcrypt_gmac"));
    if (!gk_new || !gk_free || !gk_crypt || !gk_mac) {
      busy = false;
      return -4;
    }
  }
  context.mail = std::make_shared<safe::mail_raw_t>();
  context.position = position;
  context.peer = {};
  context.peer.sin_family = AF_INET;
  context.peer.sin_port = htons(port);
  if (inet_pton(AF_INET, ip, &context.peer.sin_addr) != 1) {
    busy = false;
    return -5;
  }
  context.socket = SOCKET(sock);
  context.ps5 = ps5;
  context.keys = gk_new(3, handshake, secret);
  if (!context.keys) {
    busy = false;
    return -6;
  }
  context.sending = false;
  context.wait_idr = true;
  context.header.clear();
  context.frame = context.video_seq = context.audio_seq = 0;
  context.frames = context.audio_packets = context.send_errors = context.packetize_us = context.max_packetize_us = 0;
  return 0;
}

RP_EXPORT int rp_direct_begin(int appid) {
  using namespace remoteplay;
  std::lock_guard guard(lifecycle);
  if (!busy || context.video_thread.joinable()) {
    return -1;
  }
  int current = proc::proc.running();
  if (current && current != appid) {
    return -2;
  }
  auto launch = std::make_shared<rtsp_stream::launch_session_t>();
  launch->device_name = "Remote Play";
  launch->unique_id = "ab1347ea-1b44-443a-81cd-c1f998ea0001";
  launch->width = 1280;
  launch->height = 720;
  launch->fps = 60000;
  launch->gcmap = 1;
  launch->surround_info = 196610;
  launch->scale_factor = 100;
  launch->enable_sops = true;
  launch->perm = crypto::PERM::_all_inputs;
  if (!current) {
    auto &apps = proc::proc.get_apps();
    auto it = std::find_if(apps.begin(), apps.end(), [appid](auto &app) {
      return app.id == std::to_string(appid);
    });
    if (it == apps.end()) {
      return -3;
    }
    int result = proc::proc.execute(*it, launch);
    if (result) {
      return result;
    }
  } else {
    proc::proc.resume();
    if (!proc::proc.virtual_display) {
      display_device::configure_display(config::video, *launch);
    }
    if (video::probe_encoders()) {
      return -4;
    }
  }
  platf::streaming_will_start();
  context.platform_started = true;
  context.input = input::alloc(context.mail);
  video::config_t vc {};
  vc.width = 1280;
  vc.height = 720;
  vc.framerate = 60;
  vc.encodingFramerate = 60000;
  vc.bitrate = 8000;
  vc.slicesPerFrame = 1;
  vc.numRefFrames = 1;
  vc.encoderCscMode = 2;
  audio::config_t ac {};
  ac.channels = 2;
  ac.packetDuration = 10;
  ac.mask = 3;
  ac.silence_on_timeout = true;
  context.video_thread = std::thread([vc] {
    video::capture(context.mail, vc, &context);
  });
  context.audio_thread = std::thread([ac] {
    audio::capture(context.mail, ac, &context);
  });
  return 0;
}

RP_EXPORT int rp_direct_header(unsigned char *out, int capacity) {
  using namespace remoteplay;
  std::lock_guard guard(context.media);
  if (context.header.size() > capacity) {
    return -1;
  }
  std::copy(context.header.begin(), context.header.end(), out);
  return int(context.header.size());
}

RP_EXPORT void rp_direct_stream() {
  using namespace remoteplay;
  std::lock_guard guard(context.media);
  context.sending = true;
  context.wait_idr = true;
  context.mail->event<bool>(mail::idr)->raise(true);
}

RP_EXPORT void rp_direct_idr() {
  remoteplay::context.mail->event<bool>(mail::idr)->raise(true);
}

RP_EXPORT void rp_direct_input(int buttons, int lt, int rt, int lx, int ly, int rx, int ry) {
  using namespace remoteplay;
  std::lock_guard guard(lifecycle);
  if (!context.input) {
    return;
  }
  NV_MULTI_CONTROLLER_PACKET p {};
  p.header.size = htonl(sizeof(p) - 4);
  p.header.magic = MULTI_CONTROLLER_MAGIC_GEN5;
  p.headerB = MC_HEADER_B;
  p.activeGamepadMask = 1;
  p.midB = MC_MID_B;
  p.buttonFlags = buttons;
  p.buttonFlags2 = buttons >> 16;
  p.leftTrigger = lt;
  p.rightTrigger = rt;
  p.leftStickX = lx;
  p.leftStickY = ly;
  p.rightStickX = rx;
  p.rightStickY = ry;
  p.tailA = MC_TAIL_A;
  p.tailB = MC_TAIL_B;
  auto b = reinterpret_cast<uint8_t *>(&p);
  input::passthrough(context.input, std::vector<uint8_t>(b, b + sizeof(p)), crypto::PERM::_all_inputs);
}

RP_EXPORT void rp_direct_end() {
  using namespace remoteplay;
  std::lock_guard guard(lifecycle);
  if (!busy) {
    return;
  }
  {
    std::lock_guard media(context.media);
    context.sending = false;
  }
  context.mail->event<bool>(mail::shutdown)->raise(true);
  if (context.video_thread.joinable()) {
    context.video_thread.join();
  }
  if (context.audio_thread.joinable()) {
    context.audio_thread.join();
  }
  if (context.input) {
    input::reset(context.input);
    context.input.reset();
  }
  if (context.platform_started) {
    proc::proc.pause();
    if (config::video.dd.config_revert_on_disconnect) {
      display_device::revert_configuration();
    }
    platf::streaming_will_stop();
    context.platform_started = false;
  }
  {
    std::lock_guard media(context.media);
    if (context.keys) {
      gk_free(context.keys);
    }
    context.keys = nullptr;
  }
  BOOST_LOG(info) << "Remote Play native media: frames=" << context.frames << " audio=" << context.audio_packets << " send_errors=" << context.send_errors << " packetize_encrypt_send_us_mean=" << (context.frames ? context.packetize_us / context.frames : 0) << " max=" << context.max_packetize_us;
  busy = false;
}

namespace remoteplay {
  void start() {
    control_thread = std::thread([] {
      auto home = root() / L"remoteplay/python";
      if (!std::filesystem::exists(home)) {
        BOOST_LOG(error) << "Remote Play runtime not installed";
        return;
      }
      PyConfig cfg;
      PyConfig_InitIsolatedConfig(&cfg);
      PyConfig_SetString(&cfg, &cfg.home, home.c_str());
      cfg.write_bytecode = 0;
      cfg.install_signal_handlers = 0;
      cfg.module_search_paths_set = 1;
      for (const auto &path : {home / L"python313.zip", home / L"DLLs", home / L"Lib", home / L"Lib/site-packages"}) {
        PyWideStringList_Append(&cfg.module_search_paths, path.c_str());
      }
      auto result = Py_InitializeFromConfig(&cfg);
      PyConfig_Clear(&cfg);
      if (PyStatus_Exception(result)) {
        BOOST_LOG(error) << "Remote Play Python init failed: " << (result.err_msg ? result.err_msg : "unknown");
        return;
      }
      auto dir = (root() / L"remoteplay").u8string();
      PyObject *path = PySys_GetObject("path");
      PyObject *item = PyUnicode_FromString(reinterpret_cast<const char *>(dir.c_str()));
      PyList_Insert(path, 0, item);
      Py_DECREF(item);
      if (PyRun_SimpleString("import embedded_host; embedded_host.main()")) {
        BOOST_LOG(error) << "Remote Play control stopped with error";
      }
      Py_FinalizeEx();
    });
  }

  void stop() {
    stopping = true;
    if (control_thread.joinable()) {
      control_thread.join();
    }
    rp_direct_end();
  }
}  // namespace remoteplay

RP_EXPORT const char *rp_direct_data_path() {
  static auto path = (platf::appdata() / "remoteplay").u8string();
  return reinterpret_cast<const char *>(path.c_str());
}

RP_EXPORT int rp_direct_default_app() {
  for (auto &app : proc::proc.get_apps()) {
    if (app.cmd.empty() && !app.virtual_display) {
      return std::stoi(app.id);
    }
  }
  return 0;
}
