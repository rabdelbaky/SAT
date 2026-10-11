"""Sets coverage.xml mtime to epoch 0 (deliberately stale). Used by coverage-stale fixture."""

import os
import pathlib

# The file already exists; just reset its mtime to make it look old.
p = pathlib.Path("coverage.xml")
if not p.exists():
    # Create a minimal file in case it was not committed (should not happen)
    p.write_text(
        '<?xml version="1.0"?><coverage line-rate="0.9"><packages/></coverage>',
        encoding="utf-8",
    )
# Set both access time and modification time to epoch 0 (year 1970).
os.utime(str(p), (0, 0))
print("coverage.xml mtime set to epoch (stale)")
