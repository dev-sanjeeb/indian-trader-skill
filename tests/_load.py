import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
REL = os.path.join(FIX, "RELIANCE-22d5m.json.gz")


def load(skill, script):
    folder = os.path.join(ROOT, skill)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location("%s_%s" % (skill.replace("-", "_"), script[:-3]),
                                                  os.path.join(folder, script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
