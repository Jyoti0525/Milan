"""Pure domain types. No I/O, no framework, no dependency on any other layer.

Everything above this package may import from it; it imports from nothing but
the standard library and Pydantic. That direction is what keeps the money
rules testable without a database, a file, or a model.
"""
