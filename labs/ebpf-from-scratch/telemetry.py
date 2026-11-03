"""Copyright (c) 2026 Zenable, Inc. Ship agentwatch events as OpenTelemetry log records.

One record per kernel event, with the process, file and network facts as
attributes named after the OpenTelemetry semantic conventions, so a collector
can route them like any other log stream.
"""

from events import Event, Kind
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource

SERVICE_NAME = "agentwatch"


def attributes(event: Event) -> dict[str, str | int]:
    """The event as semantic-convention attributes."""
    attrs: dict[str, str | int] = {
        "process.pid": event.pid,
        "process.parent_pid": event.ppid,
        "process.executable.name": event.comm,
        "process.user.id": event.uid,
        "agentwatch.kind": event.kind.name.lower(),
    }
    if event.kind in (Kind.OPEN, Kind.DENIED):
        attrs["file.path"] = event.detail
    elif event.kind == Kind.EXEC:
        attrs["process.executable.path"] = event.detail
    elif event.kind == Kind.CONNECT:
        host, _, port = event.detail.rpartition(":")
        attrs["network.peer.address"] = host.strip("[]")
        if port.isdigit():
            attrs["network.peer.port"] = int(port)
    return attrs


def severity(event: Event) -> SeverityNumber:
    return SeverityNumber.WARN if event.kind == Kind.DENIED else SeverityNumber.INFO


def provider(exporter: LogRecordExporter) -> LoggerProvider:
    result = LoggerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    result.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(result)
    return result


def otlp_provider(endpoint: str) -> LoggerProvider:
    return provider(OTLPLogExporter(endpoint=f"{endpoint.rstrip('/')}/v1/logs"))


class Emitter:
    def __init__(self, logger_provider: LoggerProvider) -> None:
        self._provider = logger_provider
        self._logger = logger_provider.get_logger(SERVICE_NAME)

    def emit(self, event: Event) -> None:
        self._logger.emit(
            body=f"{event.kind.name.lower()} {event.comm} {event.detail}".strip(),
            severity_number=severity(event),
            severity_text=severity(event).name,
            attributes=attributes(event),
        )

    def shutdown(self) -> None:
        self._provider.shutdown()
