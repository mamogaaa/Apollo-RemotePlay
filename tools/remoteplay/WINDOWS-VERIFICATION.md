# Real Windows verification — 2026-11-25

Host: DESKTOP-RBF3MM2, Windows 11 Pro 26100. Apollo v0.3.0 service.
Client: official portable Chiaki-ng 1.10.1, unchanged executable, OpenGL,
profile ApolloRemotePlayLab. Adapter native DLLs built locally with UCRT64.
Source: Apollo Desktop app 881448767, real GameStream capture.

| GUI check | PS4 | PS5 |
|---|---|---|
| PIN registration | passed | passed |
| Animated Windows desktop | passed | passed |
| Cross -> real XInput app counter | 5 -> 6 | 7 -> 8 |
| D-pad -> app movement + release | passed | passed |
| Physical audio endpoint peak | 0.0899 | 0.0917 |
| Disconnect / reconnect | passed | passed |
| Cross after reconnect | 6 -> 7 | 8 -> 9 |
| Audio peak after reconnect | 0.0981 | 0.0888 |

Audio sessions were unmuted at both application and endpoint, volume 1.0.
Source audio played on Steam Streaming Speakers; Chiaki rendered on Mi Monitor
(NVIDIA High Definition Audio). A three-second WASAPI loopback capture of the
Chiaki output endpoint measured RMS 0.0602 / peak 0.0963. Acoustic playback quality
was not judged by a human listener. The recording verifies rendered output.

The desktop probe is an ordinary Tk/XInput/winsound Windows application. It does
not inject data into the adapter. The adapter was launched with --apollo-state
and --apollo-app throughout these checks. Closing the probe stopped system sound;
the live PS5 desktop continued for more than 12 seconds, with heartbeats intact.

Local ignored evidence: work/live-host2.log; work/ps4-reconnect.png;
work/ps5-success.png; work/ps5-reconnect.png; work/chiaki-ps5-output.wav;
tools/remoteplay/build/desktop-probe-events.jsonl; work/final-unit.log.

Separate actual-source engine test: work/apollo-live-tone2.log, both profiles twice,
119 decoded frames per connection, 286–364 audio packets, PCM RMS 1957–1972.
Final unit suite: 17 passed. Prior registration, fixture and loss/reconnect tests
passed. Neither fixtures nor synthetic adapter media establish the GUI result.

Limits: one stream, H.264 SDR 720p60. Sony console/official Remote Play client
compatibility remains unverified. No claim of PS4/PS5 hardware success.
