#include "ei_glue.h"

#ifdef FALL_HOST_BUILD
#define USE_EDGE_IMPULSE 1
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"
#else
#include "config.h"
#if USE_EDGE_IMPULSE
#include EI_HEADER
#endif
#endif

#include <string.h>

namespace fall {

#if USE_EDGE_IMPULSE
static_assert(EI_CLASSIFIER_RAW_SAMPLE_COUNT == 100 && EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME == 6,
              "Model phai nhan 100 mau x 6 truc (ax,ay,az,gx,gy,gz) @ 50 Hz");
static_assert(EI_CLASSIFIER_INTERVAL_MS == 20, "Model phai duoc train o 50 Hz");

float ei_fall_probability(const float *window, void *) {
    static int fall_index = -1;
    if (fall_index < 0) {
        for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++)
            if (strcmp(ei_classifier_inferencing_categories[i], "Fall") == 0) fall_index = (int)i;
        if (fall_index < 0) return -1.0f;
    }
    signal_t signal;
    if (numpy::signal_from_buffer(const_cast<float *>(window), EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE, &signal) != 0)
        return -1.0f;
    ei_impulse_result_t result = {};
    if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) return -1.0f;
    return result.classification[fall_index].value;
}

const char *ei_model_name() { return EI_CLASSIFIER_PROJECT_NAME; }
#else
float ei_fall_probability(const float *, void *) { return -1.0f; }
const char *ei_model_name() { return ""; }
#endif

}  // namespace fall
