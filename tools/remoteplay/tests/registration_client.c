/* Test driver around unmodified Chiaki-ng client registration. */
#include <chiaki/regist.h>
#include <chiaki/log.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void done(ChiakiRegistEvent *event, void *user)
{
    int *result = user;
    if(event->type == CHIAKI_REGIST_EVENT_TYPE_FINISHED_SUCCESS) {
        ChiakiRegisteredHost *h = event->registered_host;
        /* Deliberately do not print credentials. */
        printf("REGISTERED target=%d name=%s key_type=%u\n", h->target, h->server_nickname, h->rp_key_type);
        *result = 0;
    }
}
int main(int argc, char **argv)
{
    if(argc != 4) return 2;
    ChiakiLog log;
    /* Chiaki INFO logs include decrypted registration hexdumps; keep errors only. */
    chiaki_log_init(&log, CHIAKI_LOG_ERROR, chiaki_log_cb_print, NULL);
    ChiakiRegistInfo info = {0};
    info.target = !strcmp(argv[1], "ps5") ? CHIAKI_TARGET_PS5_1 : CHIAKI_TARGET_PS4_10;
    info.host = argv[2];
    info.pin = strtoul(argv[3], NULL, 10);
    memset(info.psn_account_id, 0x42, sizeof(info.psn_account_id));
    ChiakiRegist regist;
    int result = 1;
    if(chiaki_regist_start(&regist, &log, &info, done, &result) != CHIAKI_ERR_SUCCESS) return 3;
    chiaki_regist_fini(&regist);
    return result;
}
