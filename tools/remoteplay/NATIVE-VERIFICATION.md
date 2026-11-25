# Native Windows verification, 2026-11-25

Apollo now sends encoded H.264 and 10 ms Opus directly over Remote Play.
Capture/encoding, FEC, encryption and UDP output run in the Apollo process;
embedded Python handles registration and session negotiation. Controller input
goes directly to Apollo input. There is no GameStream/Moonlight intermediary
and no Opus transcoding.

## Real end-to-end checks

The unchanged official Chiaki-ng GUI 1.10.1 connected and reconnected to both
PS4 and PS5 profiles. Screenshots showed the live Windows desktop and application
clock. Cross and D-pad reached a separate application through Windows XInput;
button releases and disconnect were observed. The desktop probe plays sound
through Windows and reads XInput; it does not feed media into the server.

Audio recorded from Chiaki's physical Mi Monitor output, separate from Apollo's
Steam Streaming Speakers capture endpoint:

| Final GUI reconnect | Normalized RMS | Peak |
| --- | ---: | ---: |
| PS4 | 0.04922 | 0.09998 |
| PS5 | 0.04945 | 0.10071 |

This verifies client playback output, not subjective speaker quality.

Final unchanged-engine sessions against the running native Apollo:

| Profile / attempt | Decoded video frames | Opus packets | PCM RMS |
| --- | ---: | ---: | ---: |
| PS4 / 1 | 299 | 1298 | 1440.4 |
| PS4 / 2 | 299 | 1367 | 1538.6 |
| PS5 / 1 | 299 | 1399 | 1475.6 |
| PS5 / 2 | 299 | 1362 | 1460.0 |

The callback counted 300 video units including stream headers. Strict FFmpeg
decoding passed. Disconnect released the controller and capture/encoder threads.
Native send errors: zero. Silent-desktop regression: 119 decoded frames and 633
audio packets, with no application playing audio.

The profile negotiates 720p, up to 60 fps, 8 Mbps H.264 SDR. Desktop capture is
change-driven; these tests do not measure sustained 60 fps gameplay.

## Overhead

Measured from entry to the native video sender, including mutex wait, through
FEC, encryption and the final sendto. Four final sessions had means of 57, 51,
51 and 52 microseconds; maxima of 241, 142, 182 and 166 microseconds.
These are sender costs, **not input-to-photon or total end-to-end latency**.
Apollo adjusts some capture timestamps into the future, so those timestamps
are not used to claim a latency bound.

Remote Play UDP sockets belonged to sunshine.exe. No established GameStream
connections to ports 47984/47989/48010 were present during inspection.

## Runtime checks

- Release and web builds completed; 17 regression unit tests passed.
- Unauthenticated management API returns 401. Authenticated PIN generation
  produces eight digits and a five-minute lifetime. Pairing is closed at startup.
- Authenticated Remote Play page returns 200. Visual browser validation of this
  new management page remains outstanding.
- Graceful standalone exit completed without forced timeout.
- NSIS package generated and extracted. Its stripped executable starts with
  PATH containing only Windows directories; bundled Python, crypto and protocol
  modules load and the listener becomes ready. No external Python/MSYS2 needed.
- No client state, certificates or pairing keys are included in the package.

## Deployment and limitations

Automatic execution approval rejected system replacement with only the reason
`blocked by policy`. Old Apollo remains installed as ApolloService, Running,
Automatic, with ensure_only_display unchanged. The native fork was tested
separately and is **not installed globally**. Installer migration, fork service
startup and reboot persistence remain unverified. The package is a prerelease.

Physical Sony consoles and Sony clients, WAN/PSN, HDR, haptics, motion, touch,
long gameplay soak, native FEC on a lossy network and input-to-photon latency
remain unverified or unsupported. One active client; fixed 720p SDR; one FEC
block per frame; reconnect required before 32-bit key-position wrap. Fork
binaries are not Authenticode-signed.

## Reproduce

Use build_direct.ps1, then start the real native Apollo. Run the desktop probe
separately and connect unchanged Chiaki with Local and Remote H.264 settings.
Same-PC tests require separate audio sinks and controller feedback isolation.
tests/native_integration.py tests an already-running host and starts no fixture
or bridge. Local captures and logs are excluded from Git because they can
contain desktop content.
