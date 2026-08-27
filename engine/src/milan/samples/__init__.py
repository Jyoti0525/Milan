"""Sample merchant files, written in other people's dialects.

Generated rather than committed. Four hundred orders of settlement rows is a
megabyte of CSV that would have to be regenerated every time the chaos engine
changed, and a stale sample folder is worse than none - it demonstrates a
month the engine no longer produces.
"""

from milan.samples.build import BUILDERS, Folder, named, write_all, write_one

__all__ = ["BUILDERS", "Folder", "named", "write_all", "write_one"]
