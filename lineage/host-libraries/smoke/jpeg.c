#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jpeglib.h>

static int roundtrip(int arithmetic) {
    unsigned char pixels[16 * 16 * 3], decoded[sizeof pixels];
    for (int y = 0; y < 16; ++y) for (int x = 0; x < 16; ++x) {
        size_t offset = (y * 16 + x) * 3;
        pixels[offset] = x * 12; pixels[offset + 1] = y * 12; pixels[offset + 2] = (x + y) * 6;
    }
    struct jpeg_compress_struct compressor;
    struct jpeg_error_mgr errors;
    compressor.err = jpeg_std_error(&errors);
    jpeg_create_compress(&compressor);
    unsigned char *encoded = NULL;
    unsigned long size = 0;
    jpeg_mem_dest(&compressor, &encoded, &size);
    compressor.image_width = 16; compressor.image_height = 16;
    compressor.input_components = 3; compressor.in_color_space = JCS_RGB;
    jpeg_set_defaults(&compressor); jpeg_set_quality(&compressor, 95, TRUE);
    compressor.arith_code = arithmetic;
    jpeg_start_compress(&compressor, TRUE);
    while (compressor.next_scanline < compressor.image_height) {
        JSAMPROW row = pixels + compressor.next_scanline * 16 * 3;
        if (jpeg_write_scanlines(&compressor, &row, 1) != 1) return 1;
    }
    jpeg_finish_compress(&compressor); jpeg_destroy_compress(&compressor);
    struct jpeg_decompress_struct decompressor;
    decompressor.err = jpeg_std_error(&errors);
    jpeg_create_decompress(&decompressor);
    jpeg_mem_src(&decompressor, encoded, size);
    if (jpeg_read_header(&decompressor, TRUE) != JPEG_HEADER_OK || decompressor.arith_code != arithmetic) return 2;
    if (!jpeg_start_decompress(&decompressor) || decompressor.output_width != 16
        || decompressor.output_height != 16 || decompressor.output_components != 3) return 3;
    while (decompressor.output_scanline < decompressor.output_height) {
        JSAMPROW row = decoded + decompressor.output_scanline * 16 * 3;
        if (jpeg_read_scanlines(&decompressor, &row, 1) != 1) return 4;
    }
    if (!jpeg_finish_decompress(&decompressor)) return 5;
    jpeg_destroy_decompress(&decompressor); free(encoded);
    unsigned long difference = 0;
    for (unsigned i = 0; i < sizeof pixels; ++i) difference += abs((int)pixels[i] - decoded[i]);
    return difference > sizeof pixels * 12 ? 6 : 0;
}
int main(void) {
    int result = roundtrip(0);
    if (result) return result;
    result = roundtrip(1);
    if (result) return result + 10;
    puts("JPEG Huffman/arithmetic encode-decode and pixel-error bound: PASS");
    return 0;
}
