def main() -> None:
    from .observability import configure_observability

    configure_observability()
    print("Hello from agentic-rag-e2e!")
