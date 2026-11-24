/* Drives the unmodified Chiaki session engine. Credentials arrive on stdin. */
#include <chiaki/session.h>
#include <chiaki/log.h>
#include <chiaki/time.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <unistd.h>
#include <arpa/inet.h>
static atomic_int connected, frames, audio_frames, recovered_frames;
static FILE *video, *audio;
static void log_cb(ChiakiLogLevel level, const char *msg, void *user) {
    /* Avoid upstream debug hexdumps and any keys/nonce/session identifiers. */
    if(level == CHIAKI_LOG_ERROR || strstr(msg, "Takion connected") || strstr(msg,"Senkusha completed"))
        fprintf(stderr, "%s\n", msg);
}
static void event(ChiakiEvent *e, void *user) {
    if(e->type == CHIAKI_EVENT_CONNECTED) { atomic_store(&connected, 1); puts("STREAM_CONNECTED"); }
    if(e->type == CHIAKI_EVENT_QUIT) fprintf(stderr, "QUIT reason=%d\n", e->quit.reason);
}
static bool sample(uint8_t *buf, size_t size, int32_t lost, bool recovered, void *user) {
    if(video) fwrite(buf, 1, size, video);
    if(recovered) atomic_fetch_add(&recovered_frames,1);
    atomic_fetch_add(&frames, 1);
    return true;
}
static void audio_header(ChiakiAudioHeader *header, void *user) {
    printf("AUDIO_HEADER channels=%u rate=%u samples=%u\n",header->channels,header->rate,header->frame_size);
}
static void audio_frame(uint8_t *buf, size_t size, void *user) {
    if(buf && audio) { uint16_t n=htons(size); fwrite(&n,2,1,audio); fwrite(buf,1,size,audio); }
    if(buf) atomic_fetch_add(&audio_frames,1);
}
int main(int argc, char **argv) {
    if(argc < 3) return 2;
    ChiakiConnectInfo info = {0};
    info.ps5 = !strcmp(argv[1], "ps5");
    info.host = "127.0.0.1";
    char key[33];
    if(scanf("%15s %32s", info.regist_key, key) != 2 || strlen(key) != 32) return 2;
    for(int i=0;i<16;i++) { unsigned v; if(sscanf(key+2*i,"%2x",&v)!=1) return 2; info.morning[i]=v; }
    chiaki_connect_video_profile_preset(&info.video_profile, CHIAKI_VIDEO_RESOLUTION_PRESET_720p, CHIAKI_VIDEO_FPS_PRESET_60);
    info.video_profile.codec = CHIAKI_CODEC_H264;
    info.packet_loss_max = 0.1;
    ChiakiLog log;
    chiaki_log_init(&log, CHIAKI_LOG_ALL, log_cb, NULL);
    ChiakiSession session;
    if(chiaki_session_init(&session, &info, &log)) return 3;
    chiaki_session_set_event_cb(&session,event,NULL);
    chiaki_session_set_video_sample_cb(&session,sample,NULL);
    ChiakiAudioSink sink = {.header_cb=audio_header,.frame_cb=audio_frame};
    chiaki_session_set_audio_sink(&session,&sink);
    if(argc > 3) {
        video=fopen(argv[3],"wb");
        char filename[1024]; snprintf(filename,sizeof(filename),"%s.opus-packets",argv[3]);
        audio=fopen(filename,"wb");
    }
    if(chiaki_session_start(&session)) return 4;
    int got_ctrl=0;
    int target_frames=argc>4 ? atoi(argv[4]) : 120;
    if(target_frames<120 || target_frames>36000) target_frames=120;
    uint64_t until=chiaki_time_now_monotonic_ms()+15000+(uint64_t)target_frames*1000/60;
    while(chiaki_time_now_monotonic_ms()<until) {
        chiaki_mutex_lock(&session.state_mutex);
        got_ctrl=session.ctrl_session_id_received;
        chiaki_mutex_unlock(&session.state_mutex);
        if(!strcmp(argv[2],"control") && got_ctrl) { usleep(200000); break; }
        if(atomic_load(&connected)) {
            ChiakiControllerState state;
            chiaki_controller_state_set_idle(&state);
            state.left_x=12345;
            if(atomic_load(&frames)<60) state.buttons=CHIAKI_CONTROLLER_BUTTON_CROSS;
            chiaki_session_set_controller_state(&session,&state);
        }
        if(atomic_load(&frames)>=target_frames && atomic_load(&audio_frames)>=100) break;
        usleep(10000);
    }
    chiaki_session_stop(&session);
    chiaki_session_join(&session);
    chiaki_session_fini(&session);
    if(video) fclose(video);
    if(audio) fclose(audio);
    printf("CONTROL=%d CONNECTED=%d FRAMES=%d AUDIO=%d RECOVERED=%d\n",got_ctrl,atomic_load(&connected),atomic_load(&frames),atomic_load(&audio_frames),atomic_load(&recovered_frames));
    return !strcmp(argv[2],"control") ? !got_ctrl : !(atomic_load(&connected) && atomic_load(&frames)>=target_frames && atomic_load(&audio_frames)>=100);
}
