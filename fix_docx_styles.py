"""Repair a .docx that the local editor SDK wrote and Word refuses to open.

WHY THIS EXISTS
    `USER-GUIDE.docx` was produced by the local editor SDK and **Word refused to
    open it** — "Word experienced an error trying to open the file" — while
    `python-docx` opened it happily, and the package looked well-formed: eleven
    parts, all XML well-formed, every part declared in `[Content_Types].xml`,
    every relationship resolvable.

    Bisected with Word itself (a private COM instance, open, report, quit) by
    swapping one part at a time into a package python-docx had made and Word had
    accepted. The fault was in `word/document.xml`, and it is this:

        <w:sectPr/></w:body></w:document>

    An **empty `w:sectPr`**. The final section properties must carry a page size;
    with none, Word has no page to lay the document out on and reports the
    generic "experienced an error" rather than anything useful. python-docx
    defaults the page and never notices.

    Two faults were found and both are repaired here:
      1. `word/styles.xml` empty — no `docDefaults`, no `Normal`, no default
         table style. (This alone did not fix it; it is still wrong.)
      2. `word/document.xml`'s final `w:sectPr` empty.

USAGE
    py fix_docx_styles.py <file.docx> [<output.docx>]
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

# A4 portrait, 2 cm margins — the same geometry the editor's own template uses,
# so nothing about the layout changes; it just becomes explicit.
SECTPR = ('<w:sectPr>'
          '<w:pgSz w:w="11906" w:h="16838"/>'
          '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
          'w:header="709" w:footer="709" w:gutter="0"/>'
          '<w:cols w:space="708"/>'
          '<w:docGrid w:linePitch="360"/>'
          '</w:sectPr>')

_EMPTY_SECTPR = re.compile(r"<w:sectPr\s*/>")

# ── fault 3: markdown fenced code blocks become wps text boxes ───────────────
#
# THE ONE THAT ACTUALLY BROKE WORD.
#   The editor SDK renders a ``` block as a `wps:wsp` shape with `txBox="1"`,
#   placed directly inside `<wp:inline>` and **without** the `mc:AlternateContent`
#   wrapper Word requires around a wps shape. Three of them in this document
#   (paragraphs 23, 64 and 83) and Word refuses the whole file with the generic
#   "experienced an error trying to open the file".
#
#   Found by bisecting the body against Word itself: the first 23 paragraphs
#   opened, the first 24 did not, and the 24th was a code block. python-docx
#   reads them without complaint, which is why the fault was invisible until
#   Word was asked.
#
#   They are replaced with ordinary shaded paragraphs — same text, same
#   monospace look, no shape, nothing for Word to object to.
_MONO = "Consolas"


def _top_level_paragraphs(inner: str) -> list[tuple[int, int]]:
    """(start, end) spans of every `w:p` at depth 0 inside the body."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = None
    for m in re.finditer(r"<(/?)w:p\b[^>]*?(/?)>", inner):
        closing, selfclose = m.group(1), m.group(2)
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, m.end()))
                start = None
        elif selfclose:
            if depth == 0:
                spans.append((m.start(), m.end()))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def _textbox_lines(paragraph: str) -> list[str]:
    """The lines inside a text box, in order."""
    content = re.search(r"<w:txbxContent>(.*)</w:txbxContent>", paragraph, re.S)
    if not content:
        return []
    lines = []
    for span in _top_level_paragraphs(content.group(1)):
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                                  content.group(1)[span[0]:span[1]]))
        lines.append(text)
    return lines


def _code_paragraph(line: str) -> str:
    """One line of a code block, as a plain shaded monospace paragraph."""
    esc = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        '<w:p><w:pPr>'
        '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>'
        '<w:spacing w:before="0" w:after="0"/>'
        '<w:ind w:left="240"/>'
        '</w:pPr>'
        f'<w:r><w:rPr><w:rFonts w:ascii="{_MONO}" w:hAnsi="{_MONO}" w:cs="{_MONO}"/>'
        '<w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr>'
        f'<w:t xml:space="preserve">{esc}</w:t></w:r></w:p>'
    )


def replace_textboxes(doc: str) -> tuple[str, int]:
    """Swap every wps text box for ordinary paragraphs. (new_xml, count)."""
    open_tag = "<w:body>"
    i = doc.index(open_tag) + len(open_tag)
    j = doc.rindex("</w:body>")
    inner = doc[i:j]

    # Walk back to front so earlier spans keep their offsets.
    out = inner
    swapped = 0
    for start, end in reversed(_top_level_paragraphs(inner)):
        para = inner[start:end]
        if "<wps:wsp>" not in para:
            continue
        lines = _textbox_lines(para) or [""]
        out = out[:start] + "".join(_code_paragraph(ln) for ln in lines) + out[end:]
        swapped += 1
    return doc[:i] + out + doc[j:], swapped

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Pyidaungsu" w:cs="Calibri"/>
<w:sz w:val="22"/><w:szCs w:val="22"/>
<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr>
<w:spacing w:after="160" w:line="259" w:lineRule="auto"/>
</w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>
<w:qFormat/></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal">
<w:name w:val="Normal Table"/><w:semiHidden/><w:unhideWhenUsed/>
<w:tblPr><w:tblInd w:w="0" w:type="dxa"/>
<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>
<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>
</w:tblPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:basedOn w:val="TableNormal"/><w:uiPriority w:val="39"/>
<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>
</w:tblBorders></w:tblPr></w:style>
{headings}
</w:styles>
"""

# Heading 1-6. The document marks its headings with a direct `w:outlineLvl`
# rather than a style reference, so these are here so Word's Navigation pane and
# its own style list behave — and because a document with no heading styles at
# all is the shape Word is least happy with.
_HEADING = """<w:style w:type="paragraph" w:styleId="Heading{n}">
<w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:qFormat/>
<w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="{before}" w:after="{after}"/>
<w:outlineLvl w:val="{lvl}"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr>
</w:style>"""

_SIZES = {1: "36", 2: "30", 3: "26", 4: "24", 5: "22", 6: "22"}
_SPACE = {1: ("360", "120"), 2: ("280", "100"), 3: ("240", "80"),
          4: ("200", "80"), 5: ("160", "60"), 6: ("160", "60")}


def build_styles() -> str:
    parts = []
    for n in range(1, 7):
        before, after = _SPACE[n]
        parts.append(_HEADING.format(n=n, lvl=n - 1, sz=_SIZES[n],
                                     before=before, after=after))
    return "\n".join(parts)


def is_empty_styles(xml: str) -> bool:
    """True when the styles part declares no styles at all."""
    return not re.search(r"<w:(style|docDefaults)\b", xml or "")


def repair(src: Path, dst: Path | None = None) -> tuple[bool, str]:
    """(changed, message). Copies every part through, fixing the two known faults."""
    dst = dst or src
    tmp = dst.with_suffix(".docx.tmp")
    notes: list[str] = []

    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        if "word/document.xml" not in names:
            return False, "no word/document.xml in this package"

        parts: dict[str, bytes] = {}
        for item in zin.infolist():
            if item.filename.endswith("/"):     # directory entries: not OPC parts
                continue
            parts[item.filename] = zin.read(item.filename)

    # ── fault 1: the final section properties have no page size ──────────────
    doc = parts.get("word/document.xml", b"").decode("utf-8")
    doc, n_sect = _EMPTY_SECTPR.subn(SECTPR, doc)
    if n_sect:
        notes.append(f"filled in {n_sect} empty sectPr (page size was missing)")

    # ── fault 3: wps text boxes without the mc:AlternateContent wrapper ──────
    # THE ONE THAT ACTUALLY STOPPED WORD OPENING THE FILE. Done before the
    # styles work so the counts in the notes refer to the document as written.
    doc, n_boxes = replace_textboxes(doc)
    if n_boxes:
        notes.append(f"replaced {n_boxes} text box(es) with ordinary paragraphs "
                     f"(markdown code blocks — Word rejects a wps shape that is "
                     f"not wrapped in mc:AlternateContent)")
    parts["word/document.xml"] = doc.encode("utf-8")

    # ── fault 2: the styles part declares nothing ───────────────────────────
    styles = parts.get("word/styles.xml", b"").decode("utf-8", "replace")
    if "word/styles.xml" not in parts:
        notes.append("added word/styles.xml")
        parts["word/styles.xml"] = STYLES.format(headings=build_styles()).encode("utf-8")
    elif is_empty_styles(styles):
        notes.append("populated an empty styles part")
        parts["word/styles.xml"] = STYLES.format(headings=build_styles()).encode("utf-8")

    if not notes:
        return False, "nothing to repair — both parts already look right"

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in parts.items():
            zout.writestr(name, data)

    shutil.move(str(tmp), str(dst))
    return True, "; ".join(notes)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: py fix_docx_styles.py <file.docx> [<out.docx>]")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    changed, message = repair(src, dst)
    print(("changed: " if changed else "skipped: ") + message)
