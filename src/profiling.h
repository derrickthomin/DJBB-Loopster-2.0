#pragma once
// -------- Preset-load profiling (conversion-review-plan.md Item 3) --------
//
// TEMPORARY measurement scaffolding. The preset "load" spans a reboot:
// presets.cpp::load_preset() writes STARTUP_PRESET + reboots; the loops are
// actually read from flash on the NEXT boot in setup() -> loop_manager
// .initialize() -> load_loops_binary(). So all the per-loop cost is boot-side.
//
// We accumulate micros() per stage during boot and print one report from loop()
// once USB CDC has re-enumerated after the reboot (Serial isn't up yet in
// setup() right after a reboot, so printing there would be lost).
//
// Set PRESET_LOAD_PROFILE to 0 (or delete this include + the PROF_* calls) to
// compile it all out — the macros become no-ops with zero code size cost.

#define PRESET_LOAD_PROFILE 0

#if PRESET_LOAD_PROFILE
#include <Arduino.h>

struct PresetLoadTiming {
    uint32_t startup_preset_us = 0; // settings.load_startup_preset() (read+apply+serialize+flash write)
    uint32_t cleanup_us = 0;        //   cleanup_orphan_loops()
    uint32_t read_presets_us = 0;   //   read_presets_file() (flash read + JSON parse)
    uint32_t apply_us = 0;          //   _apply_preset_json + serialize loops metadata
    uint32_t write_presets_us = 0;  //   write_presets_file() (FLASH WRITE of presets.json)
    uint32_t lm_initialize_us = 0;  // loop_manager.initialize() total
    uint32_t json_parse_us = 0;     //   deserializeJson(loops_to_load_json)
    uint32_t load_binary_us = 0;    //   load_loops_binary() total
    uint32_t loop_read_us = 0;      //     sum of load_loop_from_flash
    uint32_t finalize_us = 0;       //     sum of finalize_loop_load
    uint32_t update_pixels_us = 0;  // loop_manager.update_pad_pixels()
    uint16_t loops_loaded = 0;
    uint32_t total_events = 0;

    // Heap snapshots (bytes). Loops are std::vectors on the heap, so
    // (free_before - free_after) is the RAM this preset's loops consume.
    uint32_t heap_total = 0;
    uint32_t heap_free_before = 0;
    uint32_t heap_free_after = 0;

    void report() {
        Serial.println();
        Serial.println("===== PRESET LOAD PROFILE (Item 3) =====");
        Serial.printf("loops loaded:        %u\n", loops_loaded);
        Serial.printf("total events:        %lu\n", (unsigned long)total_events);
        Serial.println("---- boot-side stages (micros) ----");
        Serial.printf("load_startup_preset: %8lu us\n", (unsigned long)startup_preset_us);
        Serial.printf("  cleanup_orphans:   %8lu us\n", (unsigned long)cleanup_us);
        Serial.printf("  read_presets_file: %8lu us\n", (unsigned long)read_presets_us);
        Serial.printf("  apply+serialize:   %8lu us\n", (unsigned long)apply_us);
        Serial.printf("  write_presets_file:%8lu us  <-- flash write\n", (unsigned long)write_presets_us);
        Serial.printf("lm.initialize total: %8lu us\n", (unsigned long)lm_initialize_us);
        Serial.printf("  json parse:        %8lu us\n", (unsigned long)json_parse_us);
        Serial.printf("  load_loops_binary: %8lu us\n", (unsigned long)load_binary_us);
        Serial.printf("    loop reads:      %8lu us\n", (unsigned long)loop_read_us);
        Serial.printf("    finalize:        %8lu us\n", (unsigned long)finalize_us);
        Serial.printf("update_pad_pixels:   %8lu us\n", (unsigned long)update_pixels_us);
        uint32_t total = startup_preset_us + lm_initialize_us + update_pixels_us;
        Serial.printf("SUM (load-visible):  %8lu us  (%lu ms)\n",
                      (unsigned long)total, (unsigned long)(total / 1000));
        if (loops_loaded > 0) {
            Serial.printf("per-loop avg:        %8lu us\n",
                          (unsigned long)(load_binary_us / loops_loaded));
        }
        Serial.println("---- heap / RAM (bytes) ----");
        uint32_t used_by_load = (heap_free_before >= heap_free_after)
                                    ? (heap_free_before - heap_free_after)
                                    : 0;
        Serial.printf("heap total:          %8lu\n", (unsigned long)heap_total);
        Serial.printf("free before load:    %8lu\n", (unsigned long)heap_free_before);
        Serial.printf("free after load:     %8lu\n", (unsigned long)heap_free_after);
        Serial.printf("used by preset load: %8lu  (%lu KB)\n",
                      (unsigned long)used_by_load, (unsigned long)(used_by_load / 1024));
        if (total_events > 0) {
            Serial.printf("bytes / event:       %8lu\n",
                          (unsigned long)(used_by_load / total_events));
        }
        Serial.println("========================================");
        Serial.flush();
    }
};

extern PresetLoadTiming g_preset_timing;

#define PROF_START(v) uint32_t v = micros()
#define PROF_ADD(field, v) (g_preset_timing.field += (micros() - (v)))
#define PROF_SET(field, val) (g_preset_timing.field = (val))
#else
#define PROF_START(v) ((void)0)
#define PROF_ADD(field, v) ((void)0)
#define PROF_SET(field, val) ((void)0)
#endif
