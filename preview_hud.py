"""Render the HUD to a PNG so the frame furniture can be looked at.

Runs Qt on the **native** platform, builds the real `HudCanvas`, sets live-looking
metric values, and grabs the widget. Nothing here ships — it is a way to see the
HUD without starting the assistant and waiting for a state to occur.

WHY NOT THE OFFSCREEN PLATFORM

    `QT_QPA_PLATFORM=offscreen` renders every glyph as an empty box — measured
    2026-09-29 with plain ASCII and four different monospace families, so it is
    the plugin's font engine and not the font choice. The shapes were right and
    every number in the preview was a placeholder, which is exactly the kind of
    preview that misleads. The native platform renders text correctly, and the
    widget is never `show()`n, so nothing appears on screen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication                     # noqa: E402

import ui                                                    # noqa: E402

OUT = Path("preview_hud.png")
W, H = 1200, 760


def main() -> int:
    app = QApplication(sys.argv)

    hud = ui.HudCanvas("", assistant_name="J.A.R.V.I.S")
    hud.resize(W, H)
    hud.state = "LISTENING"
    hud._amp_disp = 0.42
    hud._blink = True

    # Let `_metrics` take a real reading rather than pinning a number. The
    # background thread polls on its own schedule and overwrites anything set
    # here — the first attempt wrote cpu=37 and the render showed 0, because
    # the thread had already replaced it. A preview showing the machine's
    # actual load is also the more useful one.
    for _ in range(60):
        app.processEvents()
        time.sleep(0.05)
        if ui._metrics.cpu > 0:
            break
    print(f"cpu={ui._metrics.cpu:.1f}  mem={ui._metrics.mem:.1f}")

    # Two passes: the first lets the layout settle and the cached grid layer
    # build at this size, the second is the one that is kept.
    hud.grab()
    app.processEvents()
    pix = hud.grab()
    pix.save(str(OUT), "PNG")
    print(f"saved {OUT}  {pix.width()}x{pix.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
