"""Phoebix desktop application (package `phx`).

Layers (dependencies point downward only):
    ui        -> services
    services  -> domain, data
    domain    -> nothing (pure business rules, no I/O)
    data      -> sqlite3 only
"""
APP_NAME = "Phoebix"
