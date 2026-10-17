#include "perfetto/tracing.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <thread>

PERFETTO_DEFINE_CATEGORIES(perfetto::Category("lineage_package"));
PERFETTO_TRACK_EVENT_STATIC_STORAGE();

int main() {
    perfetto::TracingInitArgs args;
    args.backends = perfetto::kInProcessBackend;
    perfetto::Tracing::Initialize(args);
    perfetto::TrackEvent::Register();
    for (int iteration = 0; iteration < 2; ++iteration) {
        perfetto::TraceConfig config;
        config.add_buffers()->set_size_kb(64);
        config.add_data_sources()->mutable_config()->set_name("track_event");
        auto session = perfetto::Tracing::NewTrace(perfetto::kInProcessBackend);
        session->Setup(config);
        session->StartBlocking();
        for (int retry = 0; retry < 5000 && !perfetto::TrackEvent::IsEnabled(); ++retry)
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if (!perfetto::TrackEvent::IsEnabled()) {
            std::fputs("tracing data source did not become enabled\n", stderr);
            return 3;
        }
        TRACE_EVENT_INSTANT("lineage_package", "lineage_packaged_cpp_event");
        perfetto::TrackEvent::Flush();
        if (!session->FlushBlocking(5000)) return 1;
        session->StopBlocking();
        const auto bytes = session->ReadTraceBlocking();
        const char *marker = "lineage_packaged_cpp_event";
        if (std::search(bytes.begin(), bytes.end(), marker, marker + std::strlen(marker)) == bytes.end()) {
            std::fputs("recorded trace lacks the emitted event\n", stderr);
            return 2;
        }
    }
    std::puts("pass: two in-process C++ tracing sessions contain the emitted event");
}
