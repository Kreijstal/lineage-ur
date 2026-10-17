#include "perfetto/public/abi/tracing_session_abi.h"
#include "perfetto/public/producer.h"
#include "perfetto/public/te_category_macros.h"
#include "perfetto/public/te_macros.h"
#include "perfetto/public/track_event.h"
#include "perfetto/public/protos/config/trace_config.pzc.h"
#include "perfetto/public/protos/config/data_source_config.pzc.h"
#include "perfetto/public/protos/config/track_event/track_event_config.pzc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CATEGORIES(C) C(lineage_package, "lineage_package", "Package regression")
PERFETTO_TE_CATEGORIES_DEFINE(CATEGORIES)

struct Trace { unsigned char bytes[1024 * 1024]; size_t length; };

static void read_trace(struct PerfettoTracingSessionImpl *session, const void *bytes,
                       size_t size, bool more, void *user) {
    (void)session;
    (void)more;
    struct Trace *trace = user;
    if (size > sizeof(trace->bytes) - trace->length) abort();
    memcpy(trace->bytes + trace->length, bytes, size);
    trace->length += size;
}

int main(void) {
    struct PerfettoProducerInitArgs args = PERFETTO_PRODUCER_INIT_ARGS_INIT();
    args.backends = PERFETTO_BACKEND_IN_PROCESS;
    PerfettoProducerInit(args);
    PerfettoTeInit();
    PERFETTO_TE_REGISTER_CATEGORIES(CATEGORIES);
    struct PerfettoPbMsgWriter writer;
    struct PerfettoHeapBuffer *heap = PerfettoHeapBufferCreate(&writer.writer);
    struct perfetto_protos_TraceConfig config_message;
    PerfettoPbMsgInit(&config_message.msg, &writer);
    struct perfetto_protos_TraceConfig_BufferConfig buffer;
    perfetto_protos_TraceConfig_begin_buffers(&config_message, &buffer);
    perfetto_protos_TraceConfig_BufferConfig_set_size_kb(&buffer, 64);
    perfetto_protos_TraceConfig_end_buffers(&config_message, &buffer);
    struct perfetto_protos_TraceConfig_DataSource source;
    perfetto_protos_TraceConfig_begin_data_sources(&config_message, &source);
    struct perfetto_protos_DataSourceConfig data_source;
    perfetto_protos_TraceConfig_DataSource_begin_config(&source, &data_source);
    perfetto_protos_DataSourceConfig_set_cstr_name(&data_source, "track_event");
    struct perfetto_protos_TrackEventConfig event_config;
    perfetto_protos_DataSourceConfig_begin_track_event_config(&data_source, &event_config);
    /* Unlike the C++ SDK, the C SDK disables categories unless explicitly enabled. */
    perfetto_protos_TrackEventConfig_set_cstr_enabled_categories(&event_config, "lineage_package");
    perfetto_protos_DataSourceConfig_end_track_event_config(&data_source, &event_config);
    perfetto_protos_TraceConfig_DataSource_end_config(&source, &data_source);
    perfetto_protos_TraceConfig_end_data_sources(&config_message, &source);
    const size_t config_size = PerfettoStreamWriterGetWrittenSize(&writer.writer);
    unsigned char *config = malloc(config_size);
    if (!config) return 6;
    PerfettoHeapBufferCopyInto(heap, &writer.writer, config, config_size);
    PerfettoHeapBufferDestroy(heap, &writer.writer);
    for (int iteration = 0; iteration < 2; ++iteration) {
        struct PerfettoTracingSessionImpl *session = PerfettoTracingSessionInProcessCreate();
        if (!session) return 1;
        PerfettoTracingSessionSetup(session, config, config_size);
        PerfettoTracingSessionStartBlocking(session);
        for (int retry = 0; retry < 5000 && !PERFETTO_ATOMIC_LOAD_EXPLICIT(lineage_package.enabled, PERFETTO_MEMORY_ORDER_RELAXED); ++retry) {
            const struct timespec delay = {0, 1000000};
            nanosleep(&delay, NULL);
        }
        if (!PERFETTO_ATOMIC_LOAD_EXPLICIT(lineage_package.enabled, PERFETTO_MEMORY_ORDER_RELAXED)) {
            fputs("tracing category did not become enabled\n", stderr);
            return 5;
        }
        PERFETTO_TE(lineage_package, PERFETTO_TE_INSTANT("lineage_packaged_c_event"), PERFETTO_TE_FLUSH());
        if (!PerfettoTracingSessionFlushBlocking(session, 5000)) return 2;
        PerfettoTracingSessionStopBlocking(session);
        struct Trace *trace = calloc(1, sizeof(*trace));
        if (!trace) return 3;
        PerfettoTracingSessionReadTraceBlocking(session, read_trace, trace);
        const char marker[] = "lineage_packaged_c_event";
        bool found = false;
        for (size_t i = 0; i + sizeof(marker) - 1 <= trace->length; ++i)
            if (!memcmp(trace->bytes + i, marker, sizeof(marker) - 1)) found = true;
        free(trace);
        PerfettoTracingSessionDestroy(session);
        if (!found) { fputs("recorded trace lacks the emitted event\n", stderr); return 4; }
    }
    free(config);
    puts("pass: two in-process C tracing sessions contain the emitted event");
    return 0;
}
