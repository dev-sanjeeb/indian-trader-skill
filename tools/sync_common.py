#!/usr/bin/env python3
"""Copy common/inmarket.py into every skill folder and refresh the shared Safety
block in each SKILL.md (between the safety markers). Run after editing common/.

  python3 tools/sync_common.py          write
  python3 tools/sync_common.py --check  exit 1 if anything is out of date (used by the tests)
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = "<!-- safety:start -->", "<!-- safety:end -->"


def main():
    check = "--check" in sys.argv
    common = open(os.path.join(ROOT, "common", "inmarket.py"), encoding="utf-8").read()
    safety = open(os.path.join(ROOT, "common", "SAFETY.md"), encoding="utf-8").read().strip()
    block = "%s\n%s\n%s" % (START, safety, END)
    stale = []
    for d in sorted(glob.glob(os.path.join(ROOT, "in-trader-*"))):
        p = os.path.join(d, "inmarket.py")
        cur = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        if cur != common:
            stale.append(p)
            if not check:
                open(p, "w", encoding="utf-8").write(common)
        sk = os.path.join(d, "SKILL.md")
        txt = open(sk, encoding="utf-8").read()
        if "{{SAFETY}}" in txt:
            new = txt.replace("{{SAFETY}}", block)
        elif START in txt:
            a, b = txt.index(START), txt.index(END) + len(END)
            new = txt[:a] + block + txt[b:]
        else:
            new = txt.rstrip() + "\n\n" + block + "\n"
        if new != txt:
            stale.append(sk)
            if not check:
                open(sk, "w", encoding="utf-8").write(new)
    if check and stale:
        print("out of date: " + ", ".join(os.path.relpath(s, ROOT) for s in stale))
        return 1
    print("%s %d file(s)." % ("Would update" if check else "Updated", len(stale)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
