"""NegativeSpace web interface: the FastAPI layer between the browser and the engine.

The engine owns the catalog's schema, photo state and history; this layer reads the
catalog, writes settings through ns_db, and runs the engine as a child process for
everything else (webui-spec.md 5.6, 6.1). The browser never touches SQLite.
"""
