// Chạy ĐÚNG bộ phát hiện của firmware (detector.cpp + ei_glue.cpp + model Edge Impulse) trên PC.
//
// stdin : lặp lại [int32 N][N x 6 float32]   (mỗi bản ghi 50 Hz, hệ trục SisFall)
// stdout: mỗi lần xét va chạm 1 dòng "peak_index ai_score tilt_deg pre_tilt_deg peak_g fall", hết bản ghi in "END"
// argv  : [trigger_g] [ai_threshold] [min_tilt_deg] [max_pre_tilt_deg] [no-ai]
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "detector.h"
#include "ei_glue.h"

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

int main(int argc, char **argv) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);  // stdin nhị phân: chế độ văn bản sẽ cắt ở 0x1A và đổi \r\n
#endif
    fall::DetectorConfig cfg;
    if (argc > 1) cfg.trigger_g = (float)atof(argv[1]);
    if (argc > 2) cfg.ai_threshold = (float)atof(argv[2]);
    if (argc > 3) cfg.min_tilt_deg = (float)atof(argv[3]);
    if (argc > 4) cfg.max_pre_tilt_deg = (float)atof(argv[4]);
    const bool use_ai = !(argc > 5 && strcmp(argv[5], "no-ai") == 0);

    fall::FallDetector det(cfg, use_ai ? fall::ei_fall_probability : nullptr);
    int32_t n;
    std::vector<float> rec;
    while (fread(&n, sizeof(n), 1, stdin) == 1) {
        rec.resize((size_t)n * fall::kChannels);
        if (fread(rec.data(), sizeof(float), rec.size(), stdin) != rec.size()) return 1;
        det.reset();
        fall::Detection d;
        for (int32_t i = 0; i < n; i++)
            if (det.push(&rec[(size_t)i * fall::kChannels], &d))
                printf("%u %.5f %.2f %.2f %.3f %d\n", d.peak_index, d.ai_score, d.tilt_deg, d.pre_tilt_deg, d.peak_g, d.fall ? 1 : 0);
        printf("END\n");
    }
    return 0;
}
