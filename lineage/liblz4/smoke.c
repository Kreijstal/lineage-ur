#include <lz4.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    const char input[] = "Lineage UR packaged host library roundtrip";
    char compressed[256];
    char restored[sizeof(input)];
    int size = LZ4_compress_default(input, compressed, sizeof(input), sizeof(compressed));
    if (size <= 0 || LZ4_decompress_safe(compressed, restored, size, sizeof(restored)) != sizeof(input)
            || memcmp(input, restored, sizeof(input)) != 0) {
        return 1;
    }
    puts(LZ4_versionString());
    return 0;
}
