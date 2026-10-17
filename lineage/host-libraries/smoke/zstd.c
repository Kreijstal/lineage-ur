#include <zstd.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    unsigned char input[4096], compressed[8192], decoded[4096];
    for (unsigned i = 0; i < sizeof input; ++i) input[i] = (unsigned char)(i * 17);
    size_t size = ZSTD_compress(compressed, sizeof compressed, input, sizeof input, 9);
    if (ZSTD_isError(size)) return 1;
    if (ZSTD_decompress(decoded, sizeof decoded, compressed, size) != sizeof input || memcmp(input, decoded, sizeof input)) return 2;
    ZSTD_CCtx *compressor = ZSTD_createCCtx(); ZSTD_DCtx *decompressor = ZSTD_createDCtx();
    if (!compressor || !decompressor) return 3;
    size = ZSTD_compress_usingDict(compressor, compressed, sizeof compressed, input, sizeof input, input, 512, 6);
    if (ZSTD_isError(size)) return 4;
    if (ZSTD_decompress_usingDict(decompressor, decoded, sizeof decoded, compressed, size, input, 512) != sizeof input || memcmp(input, decoded, sizeof input)) return 5;
    ZSTD_freeCCtx(compressor); ZSTD_freeDCtx(decompressor);
    if (!ZSTD_isError(ZSTD_decompress(decoded, sizeof decoded, "invalid", 7))) return 6;
    puts("Zstandard normal/dictionary roundtrips and invalid input: PASS");
    return 0;
}
