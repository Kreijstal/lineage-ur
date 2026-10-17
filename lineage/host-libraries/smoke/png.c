#include <png.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    const unsigned char pixels[16] = {255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,128};
    unsigned char decoded[sizeof pixels];
    png_image image = {.version = PNG_IMAGE_VERSION, .width = 2, .height = 2, .format = PNG_FORMAT_RGBA};
    png_alloc_size_t size = 0;
    if (!png_image_write_to_memory(&image, NULL, &size, 0, pixels, 0, NULL)) return 1;
    void *encoded = malloc(size);
    if (!encoded || !png_image_write_to_memory(&image, encoded, &size, 0, pixels, 0, NULL)) return 2;
    png_image read = {.version = PNG_IMAGE_VERSION};
    if (!png_image_begin_read_from_memory(&read, encoded, size)) return 3;
    read.format = PNG_FORMAT_RGBA;
    if (read.width != 2 || read.height != 2 || !png_image_finish_read(&read, NULL, decoded, 0, NULL)) return 4;
    if (memcmp(decoded, pixels, sizeof pixels)) return 5;
    png_image_free(&read); free(encoded);
    png_image invalid = {.version = PNG_IMAGE_VERSION};
    if (png_image_begin_read_from_memory(&invalid, "not a PNG", 9)) return 6;
    png_image_free(&invalid);
    puts("PNG RGBA encode/decode, alpha and invalid input: PASS");
    return 0;
}
