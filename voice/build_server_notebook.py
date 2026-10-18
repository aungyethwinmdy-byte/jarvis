"""Build voice/f5_myanmar_tts_server.ipynb from the cells in notebook_src/.

Generated, not hand-edited, because of cell 4: it carries the whole Flask server
as a Python string, and that string inside .ipynb JSON is a wall of \\n escapes —
unreadable, uneditable, and a syntax error in it does not show up until Colab is
minutes into a run. As separate files the cells read and diff like code, and
this build compiles the embedded server here, in a second, and fails loudly if
it is broken.

    py voice/build_server_notebook.py

Writes voice/f5_myanmar_tts_server.ipynb, and — when this machine has a Desktop
— a copy there named f5_myanmar_tts_server_v2.ipynb, which is the file to upload
to Colab (the name is not the same as the old notebook's on purpose: the old one
is the user's file and is left alone).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "notebook_src"
DEST = HERE / "f5_myanmar_tts_server.ipynb"
DESKTOP_COPY = Path(os.path.expanduser("~")) / "Desktop" / "f5_myanmar_tts_server_v2.ipynb"

CELLS = [
    ("c0.md", "markdown"),
    ("c1.py", "code"),
    ("c2.py", "code"),
    ("c3.py", "code"),
    ("c4.py", "code"),
    ("c5.py", "code"),
]


def build() -> dict:
    cells = []
    for name, kind in CELLS:
        source = (SRC / name).read_text(encoding="utf-8")
        cell = {
            "cell_type": kind,
            "metadata": {},
            "source": source.splitlines(keepends=True),
        }
        if kind == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        cells.append(cell)
    return {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"machine_shape": "hm", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def check_server_compiles() -> None:
    """Compile the server code that cell 4 writes into /content/tts_server.py.

    This is the check worth having: everything else in the notebook fails in
    front of the user, but the server only fails at the first spoken line, after
    a model download, and its traceback used to go somewhere nobody could read.
    """
    cell4 = (SRC / "c4.py").read_text(encoding="utf-8")
    m = re.search(r"SERVER_CODE = r'''(.*?)'''", cell4, re.S)
    if not m:
        raise SystemExit("cell 4 no longer contains an r'''SERVER_CODE''' block")
    body = (m.group(1)
            .replace("__REF_WAV__", "/content/ref_aye_thant.wav")
            .replace("__REF_TEXT_FILE__", "/content/ref_text.txt")
            .replace("__OUT_WAV__", "/content/_speak_out.wav")
            .replace("__LOG_PATH__", "/content/server.log")
            .replace("__EXPOSE_LOG__", "True"))
    compile(body, "tts_server.py", "exec")
    print(f"embedded server code compiles ({len(body)} chars)")


def main() -> int:
    check_server_compiles()

    notebook = build()
    text = json.dumps(notebook, ensure_ascii=False, indent=1)
    for path in (DEST, DESKTOP_COPY):
        try:
            path.write_text(text, encoding="utf-8", newline="\n")
        except OSError as e:
            print(f"could not write {path}: {e}")
            continue
        print(f"wrote {path}  ({len(text)} bytes)")

    reloaded = json.loads(DEST.read_text(encoding="utf-8"))
    print(f"cells: {len(reloaded['cells'])}  nbformat: {reloaded['nbformat']}")
    for i, cell in enumerate(reloaded["cells"]):
        first = "".join(cell["source"]).splitlines()[0][:58]
        print(f"  {i}  {cell['cell_type']:8}  {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
