// Chạy model Edge Impulse trên PC bằng đúng mã C++ (DSP + NN int8) dùng trên ESP32.
//
// Chế độ văn bản (mặc định): mỗi dòng stdin = 600 số (100 mẫu x ax,ay,az,gx,gy,gz)
//                           -> in "<P(Fall)> <DSP us> <NN us>"
// Chế độ nhị phân (--binary): stdin là các khối 600 float32 -> stdout là các float32 P(Fall)
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "edge-impulse-sdk/classifier/ei_run_classifier.h"

static int fall_index() {
    for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++)
        if (strcmp(ei_classifier_inferencing_categories[i], "Fall") == 0) return (int)i;
    return 0;
}

static bool classify(std::vector<float> &buf, ei_impulse_result_t &r) {
    signal_t signal;
    numpy::signal_from_buffer(buf.data(), buf.size(), &signal);
    r = {};
    return run_classifier(&signal, &r, false) == EI_IMPULSE_OK;
}

int main(int argc, char **argv) {
    const int fall = fall_index();
    std::vector<float> buf(EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE);
    ei_impulse_result_t r;

    if (argc > 1 && strcmp(argv[1], "--binary") == 0) {
        while (fread(buf.data(), sizeof(float), buf.size(), stdin) == buf.size()) {
            float p = classify(buf, r) ? r.classification[fall].value : -1.0f;
            fwrite(&p, sizeof(float), 1, stdout);
        }
        return 0;
    }

    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream ss(line);
        size_t n = 0;
        while (n < buf.size() && ss >> buf[n]) n++;
        if (n != buf.size()) { printf("ERR expected %zu values got %zu\n", buf.size(), n); continue; }
        if (!classify(buf, r)) { printf("ERR classifier\n"); continue; }
        printf("%.6f %d %d\n", r.classification[fall].value, (int)r.timing.dsp_us, (int)r.timing.classification_us);
    }
}
