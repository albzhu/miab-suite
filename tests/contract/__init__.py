"""Contract tests between the writer (miab-broker) and the reader (miab-observer).

This package deliberately has an __init__.py so pytest's prepend import mode
resolves the test basedir up to tests/, putting tests/ on sys.path and making
`from conftest import ...` work from this subdirectory.
"""
