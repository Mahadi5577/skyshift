"""Keep test runs away from the real cache and Hunt database."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="skyshift-tests-")
os.environ["SKYSHIFT_CACHE"] = os.path.join(_tmp, "cache")
os.environ["SKYSHIFT_DATA"] = os.path.join(_tmp, "data")
