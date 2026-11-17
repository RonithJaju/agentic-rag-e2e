"""Configure telemetry at startup, before importing ingestion loaders."""

import logfire

_auto_tracing_installed = False


def install_auto_tracing() -> None:
    """Install the import hook once per process, including spawned workers."""
    global _auto_tracing_installed
    if not _auto_tracing_installed:
        logfire.install_auto_tracing(
            modules=["agentic_rag_e2e.ingestion.loaders"],
            min_duration=0,
        )
        _auto_tracing_installed = True


def configure_observability() -> None:
    """Read Logfire credentials from the environment and enable loader tracing."""
    install_auto_tracing()
    logfire.configure(service_name="rag-ingestion")
