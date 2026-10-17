#include "include/core/SkBitmap.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkPaint.h"
#include "include/core/SkRect.h"

#include <cstdio>

int main() {
    SkBitmap bitmap;
    bitmap.allocN32Pixels(16, 16);
    SkCanvas canvas(bitmap);
    canvas.clear(SK_ColorBLUE);
    SkPaint paint;
    paint.setColor(SK_ColorRED);
    canvas.save();
    canvas.clipRect(SkRect::MakeXYWH(4, 4, 8, 8));
    canvas.drawRect(SkRect::MakeWH(16, 16), paint);
    canvas.restore();
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x) {
            const auto expected = x >= 4 && x < 12 && y >= 4 && y < 12 ? SK_ColorRED : SK_ColorBLUE;
            if (bitmap.getColor(x, y) != expected) {
                std::fprintf(stderr, "raster mismatch at %d,%d\n", x, y);
                return 1;
            }
        }
    }
    std::puts("pass: CPU raster drawing, clipping and all 256 pixels");
}
