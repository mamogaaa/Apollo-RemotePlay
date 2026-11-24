/* Narrow ABI around the pinned moonlight-common-c. One connection per process. */
#include <Limelight.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef int (*media_callback)(int kind, const void *data, int size, int metadata);
static media_callback callback;
static int video_setup(int format, int w, int h, int fps, void *ctx, int flags) {
    return format == VIDEO_FORMAT_H264 && w == 1280 && h == 720 && fps == 60 ? 0 : -1;
}
static int video_submit(PDECODE_UNIT unit) {
    if (unit->fullLength <= 0 || unit->fullLength > 280000) return DR_NEED_IDR;
    unsigned char *frame = malloc(unit->fullLength);
    if (!frame) return DR_NEED_IDR;
    size_t offset = 0;
    for (PLENTRY entry = unit->bufferList; entry; entry = entry->next) {
        if (entry->length <= 0 || (size_t)entry->length > (size_t)unit->fullLength - offset) {
            free(frame); return DR_NEED_IDR;
        }
        memcpy(frame + offset, entry->data, entry->length);
        offset += entry->length;
    }
    int result = offset == (size_t)unit->fullLength ? callback(1, frame, offset, unit->frameType == FRAME_TYPE_IDR) : -1;
    free(frame);
    return result == 0 ? DR_OK : DR_NEED_IDR;
}
static int audio_init(int config, const POPUS_MULTISTREAM_CONFIGURATION opus, void *ctx, int flags) {
    if (opus->sampleRate != 48000 || opus->channelCount != 2 || opus->streams != 1 || opus->coupledStreams != 1 ||
        opus->mapping[0] != 0 || opus->mapping[1] != 1) return -1;
    return callback(3, NULL, 0, opus->samplesPerFrame);
}
static void audio_sample(char *data, int length) { callback(2, data, length, 0); }
static void terminated(int error) { callback(4, NULL, 0, error); }
static void failed(int stage, int error) { callback(5, NULL, stage, error); }
int rp_moon_start(const char *address, const char *version, const char *gfe, const char *url,
                  const unsigned char *key, uint32_t key_id, media_callback cb) {
    SERVER_INFORMATION server;
    STREAM_CONFIGURATION config;
    DECODER_RENDERER_CALLBACKS video;
    AUDIO_RENDERER_CALLBACKS audio;
    CONNECTION_LISTENER_CALLBACKS listener;
    callback = cb;
    LiInitializeServerInformation(&server);
    LiInitializeStreamConfiguration(&config);
    LiInitializeVideoCallbacks(&video);
    LiInitializeAudioCallbacks(&audio);
    LiInitializeConnectionCallbacks(&listener);
    server.address = address; server.serverInfoAppVersion = version;
    server.serverInfoGfeVersion = gfe; server.rtspSessionUrl = url;
    server.serverCodecModeSupport = SCM_H264;
    config.width = 1280; config.height = 720; config.fps = 60; config.bitrate = 8000;
    config.packetSize = 1024; config.streamingRemotely = STREAM_CFG_LOCAL;
    config.audioConfiguration = AUDIO_CONFIGURATION_STEREO;
    config.supportedVideoFormats = VIDEO_FORMAT_H264;
    config.clientRefreshRateX100 = 6000;
    config.encryptionFlags = ENCFLG_ALL;
    memcpy(config.remoteInputAesKey, key, 16);
    config.remoteInputAesIv[0] = key_id >> 24; config.remoteInputAesIv[1] = key_id >> 16;
    config.remoteInputAesIv[2] = key_id >> 8; config.remoteInputAesIv[3] = key_id;
    video.setup = video_setup; video.submitDecodeUnit = video_submit;
    video.capabilities = CAPABILITY_DIRECT_SUBMIT;
    audio.init = audio_init; audio.decodeAndPlaySample = audio_sample;
    audio.capabilities = CAPABILITY_SUPPORTS_ARBITRARY_AUDIO_DURATION;
    listener.connectionTerminated = terminated; listener.stageFailed = failed;
    return LiStartConnection(&server, &config, &listener, &video, &audio, NULL, 0, NULL, 0);
}
void rp_moon_stop(void) { LiStopConnection(); callback = NULL; }
void rp_moon_interrupt(void) { LiInterruptConnection(); }
void rp_moon_idr(void) { LiRequestIdrFrame(); }
int rp_moon_input(int buttons, unsigned char lt, unsigned char rt, short lx, short ly, short rx, short ry) {
    return LiSendMultiControllerEvent(0, 1, buttons, lt, rt, lx, ly, rx, ry);
}
