/* Thin bridge to the external Chiaki implementation; inherits its linking terms. */
#include <chiaki/gkcrypt.h>
#include <chiaki/log.h>
#include <stdlib.h>
static ChiakiLog quiet_log = {0};
void *rp_gk_new(unsigned char index, const unsigned char *handshake, const unsigned char *secret) {
    return chiaki_gkcrypt_new(&quiet_log, 0, index, handshake, secret);
}
void rp_gk_free(void *ctx) { chiaki_gkcrypt_free(ctx); }
void *chiaki_aligned_alloc(size_t alignment, size_t size) {
#ifdef _WIN32
    return _aligned_malloc(size, alignment);
#else
    void *p = NULL;
    return posix_memalign(&p, alignment, size) ? NULL : p;
#endif
}
void chiaki_aligned_free(void *p) {
#ifdef _WIN32
    _aligned_free(p);
#else
    free(p);
#endif
}
