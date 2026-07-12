"""Importers for external services via Chrome DevTools Protocol (CDP).

Each fetcher module knows how to extract a conversation from a specific web
chat service by injecting JS into a running browser tab and reading the
result back over CDP.
"""