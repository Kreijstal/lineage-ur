#include <zlib.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    unsigned char input[4096], compressed[8192], decoded[4096];
    for (unsigned i = 0; i < sizeof input; ++i) input[i] = (unsigned char)(i * 17);
    uLongf compressed_size = sizeof compressed, decoded_size = sizeof decoded;
    if (compress2(compressed, &compressed_size, input, sizeof input, 9) != Z_OK) return 1;
    if (uncompress(decoded, &decoded_size, compressed, compressed_size) != Z_OK) return 2;
    if (decoded_size != sizeof input || memcmp(input, decoded, sizeof input)) return 3;
    z_stream compressor = {0}, decompressor = {0};
    if (deflateInit2(&compressor, 6, Z_DEFLATED, 15 + 16, 8, Z_DEFAULT_STRATEGY) != Z_OK) return 4;
    compressor.next_in = input; compressor.avail_in = sizeof input;
    compressor.next_out = compressed; compressor.avail_out = sizeof compressed;
    if (deflate(&compressor, Z_FINISH) != Z_STREAM_END) return 5;
    unsigned long gzip_size = compressor.total_out;
    if (deflateEnd(&compressor) != Z_OK || inflateInit2(&decompressor, 15 + 16) != Z_OK) return 6;
    decompressor.next_in = compressed; decompressor.avail_in = gzip_size;
    decompressor.next_out = decoded; decompressor.avail_out = sizeof decoded;
    if (inflate(&decompressor, Z_FINISH) != Z_STREAM_END || decompressor.total_out != sizeof input) return 7;
    if (memcmp(input, decoded, sizeof input) || inflateEnd(&decompressor) != Z_OK) return 8;
    decoded_size = sizeof decoded;
    if (uncompress(decoded, &decoded_size, (const Bytef *)"invalid", 7) != Z_DATA_ERROR) return 9;
    puts("zlib and gzip roundtrips, invalid input: PASS");
    return 0;
}
