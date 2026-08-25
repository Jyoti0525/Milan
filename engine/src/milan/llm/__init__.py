"""The seam where a language model may be used, and the cache in front of it.

Nothing in this package calls a model yet, and everything above it works when
no model exists. That is the point: the adapter is built before it is needed
so that the day it is needed is a wiring day, not a design day.
"""
