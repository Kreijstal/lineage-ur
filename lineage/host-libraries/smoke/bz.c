#include <bzlib.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    char input[4096], compressed[8192], decoded[4096];
    for (unsigned i = 0; i < sizeof input; ++i) input[i] = (char)(i * 17);
    unsigned compressed_size = sizeof compressed, decoded_size = sizeof decoded;
    if (BZ2_bzBuffToBuffCompress(compressed, &compressed_size, input, sizeof input, 9, 0, 30) != BZ_OK) return 1;
    if (BZ2_bzBuffToBuffDecompress(decoded, &decoded_size, compressed, compressed_size, 0, 0) != BZ_OK) return 2;
    if (decoded_size != sizeof input || memcmp(input, decoded, sizeof input)) return 3;
    decoded_size = sizeof decoded;
    char invalid[] = "not a bzip2 stream";
    if (BZ2_bzBuffToBuffDecompress(decoded, &decoded_size, invalid, sizeof invalid, 0, 0) != BZ_DATA_ERROR_MAGIC) return 4;
    puts("bzip2 roundtrip and invalid input: PASS");
    return 0;
}
