"""The scrub check: the tree holds nothing of the machine it was made on and nothing of the build it came from.

    python3 scrub.py        prints each finding with its file and line; exit 1 when there is one

It looks for an absolute path of a machine, the hostname of this machine, an IP address, an email address, a
tailnet address, a task or milestone id and a specification id of the build the panes came from, the name of that
build (allowed in CHANGELOG.md only) and a person's name. The patterns are built from parts, so this file does
not match itself.
"""
import os
import re
import socket
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "b" + "lqc"
RULES = [
    ("an absolute path", re.compile(r"(?<![\w.~$])/(?:data|home|root|tmp|var|etc|srv|opt|mnt|media|Users|private)/")),
    ("this hostname", re.compile(re.escape(socket.gethostname()), re.I)),
    ("an IP address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("an email address", re.compile(r"[\w.+-]+" + "@" + r"[\w-]+(?:\.[\w-]+)+")),
    ("a tailnet address", re.compile(r"\.ts" + r"\.net\b|\btail" + "scale" + r"\b|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.",
                                     re.I)),
    ("a task or milestone id", re.compile(r"\bT-\d{3}\b|\bMS-\d+\b")),
    ("a specification id", re.compile(r"\b(?:BF|FR|NFR|DEV|FL|AT|OQ|IQ|UI|EV|MP|DC|ENV|IF)-\d+\b")),
    ("the build's name", re.compile(NAME, re.I)),
    ("a person's name", re.compile(r"\bJ" + r"osh\b")),
]


def main():
    found = 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ROOT)
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                print("%s: not a text file" % rel)
                found += 1
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for what, rx in RULES:
                    if what == "the build's name" and rel == "CHANGELOG.md":
                        continue
                    if rx.search(line):
                        print("%s:%d: %s: %s" % (rel, n, what, line.strip()[:100]))
                        found += 1
    print("scrub: %s" % ("clean" if not found else "%d finding(s)" % found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
