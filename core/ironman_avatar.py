"""
Iron Man Mark Holographic Helmet Avatar for JARVIS HUD.
Drop-in replacement or companion for HoloAvatar in core/avatar.py.

Pure PyQt6 QPainter software rendering — zero OpenGL dependencies.
Features:
 - 3D geometric faceted Iron Man Mark armor plates & cranium
 - Glowing neon visor slit eyes with audio-reactive pulsing
 - Dynamic 3D perspective rotation (head sway, pitch, yaw, glance)
 - Reactive energy aura & diagnostic scanline
 - State-aware coloring (Listening, Speaking, Thinking, Muted)
"""

from __future__ import annotations

import math
import random
import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF, QRadialGradient

_CAM_D = 4.8


def _blend(bg: QColor, col: QColor, a: float) -> QColor:
    f = max(0.0, min(1.0, a / 255.0))
    return QColor(
        int(bg.red() + (col.red() - bg.red()) * f),
        int(bg.green() + (col.green() - bg.green()) * f),
        int(bg.blue() + (col.blue() - bg.blue()) * f)
    )


def _c(col: QColor, a: float) -> QColor:
    q = QColor(col)
    q.setAlpha(int(max(0.0, min(255.0, a))))
    return q


class IronManAvatar:
    """
    Animated 3D Holographic Iron Man Helmet.
    API matches HoloAvatar:
      av = IronManAvatar()
      av.step(dt, amp, speaking=..., muted=..., state=...)
      av.paint(painter, cx, cy, r, primary, accent, bg)
    """

    SPAN = 2.15
    shaded = True

    def __init__(self) -> None:
        self._build_geometry()

        self._t = 0.0
        self._sway = 0.0
        self._yaw = 0.0
        self._pitch = 0.0
        self._glow = 0.0
        self._scan = -1.6
        self._mouth = 0.0
        self._emph = 0.0
        self._glance = None

        self._gaze = [0.0, 0.0]
        self._gaze_tgt = [0.0, 0.0]
        self._gaze_at = 0.0

    def _build_geometry(self):
        # Base half-landmarks (x >= 0)
        # y from +1.05 (crown) to -0.95 (chin)
        half_pts = [
            # Center line vertices (x=0)
            ("c_crown_top",    (0.0,  1.08, -0.10)),
            ("c_crown_fwd",    (0.0,  0.98,  0.30)),
            ("c_forehead_hi",  (0.0,  0.80,  0.58)),
            ("c_forehead_mid", (0.0,  0.58,  0.70)),
            ("c_brow_v",       (0.0,  0.36,  0.74)),  # Distinctive Iron Man V-cut brow
            ("c_nose_bridge",  (0.0,  0.18,  0.78)),
            ("c_upper_lip",    (0.0, -0.14,  0.76)),
            ("c_chin_groove",  (0.0, -0.42,  0.72)),
            ("c_chin_bevel",   (0.0, -0.68,  0.70)),
            ("c_chin_tip",     (0.0, -0.90,  0.60)),
            ("c_throat",       (0.0, -1.06,  0.25)),
            ("c_back_top",     (0.0,  0.88, -0.65)),
            ("c_back_mid",     (0.0,  0.35, -0.75)),
            ("c_back_neck",    (0.0, -0.70, -0.55)),

            # Right Side Faceplate & Brow
            ("brow_inner",     (0.14,  0.40,  0.72)),
            ("brow_peak",      (0.32,  0.44,  0.68)),
            ("brow_outer",     (0.52,  0.36,  0.50)),
            
            # Eye Slits (Angular high-tech eye visor)
            ("eye_in_top",     (0.16,  0.28,  0.73)),
            ("eye_out_top",    (0.42,  0.24,  0.64)),
            ("eye_out_bot",    (0.40,  0.17,  0.62)),
            ("eye_in_bot",     (0.18,  0.20,  0.70)),

            # Faceplate Cheek & Jaw Plates
            ("cheek_ridge_hi", (0.48,  0.10,  0.58)),
            ("cheek_notch",    (0.36, -0.16,  0.64)),
            ("cheek_lower",    (0.24, -0.22,  0.68)),
            ("jaw_corner_hi",  (0.50, -0.42,  0.38)),
            ("jaw_corner_lo",  (0.36, -0.70,  0.48)),
            ("chin_side_hi",   (0.22, -0.62,  0.66)),
            ("chin_side_lo",   (0.18, -0.88,  0.56)),

            # Cranium Temple, Ear Pods, Helmet Shell
            ("temple_top",     (0.40,  0.92,  0.18)),
            ("temple_hi",      (0.55,  0.66,  0.34)),
            ("ear_top",        (0.68,  0.18,  0.02)),
            ("ear_front",      (0.68, -0.04,  0.12)),
            ("ear_back",       (0.64, -0.04, -0.12)),
            ("ear_bot",        (0.62, -0.24,  0.00)),
            ("neck_side",      (0.36, -0.98, -0.15)),
            ("back_side_hi",   (0.44,  0.60, -0.45)),
            ("back_side_lo",   (0.48, -0.20, -0.48)),
        ]

        # Generate full symmetric vertex array
        verts = []
        name_map = {}
        for name, pt in half_pts:
            if name.startswith("c_"):
                idx = len(verts)
                verts.append(list(pt))
                name_map[name] = idx
            else:
                r_idx = len(verts)
                verts.append([pt[0], pt[1], pt[2]])
                name_map[name + "_r"] = r_idx

                l_idx = len(verts)
                verts.append([-pt[0], pt[1], pt[2]])
                name_map[name + "_l"] = l_idx

        self._v0 = np.array(verts, dtype=np.float32)
        n_verts = len(self._v0)
        self._v = np.empty_like(self._v0)

        # Polygon faces (triangles) for shaded armor plating
        faces = []
        def tri(n1, n2, n3):
            if n1 in name_map and n2 in name_map and n3 in name_map:
                faces.append([name_map[n1], name_map[n2], name_map[n3]])

        def quad(n1, n2, n3, n4):
            tri(n1, n2, n3)
            tri(n1, n3, n4)

        for side in ["_r", "_l"]:
            opp = "_l" if side == "_r" else "_r"
            # Forehead
            tri("c_crown_fwd", "temple_top" + side, "c_forehead_hi")
            tri("c_forehead_hi", "temple_top" + side, "temple_hi" + side)
            tri("c_forehead_hi", "temple_hi" + side, "c_forehead_mid")
            tri("c_forehead_mid", "temple_hi" + side, "brow_peak" + side)
            tri("c_forehead_mid", "brow_peak" + side, "brow_inner" + side)
            tri("c_forehead_mid", "brow_inner" + side, "c_brow_v")

            # Brow & Temple
            tri("temple_hi" + side, "brow_outer" + side, "brow_peak" + side)
            tri("brow_peak" + side, "brow_outer" + side, "eye_out_top" + side)
            tri("brow_peak" + side, "eye_out_top" + side, "eye_in_top" + side)
            tri("brow_inner" + side, "brow_peak" + side, "eye_in_top" + side)
            tri("c_brow_v", "brow_inner" + side, "c_nose_bridge")
            tri("brow_inner" + side, "eye_in_top" + side, "c_nose_bridge")

            # Eyes (Slits are cut out, faceplate surrounds them)
            tri("c_nose_bridge", "eye_in_bot" + side, "c_upper_lip")
            tri("eye_in_bot" + side, "cheek_notch" + side, "c_upper_lip")
            tri("eye_in_bot" + side, "eye_out_bot" + side, "cheek_notch" + side)
            tri("eye_out_top" + side, "brow_outer" + side, "cheek_ridge_hi" + side)
            tri("eye_out_top" + side, "cheek_ridge_hi" + side, "eye_out_bot" + side)
            tri("eye_out_bot" + side, "cheek_ridge_hi" + side, "cheek_notch" + side)

            # Cheek to Ear
            tri("brow_outer" + side, "ear_top" + side, "cheek_ridge_hi" + side)
            tri("cheek_ridge_hi" + side, "ear_top" + side, "ear_front" + side)
            tri("cheek_ridge_hi" + side, "ear_front" + side, "jaw_corner_hi" + side)
            tri("cheek_ridge_hi" + side, "jaw_corner_hi" + side, "cheek_notch" + side)

            # Mouth & Chin
            tri("c_upper_lip", "cheek_notch" + side, "cheek_lower" + side)
            tri("c_upper_lip", "cheek_lower" + side, "c_chin_groove")
            tri("c_chin_groove", "cheek_lower" + side, "chin_side_hi" + side)
            tri("c_chin_groove", "chin_side_hi" + side, "c_chin_bevel")
            tri("c_chin_bevel", "chin_side_hi" + side, "chin_side_lo" + side)
            tri("c_chin_bevel", "chin_side_lo" + side, "c_chin_tip")

            # Jawline
            tri("cheek_notch" + side, "jaw_corner_hi" + side, "cheek_lower" + side)
            tri("cheek_lower" + side, "jaw_corner_hi" + side, "jaw_corner_lo" + side)
            tri("cheek_lower" + side, "jaw_corner_lo" + side, "chin_side_hi" + side)
            tri("chin_side_hi" + side, "jaw_corner_lo" + side, "chin_side_lo" + side)
            tri("chin_side_lo" + side, "jaw_corner_lo" + side, "c_throat")

            # Ear Pod
            tri("ear_top" + side, "ear_back" + side, "ear_front" + side)
            tri("ear_front" + side, "ear_back" + side, "ear_bot" + side)
            tri("ear_front" + side, "ear_bot" + side, "jaw_corner_hi" + side)

            # Cranium Back & Dome
            tri("c_crown_top", "temple_top" + side, "c_crown_fwd")
            tri("c_crown_top", "back_side_hi" + side, "temple_top" + side)
            tri("c_crown_top", "c_back_top", "back_side_hi" + side)
            tri("c_back_top", "c_back_mid", "back_side_hi" + side)
            tri("back_side_hi" + side, "c_back_mid", "back_side_lo" + side)
            tri("back_side_hi" + side, "ear_top" + side, "temple_top" + side)
            tri("back_side_hi" + side, "ear_back" + side, "ear_top" + side)
            tri("back_side_hi" + side, "back_side_lo" + side, "ear_back" + side)
            tri("back_side_lo" + side, "c_back_neck", "ear_bot" + side)
            tri("c_back_mid", "c_back_neck", "back_side_lo" + side)

        self._faces = np.array(faces, dtype=np.int32)

        # Wireframe edges from unique face pairs
        edge_set = set()
        for f in faces:
            for i in range(3):
                e = (min(f[i], f[(i + 1) % 3]), max(f[i], f[(i + 1) % 3]))
                edge_set.add(e)
        self._edges = np.array(list(edge_set), dtype=np.int32)

        # Eye polygon indices for glowing visor rendering
        self._eye_r_idx = [name_map["eye_in_top_r"], name_map["eye_out_top_r"],
                           name_map["eye_out_bot_r"], name_map["eye_in_bot_r"]]
        self._eye_l_idx = [name_map["eye_in_top_l"], name_map["eye_out_top_l"],
                           name_map["eye_out_bot_l"], name_map["eye_in_bot_l"]]

    def step(self, dt: float, amp: float, speaking: bool = False,
             muted: bool = False, state: str = "", **kwargs) -> None:
        dt = max(0.001, min(0.10, float(dt)))
        self._t += dt
        t = self._t
        amp = max(0.0, min(1.0, float(amp)))
        live = speaking and not muted

        # Idle breathing sway
        speed = 1.0 if not muted else 0.5
        self._sway += dt * speed
        s = self._sway
        self._yaw = 0.20 * math.sin(s * 0.35) + 0.08 * math.sin(s * 0.85 + 1.0)
        self._pitch = 0.05 * math.sin(s * 0.25 + 0.6)

        # Audio energy smoothing
        target_glow = amp if live else 0.0
        self._glow += (target_glow - self._glow) * 0.35

        # Vertical scanning laser bar
        self._scan += dt * (0.6 + 1.8 * self._glow)
        if self._scan > 1.35:
            self._scan = -1.75

        # Speech jaw nod / pulse
        if live:
            self._mouth += (amp * 0.12 - self._mouth) * 0.4
        else:
            self._mouth *= 0.8

        # Saccade / deliberate glance
        if self._glance is not None:
            gx, gy, until = self._glance
            if t < until:
                self._yaw += gx * 0.15
                self._pitch += gy * 0.10
            else:
                self._glance = None

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        self._glance = (max(-1.0, min(1.0, float(dx))),
                        max(-1.0, min(1.0, float(dy))),
                        self._t + max(0.1, float(hold)))

    def _pose(self):
        v = self._v
        np.copyto(v, self._v0)

        # Jaw/chin subtle drop when speaking
        if self._mouth > 0.005:
            chin_mask = v[:, 1] < -0.3
            v[chin_mask, 1] -= self._mouth * 0.12
            v[chin_mask, 2] += self._mouth * 0.05

        # 3D rotation matrix
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        rot = np.array([
            [cy, 0.0, sy],
            [sp * sy, cp, -sp * cy],
            [-cp * sy, sp, cp * cy]
        ], dtype=np.float32)

        return v @ rot.T

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor | None = None) -> None:
        if bg is None:
            bg = QColor(0, 6, 10)

        amp = self._glow
        verts = self._pose()

        # 1. Radial background aura
        ar = r * 1.85
        grad = QRadialGradient(cx, cy, ar)
        grad.setColorAt(0.00, _c(primary, int(45 + 80 * amp)))
        grad.setColorAt(0.35, _c(primary, int(25 + 45 * amp)))
        grad.setColorAt(1.00, _c(primary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - ar, cy - ar, ar * 2, ar * 2))

        # 2. 3D Perspective Projection
        z_dist = _CAM_D - verts[:, 2]
        np.maximum(z_dist, 0.35, out=z_dist)
        k = (_CAM_D / z_dist) * r
        xs = cx + verts[:, 0] * k
        ys = cy - verts[:, 1] * k

        # 3. Shaded Armor Facet Plates
        if self.shaded:
            self._paint_facets(p, xs, ys, verts, primary, accent, bg, amp)

        # 4. Glowing Sci-Fi Wireframe Overlay
        self._paint_wire(p, xs, ys, verts, primary, bg, amp)

        # 5. Glowing Visor Slit Eyes
        self._paint_eyes(p, xs, ys, primary, accent, amp)

    def _paint_facets(self, p: QPainter, xs, ys, verts, primary: QColor,
                      accent: QColor, bg: QColor, amp: float) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)

        # Compute facet normals & backface culling
        fa, fb, fc = self._faces[:, 0], self._faces[:, 1], self._faces[:, 2]
        vA, vB, vC = verts[fa], verts[fb], verts[fc]
        fn = np.cross(vB - vA, vC - vA)
        norm = np.linalg.norm(fn, axis=1, keepdims=True)
        norm[norm == 0] = 1e-9
        fn /= norm

        # Forward facing facets (Z normal > 0)
        nz = fn[:, 2]
        front = nz > 0.02
        if not np.any(front):
            return

        vis_indices = np.flatnonzero(front)
        # Depth sort
        z_mid = (verts[fa[vis_indices], 2] + verts[fb[vis_indices], 2] + verts[fc[vis_indices], 2]) / 3.0
        sort_order = np.argsort(z_mid)
        sorted_faces = vis_indices[sort_order]

        for fi in sorted_faces:
            a, b, c = fa[fi], fb[fi], fc[fi]
            norm_z = nz[fi]
            # Key light from top-left
            diffuse = max(0.0, fn[fi, 0] * -0.45 + fn[fi, 1] * 0.55 + norm_z * 0.45)
            brightness = 0.22 + 0.65 * (diffuse ** 1.2) + 0.25 * amp
            brightness = max(0.0, min(1.0, brightness))

            face_color = _blend(bg, primary, brightness * 160)
            poly = QPolygonF([QPointF(xs[a], ys[a]), QPointF(xs[b], ys[b]), QPointF(xs[c], ys[c])])
            p.setBrush(QBrush(face_color))
            p.drawPolygon(poly)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _paint_wire(self, p: QPainter, xs, ys, verts, primary: QColor, bg: QColor, amp: float) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        e0, e1 = self._edges[:, 0], self._edges[:, 1]
        z_avg = (verts[e0, 2] + verts[e1, 2]) * 0.5
        front = z_avg > -0.15

        e0_f = e0[front]
        e1_f = e1[front]

        # Scanline glow modulation
        y_avg = (verts[e0_f, 1] + verts[e1_f, 1]) * 0.5
        scan_dist = np.abs(y_avg - self._scan)
        scan_glow = np.exp(-(scan_dist / 0.18) ** 2)

        alpha = 130 + 90 * scan_glow + 70 * amp
        alpha = np.clip(alpha, 60, 255)

        for i in range(len(e0_f)):
            idx0, idx1 = e0_f[i], e1_f[i]
            col = _blend(bg, primary, alpha[i])
            p.setPen(QPen(col, 1.2))
            p.drawLine(QPointF(xs[idx0], ys[idx0]), QPointF(xs[idx1], ys[idx1]))

    def _paint_eyes(self, p: QPainter, xs, ys, primary: QColor, accent: QColor, amp: float) -> None:
        # Draw high-intensity glowing slit eyes
        for eye_indices in [self._eye_r_idx, self._eye_l_idx]:
            poly = QPolygonF([QPointF(xs[i], ys[i]) for i in eye_indices])
            center = poly.boundingRect().center()
            ew = poly.boundingRect().width()
            eh = poly.boundingRect().height()

            # Outer soft glow
            p.setPen(Qt.PenStyle.NoPen)
            glow_col = _c(primary, int(120 + 130 * amp))
            p.setBrush(QBrush(glow_col))
            p.drawEllipse(center, ew * 0.85, eh * 1.4)

            # Inner bright neon slit
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(accent, 1.6))
            p.drawPolygon(poly)
