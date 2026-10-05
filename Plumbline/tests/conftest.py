import os
import sys
import tempfile

# make the package importable when running `pytest` from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# keep tests away from the real user settings / tile cache
os.environ.setdefault("PLUMBLINE_HOME", tempfile.mkdtemp(prefix="plumbline_test_"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
