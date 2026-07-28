#!/usr/bin/env python3
"""
光伏跟踪支架阵列设计工具 v2.0 — 1P 产品
PV Tracker Array Design Tool - Front View
正视图：沿主梁（扭矩管）方向，驱动柱为中心（X=0），主梁从±77.5向两边延伸
"""

import sys, os, math, csv, random
from dataclasses import dataclass, field
from typing import List, Tuple
from datetime import date

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# ═══════════════════════════════════════════════════════════════════════════════════
D = {
    # ── 组件 ──
    "panel_len": 2382.0,
    "panel_wid": 1134.0,
    "panel_thk": 30.0,
    "hole_spacing": 1095.0,
    "panel_gap": 18.0,
    # ── 阵列 ──
    "panel_cnt_total": 40,
    "rotation_gap": 600.0,
    "left_cnt_auto": True,
    "right_cnt_auto": True,
    "left_panel_cnt": 20,
    "right_panel_cnt": 20,
    # ── 立柱 ──
    "col_cnt": 9,
    "col_ht": 1500.0,
    "col_sec_w": 100.0,
    "col_inf_no_damping": 100.0,
    "col_inf_damping_outer": 240.0,
    "col_inf_damping_inner": 100.0,
    "col_spacings": [2207, 4600, 5500, 5500, 5600, 5600, 5500, 5500, 4600, 2207],
    "col_damping": [True, True, False, False, False, False, False, True, True],
    # ── 檩条 ──
    "purlin_w": 88.0,
    "purlin_h": 80.0,
    "purlin_influence": 50.0,
    "purlin_end_offset": 57.0,
    # ── 主梁 ──
    "beam_center_half": 77.5,       # 中心距（主梁从 ±77.5 出发）
    "beam_telescope": 260.0,        # 缩管/连接件长度
    "splice_inf_half": 180.0,       # 连接件干涉半宽
    "splice_h": 200.0,              # 连接件截面高
    # ── 检查 ──
    "col_spacing_min": 2000.0,
    "col_spacing_max": 8000.0,
}

PURLIN_GAP_CONSTANT = 57.0
DEFAULT_BEAM_SEGMENTS = [24000, 24000]  # 简单覆盖组件，后续主梁自动设计再细化

COL_END_REDUCTION = 1000  # 末跨比常规间距减小量

def col_spacing_pool(step):
    """组件宽度+间隙(step)的整数/半整数倍，四舍五入到整百"""
    pool = []
    for mult in [4, 4.5, 5, 5.5, 6, 6.5, 7]:
        v = round(mult * step / 100) * 100
        if v >= 8100:
            continue
        if 8000 < v < 8100:
            v = 8000
        if 5000 <= v <= 8000 and v not in pool:
            pool.append(v)
    return pool

# ═══════════════════════════════════════════════════════════════════════════════════
@dataclass
class InterferenceIssue:
    level: str
    msg: str
    x: float = 0.0


@dataclass
class PVParams:
    # ── 组件 ──
    panel_len: float = D["panel_len"]
    panel_wid: float = D["panel_wid"]
    panel_thk: float = D["panel_thk"]
    hole_spacing: float = D["hole_spacing"]
    panel_gap: float = D["panel_gap"]

    # ── 阵列 ──
    panel_cnt_total: int = D["panel_cnt_total"]
    rotation_gap: float = D["rotation_gap"]
    left_cnt_auto: bool = D["left_cnt_auto"]
    right_cnt_auto: bool = D["right_cnt_auto"]
    left_panel_cnt: int = D["left_panel_cnt"]
    right_panel_cnt: int = D["right_panel_cnt"]

    # ── 立柱 ──
    col_cnt: int = D["col_cnt"]
    col_ht: float = D["col_ht"]
    col_sec_w: float = D["col_sec_w"]
    col_inf_no_damping: float = D["col_inf_no_damping"]
    col_inf_damping_outer: float = D["col_inf_damping_outer"]
    col_inf_damping_inner: float = D["col_inf_damping_inner"]
    col_spacings: List[float] = field(default_factory=lambda: list(D.get("col_spacings", [])))
    col_damping: List[bool] = field(default_factory=lambda: list(D.get("col_damping", [])))

    # ── 檩条 ──
    purlin_w: float = D["purlin_w"]
    purlin_h: float = D["purlin_h"]
    purlin_influence: float = D["purlin_influence"]
    purlin_end_offset: float = D["purlin_end_offset"]

    # ── 主梁 ──
    beam_center_half: float = D["beam_center_half"]
    beam_telescope: float = D["beam_telescope"]
    splice_inf_half: float = D["splice_inf_half"]
    splice_h: float = D["splice_h"]
    beam_segments: List[float] = field(default_factory=lambda: list(DEFAULT_BEAM_SEGMENTS))
    beam_segment_types: List[str] = field(default_factory=list)

    # ── 检查 ──
    col_spacing_min: float = D["col_spacing_min"]
    col_spacing_max: float = D["col_spacing_max"]

    # ── 衍生 ──
    total_span: float = 0.0
    left_edge: float = 0.0
    right_edge: float = 0.0
    beam_edges: List[Tuple[float, float]] = field(default_factory=list)  # [(start, end, type)]
    purlin_positions: List[float] = field(default_factory=list)
    col_positions: List[float] = field(default_factory=list)
    col_names: List[str] = field(default_factory=list)
    col_is_drive: List[bool] = field(default_factory=list)
    col_inf_left: List[float] = field(default_factory=list)
    col_inf_right: List[float] = field(default_factory=list)
    splice_positions: List[float] = field(default_factory=list)
    panel_left_edges: List[float] = field(default_factory=list)

    def derive(self):
        # 1. gap ↔ hole_spacing
        self.panel_gap = PURLIN_GAP_CONSTANT - self.panel_wid + self.hole_spacing

        # 2. 自动分配左右组件数
        left = self.panel_cnt_total // 2
        right = self.panel_cnt_total - left
        if self.left_cnt_auto:
            self.left_panel_cnt = left
        if self.right_cnt_auto:
            self.right_panel_cnt = right

        step = self.panel_wid + self.panel_gap

        # 3-4. 檩条位置
        self.purlin_positions = []
        if self.right_panel_cnt > 0:
            rs = self.rotation_gap / 2.0 - self.panel_gap / 2.0
            for i in range(self.right_panel_cnt + 1):
                x = rs + i * step
                if i == self.right_panel_cnt:
                    x -= self.purlin_end_offset
                self.purlin_positions.append(x)
        if self.left_panel_cnt > 0:
            ls = -(self.rotation_gap / 2.0 - self.panel_gap / 2.0)
            lp = []
            for i in range(self.left_panel_cnt + 1):
                x = ls - i * step
                if i == self.left_panel_cnt:
                    x += self.purlin_end_offset
                lp.append(x)
            self.purlin_positions = sorted(lp + self.purlin_positions)

        if self.purlin_positions:
            self.left_edge = self.purlin_positions[0]
            self.right_edge = self.purlin_positions[-1]
            self.total_span = self.right_edge - self.left_edge
        else:
            self.left_edge = self.right_edge = self.total_span = 0.0

        # 5. 组件左边缘
        self.panel_left_edges = []
        for i in range(self.right_panel_cnt):
            self.panel_left_edges.append(self.rotation_gap / 2.0 + i * step)
        for i in range(self.left_panel_cnt):
            re = -(self.rotation_gap / 2.0 + i * step)
            self.panel_left_edges.append(re - self.panel_wid)
        self.panel_left_edges.sort()

        # 6. 立柱间距自动补全
        need = self.col_cnt + 1
        if len(self.col_spacings) != need:
            eg = self.total_span / need if self.total_span > 0 else 2000
            self.col_spacings = [eg] * need
        if len(self.col_damping) != self.col_cnt:
            self.col_damping = [False] * self.col_cnt

        # 7. 立柱位置 — 驱动柱固定在 X=0
        self.col_positions = [0.0] * self.col_cnt
        di = (self.col_cnt - 1) // 2
        self.col_positions[di] = 0.0
        for i in range(di + 1, self.col_cnt):
            self.col_positions[i] = self.col_positions[i - 1] + self.col_spacings[i]
        for i in range(di - 1, -1, -1):
            self.col_positions[i] = self.col_positions[i + 1] - self.col_spacings[i + 1]

        # 8. 立柱命名 & 干涉
        self.col_names = []
        self.col_is_drive = []
        self.col_inf_left = []
        self.col_inf_right = []
        lc = di
        for i in range(self.col_cnt):
            if i == lc:
                self.col_names.append("驱动柱")
                self.col_is_drive.append(True)
                self.col_inf_left.append(self.col_sec_w / 2)
                self.col_inf_right.append(self.col_sec_w / 2)
            else:
                self.col_names.append(
                    f"非驱动柱左{lc - i}" if i < lc else f"非驱动柱右{i - lc}")
                self.col_is_drive.append(False)
                if self.col_damping[i]:
                    if i < lc:
                        self.col_inf_left.append(self.col_inf_damping_outer)
                        self.col_inf_right.append(self.col_inf_damping_inner)
                    else:
                        self.col_inf_left.append(self.col_inf_damping_inner)
                        self.col_inf_right.append(self.col_inf_damping_outer)
                else:
                    self.col_inf_left.append(self.col_inf_no_damping)
                    self.col_inf_right.append(self.col_inf_no_damping)

        # 9. 主梁段类型自动设置（中间两根 F，其余 S）
        n = len(self.beam_segments)
        if n >= 2:
            mid = n // 2
            self.beam_segment_types = ["S"] * n
            self.beam_segment_types[mid - 1] = "F"
            self.beam_segment_types[mid] = "F"
        elif n == 1:
            self.beam_segment_types = ["F"]
        else:
            self.beam_segment_types = []

        # 10. 主梁段位置 & 连接件位置
        self.beam_edges = []
        self.splice_positions = []

        # 右侧
        cx = self.beam_center_half
        prev_end = None
        for i in range(mid, n) if n >= 2 else (range(n) if n == 1 else range(0)):
            seg_len = self.beam_segments[i]
            stype = self.beam_segment_types[i]
            if stype == "F":
                start = cx
            else:
                start = cx - self.beam_telescope
                # 连接件中心在重叠区中点
                self.splice_positions.append((cx + start) / 2)
            end = start + seg_len
            self.beam_edges.append((start, end, stype))
            cx = end

        # 左侧
        if n >= 2:
            cx = -self.beam_center_half
            for i in range(mid - 1, -1, -1):
                seg_len = self.beam_segments[i]
                stype = self.beam_segment_types[i]
                if stype == "F":
                    start = cx
                else:
                    start = cx + self.beam_telescope
                    self.splice_positions.append((cx + start) / 2)
                end = start - seg_len
                self.beam_edges.insert(0, (end, start, stype))
                cx = end
        elif n == 1:
            pass  # already handled above

        self.beam_edges.sort(key=lambda e: e[0])
        self.splice_positions.sort()

    def beam_len_total(self):
        return sum(self.beam_segments) if self.beam_segments else 0.0


# ═══════════════════════════════════════════════════════════════════════════════════
def check_interference(p: PVParams) -> List[InterferenceIssue]:
    issues = []
    def interval_overlap(l1, r1, l2, r2):
        """两个区间 [l1,r1] 和 [l2,r2] 是否重叠"""
        return r1 >= l2 and r2 >= l1

    p_inf = p.purlin_influence  # purlin half-width

    # 1. 立柱 vs 檩条（使用不对称干涉范围）
    for i, cx in enumerate(p.col_positions):
        c_l = cx - p.col_inf_left[i]
        c_r = cx + p.col_inf_right[i]
        for pi, px in enumerate(p.purlin_positions):
            p_l = px - p_inf
            p_r = px + p_inf
            if interval_overlap(c_l, c_r, p_l, p_r):
                issues.append(InterferenceIssue("critical",
                    f"⚠ {p.col_names[i]} 与 檩条{pi + 1} 干涉 (X={cx:.0f}↔{px:.0f})", cx))

    # 2. 连接件 vs 立柱（使用不对称干涉范围）
    for si, sx in enumerate(p.splice_positions):
        s_l = sx - p.splice_inf_half
        s_r = sx + p.splice_inf_half
        for i, cx in enumerate(p.col_positions):
            c_l = cx - p.col_inf_left[i]
            c_r = cx + p.col_inf_right[i]
            if interval_overlap(s_l, s_r, c_l, c_r):
                issues.append(InterferenceIssue("critical",
                    f"⚠ 连接件{si + 1} 与 {p.col_names[i]} 干涉 (X={sx:.0f}↔{cx:.0f})", sx))

    # 3. 连接件 vs 檩条
    for si, sx in enumerate(p.splice_positions):
        s_l = sx - p.splice_inf_half
        s_r = sx + p.splice_inf_half
        for pi, px in enumerate(p.purlin_positions):
            p_l = px - p_inf
            p_r = px + p_inf
            if interval_overlap(s_l, s_r, p_l, p_r):
                issues.append(InterferenceIssue("critical",
                    f"⚠ 连接件{si + 1} 与 檩条{pi + 1} 干涉 (X={sx:.0f}↔{px:.0f})", sx))

    # 4. 跨距
    if p.col_spacing_min > 0 or p.col_spacing_max > 0:
        sc = sorted(p.col_positions)
        for i in range(1, len(sc)):
            d = sc[i] - sc[i - 1]
            mid = (sc[i - 1] + sc[i]) / 2
            if p.col_spacing_min > 0 and d < p.col_spacing_min - 0.01:
                issues.append(InterferenceIssue("warning",
                    f"⚡ 立柱跨距({d:.0f}mm) < 最小推荐({p.col_spacing_min:.0f}mm)", mid))
            if p.col_spacing_max > 0 and d > p.col_spacing_max + 0.01:
                issues.append(InterferenceIssue("warning",
                    f"⚡ 立柱跨距({d:.0f}mm) > 最大推荐({p.col_spacing_max:.0f}mm)", mid))

    # 5. 超范围
    for i, cx in enumerate(p.col_positions):
        if cx < p.left_edge - 0.01 or cx > p.right_edge + 0.01:
            issues.append(InterferenceIssue("critical",
                f"⚠ {p.col_names[i]}(X={cx:.0f}) 超出主梁范围", cx))

    if not issues:
        issues.append(InterferenceIssue("ok", "✅ 全部检查通过，无干涉。"))

    issues.sort(key=lambda iss: (
        0 if iss.level == "critical" else (1 if iss.level == "warning" else 2), iss.x))
    return issues


# ═══════════════════════════════════════════════════════════════════════════════════
class FrontViewWidget(QGraphicsView):

    COL_GROUND   = QColor(139, 115, 85)
    COL_DRIVE    = QColor(230, 126, 34)
    COL_COLUMN   = QColor(90, 108, 125)
    COL_COLUMN_E = QColor(231, 76, 60)
    COL_BEAM     = QColor(68, 114, 196)
    COL_BEAM_S   = QColor(88, 134, 216)
    COL_SPLICE   = QColor(240, 147, 43)
    COL_SPLICE_E = QColor(255, 107, 107)
    COL_PURLIN   = QColor(142, 154, 175)
    COL_PURLIN_E = QColor(255, 204, 204)
    COL_PANEL    = QColor(213, 229, 245)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(255, 255, 255))
        self.setMinimumSize(500, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._zoom_level = 1.0

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._zoom_level *= factor
        self.scale(factor, factor)

    def draw_view(self, p: PVParams, issues: List[InterferenceIssue]):
        self._scene.clear()

        margin_x = max(500, p.total_span * 0.06) if p.total_span > 0 else 2000
        world_min_x = p.left_edge - margin_x
        world_max_x = p.right_edge + margin_x
        world_min_y = -700
        world_max_y = p.col_ht + p.purlin_h + p.panel_thk + 1200

        if p.total_span == 0:
            world_min_x = -2000
            world_max_x = 2000

        def sx(wx): return wx - world_min_x
        def sy(wy): return world_max_y - wy

        scene_w = world_max_x - world_min_x
        scene_h = world_max_y - world_min_y
        self._scene.setSceneRect(0, 0, scene_w, scene_h)

        def add_rect(x, y, w, h, fill, border, bw=1.5, z=0):
            r = self._scene.addRect(sx(x), sy(y + h), w, h, QPen(border, bw), QBrush(fill))
            r.setZValue(z)
            return r

        def add_text(x, y, text, size=9, color=QColor(44, 62, 80), bold=False,
                     rotate=0, anchor="center"):
            font = QFont("Microsoft YaHei", size)
            font.setBold(bold)
            item = self._scene.addSimpleText(text, font)
            item.setBrush(QBrush(color))
            item.setZValue(20)
            if rotate:
                item.setRotation(rotate)
            br = item.boundingRect()
            if anchor == "center":
                item.setPos(sx(x) - br.width() / 2, sy(y) - br.height() / 2)
            elif anchor == "left":
                item.setPos(sx(x), sy(y) - br.height() / 2)
            elif anchor == "right":
                item.setPos(sx(x) - br.width(), sy(y) - br.height() / 2)
            return item

        conflict_xs = {iss.x for iss in issues if iss.level == "critical"}

        def near_conflict(x, tolerance=200):
            return any(abs(x - cfx) < tolerance for cfx in conflict_xs)

        # ── 网格 ──
        pen_grid = QPen(QColor(235, 235, 235), 0.5)
        gs = 1000
        for gx in range(int(world_min_x // gs) * gs, int(world_max_x) + gs, gs):
            self._scene.addLine(sx(gx), 0, sx(gx), scene_h, pen_grid).setZValue(0)
        for gy in range(-1000, int(world_max_y) + 2000, 1000):
            self._scene.addLine(0, sy(gy), scene_w, sy(gy), pen_grid).setZValue(0)

        # ── 中心线 ──
        pen_center = QPen(QColor(200, 200, 200), 1.0, Qt.PenStyle.DashLine)
        self._scene.addLine(sx(0), 0, sx(0), scene_h, pen_center).setZValue(0)

        # ── 地面 ──
        pen_ground = QPen(self.COL_GROUND, 3)
        self._scene.addLine(sx(world_min_x), sy(0), sx(world_max_x), sy(0), pen_ground).setZValue(1)
        self._scene.addRect(sx(world_min_x), sy(0), scene_w, sy(world_min_y) - sy(0),
                            QPen(Qt.PenStyle.NoPen), QBrush(QColor(139, 115, 85, 15))).setZValue(0)

        # ── 立柱 ──
        for i, cx in enumerate(p.col_positions):
            cname = p.col_names[i]
            is_drive = p.col_is_drive[i]
            inf_l = p.col_inf_left[i]
            inf_r = p.col_inf_right[i]
            cf = near_conflict(cx, 150)

            if is_drive:
                add_rect(cx - p.col_sec_w / 2, 0, p.col_sec_w, p.col_ht,
                         QColor(255, 200, 150) if cf else self.COL_DRIVE,
                         QColor(192, 57, 43) if cf else QColor(180, 90, 20), bw=2.0, z=3)
            else:
                add_rect(cx - inf_l, 0, inf_l + inf_r, p.col_ht,
                         QColor(100, 149, 200, 60), QColor(100, 149, 200, 30), bw=0.5, z=2)
                add_rect(cx - p.col_sec_w / 2, 0, p.col_sec_w, p.col_ht,
                         self.COL_COLUMN_E if cf else self.COL_COLUMN,
                         QColor(192, 57, 43) if cf else QColor(61, 79, 95), bw=1.5, z=3)
                if p.col_damping[i]:
                    damp_x = cx - inf_l + 5 if i < (p.col_cnt - 1) // 2 else cx + inf_r - 45
                    add_text(damp_x, p.col_ht + 40, "阻尼", size=8,
                             color=QColor(41, 128, 185), bold=True)

            ly = -180 if is_drive else -200
            lc = (QColor(192, 57, 43) if cf else
                  QColor(180, 90, 20) if is_drive else QColor(44, 62, 80))
            add_text(cx, ly, f"{cname}\nX={cx:.0f}", size=9, color=lc, bold=is_drive)

        # ── 立柱间距标注 ──
        if p.col_cnt >= 2:
            dim_top = -60
            dim_line_y = -200
            dim_text_y = -230
            ext_bot = -280
            pen_ext = QPen(QColor(140, 140, 140), 0.6)
            pen_dim_line = QPen(QColor(100, 100, 100), 1.0)
            tick_h = 50
            for i in range(p.col_cnt - 1):
                x1 = p.col_positions[i]
                x2 = p.col_positions[i + 1]
                mid = (x1 + x2) / 2
                dist = x2 - x1
                self._scene.addLine(sx(x1), sy(dim_top), sx(x1), sy(ext_bot), pen_ext).setZValue(19)
                self._scene.addLine(sx(x2), sy(dim_top), sx(x2), sy(ext_bot), pen_ext).setZValue(19)
                self._scene.addLine(sx(x1), sy(dim_line_y), sx(x2), sy(dim_line_y),
                                    pen_dim_line).setZValue(19)
                for gx, dx in [(x1, 1), (x2, -1)]:
                    self._scene.addLine(sx(gx), sy(dim_line_y),
                                        sx(gx + dx * tick_h), sy(dim_line_y - tick_h),
                                        pen_dim_line).setZValue(19)
                    self._scene.addLine(sx(gx), sy(dim_line_y),
                                        sx(gx + dx * tick_h), sy(dim_line_y + tick_h),
                                        pen_dim_line).setZValue(19)
                add_text(mid, dim_text_y, f"{dist:.0f}", size=500, color=QColor(60, 60, 60), bold=True)

        # ── 主梁段 ──
        beam_bot = p.col_ht
        seg_colors = {"F": self.COL_BEAM, "S": self.COL_BEAM_S}
        for seg_idx, (start, end, stype) in enumerate(p.beam_edges):
            w = end - start
            seg_color = seg_colors.get(stype, self.COL_BEAM)
            add_rect(start, beam_bot, w, p.beam_sec_h if hasattr(p, 'beam_sec_h') else 150,
                     seg_color, QColor(42, 82, 152), bw=1.5, z=4)
            mid_x = (start + end) / 2
            seg_num = seg_idx + 1
            lbl = f"梁{seg_num}({stype})\n{abs(w):.0f}"
            add_text(mid_x, beam_bot + 20, lbl, size=8, color=QColor(255, 255, 255), bold=True)

        # ── 主梁连接件 ──
        for i, sx_pos in enumerate(p.splice_positions):
            cf = near_conflict(sx_pos, 200)
            s_bot = beam_bot - (p.splice_h - p.beam_sec_h) / 2 if hasattr(p, 'beam_sec_h') else beam_bot
            # 干涉范围半透明
            add_rect(sx_pos - p.splice_inf_half, s_bot, p.splice_inf_half * 2, p.splice_h,
                     QColor(240, 147, 43, 60) if cf else QColor(240, 147, 43, 40),
                     QColor(192, 57, 43) if cf else QColor(192, 114, 30), bw=1.2, z=5)
            # 连接件实体
            add_rect(sx_pos - p.beam_telescope / 2, s_bot, p.beam_telescope, p.splice_h,
                     self.COL_SPLICE_E if cf else self.COL_SPLICE,
                     QColor(192, 57, 43) if cf else QColor(192, 114, 30), bw=1.8, z=6)
            add_text(sx_pos, s_bot + p.splice_h / 2, f"连接{i + 1}", size=7,
                     color=QColor("white"), bold=True, rotate=90)

        # ── 檩条 ──
        purlin_bot = beam_bot + 150  # beam_sec_h default
        tp = len(p.purlin_positions)
        for i, px_pos in enumerate(p.purlin_positions):
            cf = near_conflict(px_pos, 100)
            add_rect(px_pos - p.purlin_w / 2, purlin_bot, p.purlin_w, p.purlin_h,
                     self.COL_PURLIN_E if cf else self.COL_PURLIN,
                     QColor(231, 76, 60) if cf else QColor(107, 123, 141), bw=1.5, z=6)
            if tp <= 15 or i % max(1, tp // 12) == 0:
                add_text(px_pos, purlin_bot + p.purlin_h + 35, f"檩{i + 1}", size=7,
                         color=QColor(85, 85, 85), rotate=90)

        # ── 组件 ──
        panel_bot = purlin_bot + p.purlin_h
        for pi, px_left in enumerate(p.panel_left_edges):
            add_rect(px_left, panel_bot, p.panel_wid, p.panel_thk,
                     self.COL_PANEL, QColor(47, 84, 150), bw=1, z=7)
            tp2 = len(p.panel_left_edges)
            if tp2 <= 20 or pi % max(1, tp2 // 10) == 0:
                add_text(px_left + p.panel_wid / 2, panel_bot + p.panel_thk / 2,
                         f"{pi + 1}", size=8, color=QColor(44, 62, 80))

        # ── 主梁总长标注（最上方） ──
        panel_top = panel_bot + p.panel_thk
        if p.beam_edges:
            bl = p.beam_edges[0][0]
            br = p.beam_edges[-1][1]
            btot_y = panel_top + 1250
            btot_text_y = panel_top + 1200
            pen_btot = QPen(QColor(50, 70, 130), 1.5)
            self._scene.addLine(sx(bl), sy(btot_y), sx(br), sy(btot_y), pen_btot).setZValue(19)
            for gx, dx in [(bl, 1), (br, -1)]:
                self._scene.addLine(sx(gx), sy(btot_y),
                                    sx(gx + dx * 50), sy(btot_y - 50), pen_btot).setZValue(19)
                self._scene.addLine(sx(gx), sy(btot_y),
                                    sx(gx + dx * 50), sy(btot_y + 50), pen_btot).setZValue(19)
            add_text((bl + br) / 2, btot_text_y,
                     f"主梁总长={abs(br - bl):.0f}", size=500,
                     color=QColor(50, 70, 130), bold=True)

        # ── 主梁各段长度标注（总长上方） ──
        if p.beam_edges:
            bdim_line_y = panel_top + 400
            bdim_text_y = panel_top + 350
            bdim_ext_top = panel_top + 150
            bdim_ext_bot = panel_top + 500
            for seg_idx, (start, end, stype) in enumerate(p.beam_edges):
                w = abs(end - start)
                mid = (start + end) / 2
                pen_ext_b = QPen(QColor(140, 160, 200), 0.6)
                self._scene.addLine(sx(start), sy(bdim_ext_top), sx(start), sy(bdim_ext_bot),
                                    pen_ext_b).setZValue(19)
                self._scene.addLine(sx(end), sy(bdim_ext_top), sx(end), sy(bdim_ext_bot),
                                    pen_ext_b).setZValue(19)
                pen_bdim = QPen(QColor(80, 100, 160), 1.0)
                self._scene.addLine(sx(start), sy(bdim_line_y), sx(end), sy(bdim_line_y),
                                    pen_bdim).setZValue(19)
                tick_h = 40
                for gx, dx in [(start, 1), (end, -1)]:
                    self._scene.addLine(sx(gx), sy(bdim_line_y),
                                        sx(gx + dx * tick_h), sy(bdim_line_y - tick_h),
                                        pen_bdim).setZValue(19)
                    self._scene.addLine(sx(gx), sy(bdim_line_y),
                                        sx(gx + dx * tick_h), sy(bdim_line_y + tick_h),
                                        pen_bdim).setZValue(19)
                add_text(mid, bdim_text_y, f"{w:.0f}", size=500,
                         color=QColor(50, 70, 130), bold=True)

        # ── 回转间隙（最上方） ──
        gh = p.rotation_gap / 2.0
        rot_dim_y = panel_top + 600
        rot_text_y = panel_top + 550
        rot_ext_top = panel_top + 700
        rot_ext_bot = panel_top + 200
        for gx in [-gh, gh]:
            self._scene.addLine(sx(gx), sy(rot_ext_top), sx(gx), sy(rot_ext_bot),
                                QPen(QColor(230, 126, 34, 150), 0.6)).setZValue(19)
        self._scene.addLine(sx(-gh), sy(rot_dim_y), sx(gh), sy(rot_dim_y),
                            QPen(QColor(230, 126, 34), 1.2)).setZValue(19)
        tick_h = 50
        for gx, dx in [(-gh, 1), (gh, -1)]:
            self._scene.addLine(sx(gx), sy(rot_dim_y),
                                sx(gx + dx * tick_h), sy(rot_dim_y - tick_h),
                                QPen(QColor(230, 126, 34), 1.2)).setZValue(19)
            self._scene.addLine(sx(gx), sy(rot_dim_y),
                                sx(gx + dx * tick_h), sy(rot_dim_y + tick_h),
                                QPen(QColor(230, 126, 34), 1.2)).setZValue(19)
        add_text(0, rot_text_y, f"{p.rotation_gap:.0f}", size=500,
                 color=QColor(230, 126, 34), bold=True)

        # ── 干涉标记 ──
        drawn = set()
        for iss in issues:
            if iss.level != "critical":
                continue
            key = round(iss.x, -1)
            if key in drawn:
                continue
            drawn.add(key)
            pen_cf = QPen(QColor(231, 76, 60), 2.5, Qt.PenStyle.DashLine)
            self._scene.addLine(sx(iss.x), sy(world_min_y + 100),
                                sx(iss.x), sy(world_max_y - 100), pen_cf).setZValue(15)
            lx = sx(iss.x)
            ly = sy(world_max_y - 200)
            self._scene.addRect(lx - 35, ly - 12, 70, 24,
                                QPen(QColor(231, 76, 60), 1.5),
                                QBrush(QColor(255, 234, 234))).setZValue(16)
            add_text(iss.x, world_max_y - 200, "!! 干涉", size=10,
                     color=QColor(231, 76, 60), bold=True)

        # ── 图例 ──
        lx0, ly0 = 15, 15
        items = [
            (self.COL_DRIVE, "驱动柱"), (self.COL_COLUMN, "非驱动柱"),
            (QColor(100, 149, 200, 80), "阻尼柱范围"),
            (self.COL_BEAM, "主梁(F)"), (self.COL_BEAM_S, "主梁(S)"),
            (self.COL_SPLICE, "连接件"), (self.COL_PURLIN, "檩条"),
            (self.COL_PANEL, "组件"), (QColor(231, 76, 60), "干涉"),
        ]
        for i, (clr, lbl) in enumerate(items):
            ci, ri = i % 4, i // 4
            self._scene.addRect(lx0 + ci * 110, ly0 + ri * 20, 14, 12,
                                QPen(clr.darker(120), 1), QBrush(clr)).setZValue(18)
            t = self._scene.addSimpleText(lbl, QFont("Microsoft YaHei", 8))
            t.setBrush(QBrush(QColor(60, 60, 60)))
            t.setPos(lx0 + ci * 110 + 18, ly0 + ri * 20 - 1)
            t.setZValue(18)

        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_level = self.transform().m11()


# ═══════════════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════════════

def export_scr(p: PVParams, filepath: str):
    L = []
    L.append("; 光伏跟踪支架 - 正视图 AutoCAD 脚本")
    L.append(f"; 生成: {date.today().isoformat()}")
    L.append(f"; 组件: {p.panel_len}×{p.panel_wid}×{p.panel_thk}mm 间隙:{p.panel_gap:.1f}")
    L.append(f"; 总组件数:{p.panel_cnt_total}(左{p.left_panel_cnt}+右{p.right_panel_cnt}) 回转间隙:{p.rotation_gap:.0f}")
    L.append(f"; 立柱:{p.col_cnt}根(驱动柱×1+非驱动柱{p.col_cnt-1}根)")
    L.append(f"; 主梁段:{len(p.beam_segments)}段 连接件:{len(p.splice_positions)}处")
    L.append(f"; 总跨度:{p.total_span:.0f}mm 原点=驱动柱中心")
    L.append("")
    L.append("_-LAYER _M GROUND   _C 52  \"\" \"\"")
    L.append("_-LAYER _M COLUMN   _C 252 \"\" \"\"")
    L.append("_-LAYER _M BEAM     _C 140 \"\" \"\"")
    L.append("_-LAYER _M BEAM_S   _C 170 \"\" \"\"")
    L.append("_-LAYER _M SPLICE   _C 30  \"\" \"\"")
    L.append("_-LAYER _M PURLIN   _C 8   \"\" \"\"")
    L.append("_-LAYER _M PANEL    _C 150 \"\" \"\"")
    L.append("")
    L.append("_-LAYER _S GROUND")
    L.append(f"_LINE {p.left_edge - 500:.0f},{0} {p.right_edge + 500:.0f},{0}")
    L.append("")
    L.append("_-LAYER _S COLUMN")
    for i, cx in enumerate(p.col_positions):
        damp = " [阻尼]" if p.col_damping[i] else ""
        L.append(f"_RECTANG {cx - p.col_sec_w / 2:.0f},{0} "
                 f"{cx + p.col_sec_w / 2:.0f},{p.col_ht:.0f}  ; {p.col_names[i]}{damp}")
    L.append("")
    for seg_idx, (start, end, stype) in enumerate(p.beam_edges):
        layer = "BEAM" if stype == "F" else "BEAM_S"
        L.append(f"_-LAYER _S {layer}")
        L.append(f"_RECTANG {start:.0f},{p.col_ht:.0f} {end:.0f},{p.col_ht + 150:.0f}  ; 主梁段{seg_idx + 1}({stype})")
    L.append("")
    L.append("_-LAYER _S SPLICE")
    for i, sx in enumerate(p.splice_positions):
        s_bot = p.col_ht - (p.splice_h - 150) / 2
        L.append(f"_RECTANG {sx - p.beam_telescope / 2:.0f},{s_bot:.0f} "
                 f"{sx + p.beam_telescope / 2:.0f},{s_bot + p.splice_h:.0f}  ; 连接件{i + 1}")
    L.append("")
    pb = p.col_ht + 150
    L.append("_-LAYER _S PURLIN")
    for i, px in enumerate(p.purlin_positions):
        L.append(f"_RECTANG {px - p.purlin_w / 2:.0f},{pb:.0f} "
                 f"{px + p.purlin_w / 2:.0f},{pb + p.purlin_h:.0f}  ; 檩条{i + 1}")
    L.append("")
    pb2 = pb + p.purlin_h
    L.append("_-LAYER _S PANEL")
    for pi, pxl in enumerate(p.panel_left_edges):
        L.append(f"_RECTANG {pxl:.0f},{pb2:.0f} "
                 f"{pxl + p.panel_wid:.0f},{pb2 + p.panel_thk:.0f}  ; 组件{pi + 1}")
    L.append("")
    L.append("_ZOOM _EXTENTS\n_REGEN\n; === 脚本结束 ===")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\r\n".join(L))


def export_csv(p: PVParams, filepath: str):
    rows = []
    w = rows.append
    w(["参数", "数值", "单位"])
    w(["组件长度", p.panel_len, "mm"])
    w(["组件宽度", p.panel_wid, "mm"])
    w(["组件厚度", p.panel_thk, "mm"])
    w(["孔间距", f"{p.hole_spacing:.1f}", "mm"])
    w(["组件间隙", f"{p.panel_gap:.1f}", "mm"])
    w(["总组件数", p.panel_cnt_total, "块"])
    w(["左/右组件", f"{p.left_panel_cnt}/{p.right_panel_cnt}", "块"])
    w(["回转间隙", f"{p.rotation_gap:.0f}", "mm"])
    w(["总跨度", f"{p.total_span:.0f}", "mm"])
    w(["立柱总数", p.col_cnt, "根"])
    w(["立柱高度", p.col_ht, "mm"])
    w(["立柱截面宽", p.col_sec_w, "mm"])
    w(["主梁段数", len(p.beam_segments), "段"])
    w(["主梁总长", f"{p.beam_len_total():.0f}", "mm"])
    w(["缩管长度", p.beam_telescope, "mm"])
    w(["连接件数量", len(p.splice_positions), "处"])
    w(["连接件干涉半宽", p.splice_inf_half, "mm"])
    w(["檩条总数", len(p.purlin_positions), "根"])
    w([])
    w(["立柱", "命名", "X(mm)", "阻尼", "干涉L", "干涉R", "下一距(mm)"])
    for i, cx in enumerate(p.col_positions):
        nd = p.col_spacings[i + 1] if i + 1 < len(p.col_spacings) else 0
        w([f"柱{i + 1}", p.col_names[i], f"{cx:.0f}", "是" if p.col_damping[i] else "否",
           f"{p.col_inf_left[i]:.0f}", f"{p.col_inf_right[i]:.0f}", f"{nd:.0f}"])
    w([])
    w(["主梁段", "起点X", "终点X", "长度", "类型"])
    for i, (start, end, stype) in enumerate(p.beam_edges):
        w([f"段{i + 1}", f"{start:.0f}", f"{end:.0f}", f"{abs(end - start):.0f}", stype])
    w([])
    w(["连接件", "X(mm)"])
    for i, sx in enumerate(p.splice_positions):
        w([f"连接件{i + 1}", f"{sx:.0f}"])
    w([])
    w(["檩条", "侧", "X(mm)", "间距(mm)"])
    for i, px in enumerate(p.purlin_positions):
        sd = "左" if px < 0 else ("中" if px == 0 else "右")
        sp = f"{px - p.purlin_positions[i - 1]:.0f}" if i > 0 else "-"
        w([f"檩条{i + 1}", sd, f"{px:.0f}", sp])
    w([])
    w(["组件", "侧", "左边缘X", "右边缘X"])
    for pi, pxl in enumerate(p.panel_left_edges):
        sd = "左" if pxl < 0 else "右"
        w([f"组件{pi + 1}", sd, f"{pxl:.0f}", f"{pxl + p.panel_wid:.0f}"])
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)


# ═══════════════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════════════

class ParamRow(QWidget):
    def __init__(self, label, widget, unit="", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        lb = QLabel(label)
        lb.setFixedWidth(110)
        lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lb.setStyleSheet("font-size:12px; color:#555;")
        layout.addWidget(lb)
        layout.addWidget(widget)
        if unit:
            ul = QLabel(unit)
            ul.setFixedWidth(32)
            ul.setStyleSheet("font-size:11px; color:#999;")
            layout.addWidget(ul)


class ParamPanel(QScrollArea):
    param_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(390)
        self.setMaximumWidth(450)

        container = QWidget()
        self.setWidget(container)
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setSpacing(8)

        self._updating_gap_hole = False
        self._rebuilding_col_table = False
        self._rebuilding_beam_table = False
        self._auto_designing = False
        self._panel_locked = False

        self._create_panel_widgets()
        self._create_array_widgets()
        self._create_column_widgets()
        self._create_beam_widgets()
        self._create_status_widgets()
        self._create_export_buttons()

        self.main_layout.addStretch()
        self._wire_signals()

    # ── helpers ──
    def _add_group(self, title):
        grp = QGroupBox(title)
        grp.setStyleSheet(
            "QGroupBox { font-weight:bold; font-size:12px; color:#1a3a5c; "
            "border:1px solid #dcdde1; border-radius:6px; margin-top:10px; padding-top:14px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; }")
        grp.setLayout(QVBoxLayout())
        grp.layout().setSpacing(4)
        self.main_layout.addWidget(grp)
        return grp

    def _dspin(self, lo, hi, val, step):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setSingleStep(step)
        sp.setDecimals(1)
        sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sp.wheelEvent = lambda e: e.ignore()
        sp.setStyleSheet("QDoubleSpinBox { padding:3px; font-size:12px; }")
        return sp

    def _spin(self, lo, hi, val):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sp.wheelEvent = lambda e: e.ignore()
        sp.setStyleSheet("QSpinBox { padding:3px; font-size:12px; }")
        return sp

    def _row(self, grp, label, widget, unit):
        row = ParamRow(label, widget, unit)
        grp.layout().addWidget(row)
        return row

    def _row_cb(self, grp, label, widget):
        if label:
            rw = QWidget()
            lay = QHBoxLayout(rw)
            lay.setContentsMargins(0, 0, 0, 0)
            lb = QLabel(label)
            lb.setFixedWidth(110)
            lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lb.setStyleSheet("font-size:12px; color:#555;")
            lay.addWidget(lb)
            lay.addWidget(widget)
            lay.addStretch()
            grp.layout().addWidget(rw)
        else:
            rw = QWidget()
            lay = QHBoxLayout(rw)
            lay.setContentsMargins(114, 0, 0, 0)
            lay.addWidget(widget)
            lay.addStretch()
            grp.layout().addWidget(rw)
        return rw

    def _add_hint(self, grp, text):
        lb = QLabel(text)
        lb.setStyleSheet("font-size:10px; color:#999; padding-left:114px; font-style:italic;")
        grp.layout().addWidget(lb)

    def _btn_style(self, bg, fg):
        return (f"QPushButton {{ background:{bg}; color:{fg}; padding:6px; "
                f"border:none; border-radius:5px; font-weight:bold; font-size:12px; }}"
                f"QPushButton:hover {{ opacity:0.85; }}")

    def _table_height(self, table, n_rows, row_h=26):
        h = table.horizontalHeader().height() + n_rows * row_h + 4
        table.setMinimumHeight(h)
        table.setMaximumHeight(h)

    # ── 组件 ──
    def _create_panel_widgets(self):
        grp = self._add_group("📐 组件参数")
        self.panel_len = self._dspin(10, 99999, D["panel_len"], 10)
        self.panel_wid = self._dspin(10, 99999, D["panel_wid"], 10)
        self.panel_thk = self._dspin(5, 500, D["panel_thk"], 1)
        self.hole_spacing = self._dspin(100, 5000, D["hole_spacing"], 1)
        self.panel_gap = self._dspin(-500, 500, D["panel_gap"], 1)
        self._row(grp, "组件长度", self.panel_len, "mm")
        self._row(grp, "组件宽度", self.panel_wid, "mm")
        self._row(grp, "组件厚度", self.panel_thk, "mm")
        self._row(grp, "孔间距", self.hole_spacing, "mm")
        self._row(grp, "组件间隙", self.panel_gap, "mm")
        self._add_hint(grp, "间隙 = 57 − 宽度 + 孔间距，二者联动")

        self.btn_confirm_panel = QPushButton("🔒 确认组件参数（锁定编辑）")
        self.btn_confirm_panel.setStyleSheet(
            "QPushButton { background:#2980b9; color:#fff; padding:6px; "
            "border:none; border-radius:5px; font-weight:bold; font-size:12px; }"
            "QPushButton:hover { background:#1a6daa; }")
        grp.layout().addWidget(self.btn_confirm_panel)

    # ── 阵列 ──
    def _create_array_widgets(self):
        grp = self._add_group("🔄 阵列排列")
        self.panel_cnt_total = self._spin(1, 500, D["panel_cnt_total"])
        self.rotation_gap = self._dspin(0, 99999, D["rotation_gap"], 10)
        self.left_cnt_auto = QCheckBox("自动分配左侧组件数")
        self.left_cnt_auto.setChecked(D["left_cnt_auto"])
        self.left_panel_cnt = self._spin(0, 500, D["left_panel_cnt"])
        self.right_cnt_auto = QCheckBox("自动分配右侧组件数")
        self.right_cnt_auto.setChecked(D["right_cnt_auto"])
        self.right_panel_cnt = self._spin(0, 500, D["right_panel_cnt"])
        self._row(grp, "组件总数", self.panel_cnt_total, "块")
        self._row(grp, "回转间隙", self.rotation_gap, "mm")
        self._row_cb(grp, "", self.left_cnt_auto)
        self._row(grp, "左侧组件", self.left_panel_cnt, "块")
        self._row_cb(grp, "", self.right_cnt_auto)
        self._row(grp, "右侧组件", self.right_panel_cnt, "块")
        self._add_hint(grp, "偶数→左右对称；奇数→左少右多")

        # 阻尼器对数（锁定阵列后可设）
        self.damping_pairs = QComboBox()
        self.damping_pairs.addItems(["1对", "2对", "3对", "4对"])
        self.damping_pairs.setCurrentIndex(0)
        self.damping_label = QLabel("→ 末端第1根")
        self.damping_label.setStyleSheet("font-size:11px; color:#2980b9; font-weight:bold;")

        damp_row = QWidget()
        damp_lay = QHBoxLayout(damp_row)
        damp_lay.setContentsMargins(0, 0, 0, 0)
        damp_lbl = QLabel("阻尼器对数")
        damp_lbl.setFixedWidth(110)
        damp_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        damp_lbl.setStyleSheet("font-size:12px; color:#555;")
        damp_lay.addWidget(damp_lbl)
        damp_lay.addWidget(self.damping_pairs)
        damp_lay.addWidget(self.damping_label)
        damp_lay.addStretch()
        grp.layout().addWidget(damp_row)

        # 3~4对时的手动位置选择面板
        self.damping_manual_panel = QWidget()
        dml = QHBoxLayout(self.damping_manual_panel)
        dml.setContentsMargins(114, 0, 0, 0)
        dml.addWidget(QLabel("阻尼位置:"))
        self.damping_pos_checks = []
        for pos in range(1, 6):  # 末端第1~5根
            cb = QCheckBox(str(pos))
            cb.setChecked(pos <= 1)
            cb.setEnabled(False)
            cb.toggled.connect(self._emit_change)
            self.damping_pos_checks.append(cb)
            dml.addWidget(cb)
        dml.addStretch()
        grp.layout().addWidget(self.damping_manual_panel)

        def on_damping_change(i):
            cnt = i + 1
            if cnt <= 2:
                self.damping_label.setText(f"→ 末端第1~{cnt}根 （自动设计用）")
                self.damping_manual_panel.setVisible(False)
            else:
                self.damping_label.setText("→ 手动选择位置: （自动设计用）")
                self.damping_manual_panel.setVisible(True)
                for j, cb in enumerate(self.damping_pos_checks):
                    cb.setEnabled(True)
                    cb.setChecked(j < cnt)
        self.damping_pairs.currentIndexChanged.connect(on_damping_change)
        on_damping_change(0)

    # ── 立柱 ──
    def _create_column_widgets(self):
        grp = self._add_group("🏛️ 立柱参数")
        self.col_cnt = self._spin(1, 51, D["col_cnt"])
        self.col_cnt.setSingleStep(2)
        self._row(grp, "立柱总数", self.col_cnt, "根")

        self.btn_auto_col = QPushButton("🔧 自动布置立柱")
        self.btn_auto_col.setStyleSheet(
            "QPushButton { background:#27ae60; color:#fff; padding:6px; "
            "border:none; border-radius:5px; font-weight:bold; font-size:12px; }"
            "QPushButton:hover { background:#219a52; }")
        grp.layout().addWidget(self.btn_auto_col)

        self._add_hint(grp, "驱动柱固定在中间(奇数)，其余非驱动柱")
        self._add_hint(grp, "高度1500mm/截面宽100mm/阻尼远离侧240mm靠近侧100mm")

        tbl_label = QLabel("立柱间距表 (mm)：")
        tbl_label.setStyleSheet("font-weight:bold; font-size:11px; color:#1a3a5c; padding-left:4px;")
        grp.layout().addWidget(tbl_label)

        self.col_table = QTableWidget()
        self.col_table.setColumnCount(4)
        self.col_table.setHorizontalHeaderLabels(["间距 mm", "编号", "命名", "阻尼柱"])
        self.col_table.horizontalHeader().setStretchLastSection(True)
        self.col_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci, cw in [(1, 40), (2, 100), (3, 55)]:
            self.col_table.horizontalHeader().setSectionResizeMode(ci, QHeaderView.ResizeMode.Fixed)
            self.col_table.setColumnWidth(ci, cw)
        self.col_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.col_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.col_table.setStyleSheet("QTableWidget { font-size:11px; }")
        # 表格由 MainWindow 放置到底部面板
        self._col_hint1 = "首行=左参考→柱1 / 末行=柱N→右参考 / 驱动柱固定在X=0"
        self._add_hint(grp, self._col_hint1)

    # ── 主梁 ──
    def _create_beam_widgets(self):
        grp = self._add_group("🛠️ 主梁 & 连接件")
        self.beam_seg_cnt = self._spin(2, 50, len(DEFAULT_BEAM_SEGMENTS))
        self.beam_seg_cnt.setSingleStep(2)
        self._row(grp, "主梁段数", self.beam_seg_cnt, "段")
        self._add_hint(grp, "中心距±77.5mm / 缩管260mm / 连接件干涉±180mm")

        tbl_label = QLabel("主梁段长度表 (mm, 从左到右)：")
        tbl_label.setStyleSheet("font-weight:bold; font-size:11px; color:#1a3a5c; padding-left:4px;")
        grp.layout().addWidget(tbl_label)

        self.beam_table = QTableWidget()
        self.beam_table.setColumnCount(3)
        self.beam_table.setHorizontalHeaderLabels(["长度 mm", "编号", "类型(F/S)"])
        self.beam_table.horizontalHeader().setStretchLastSection(True)
        self.beam_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci, cw in [(1, 40), (2, 70)]:
            self.beam_table.horizontalHeader().setSectionResizeMode(ci, QHeaderView.ResizeMode.Fixed)
            self.beam_table.setColumnWidth(ci, cw)
        self.beam_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.beam_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.beam_table.setStyleSheet("QTableWidget { font-size:11px; }")
        # 表格由 MainWindow 放置到底部面板
        self._add_hint(grp, "中间两根=F(无缩管), 其余=S(缩管260mm套入前段)")
        self._add_hint(grp, "连接件中心=重叠区中点, 干涉范围±180mm")

        self.col_spacing_min = self._dspin(0, 20000, D["col_spacing_min"], 100)
        self.col_spacing_max = self._dspin(0, 20000, D["col_spacing_max"], 100)

    # ── 状态 ──
    def _create_status_widgets(self):
        grp = self._add_group("🔍 干涉检查结果")
        self.status_list = QListWidget()
        self.status_list.setMaximumHeight(160)
        self.status_list.setStyleSheet("QListWidget { border: none; font-size: 11px; }")
        grp.layout().addWidget(self.status_list)

    # ── 导出 ──
    def _create_export_buttons(self):
        bl = QHBoxLayout()
        self.btn_scr = QPushButton("📄 导出 .scr")
        self.btn_scr.setStyleSheet(self._btn_style("#2980b9", "#fff"))
        self.btn_csv = QPushButton("📊 导出 .csv")
        self.btn_csv.setStyleSheet(self._btn_style("#27ae60", "#fff"))
        bl.addWidget(self.btn_scr)
        bl.addWidget(self.btn_csv)
        self.main_layout.addLayout(bl)

    # ── 表格构建 ──
    def _rebuild_col_table(self, cnt, spacings, damping, total_span):
        self._rebuilding_col_table = True
        nr = cnt + 1
        self.col_table.setRowCount(nr)
        lc = (cnt - 1) // 2
        for row in range(nr):
            sp = QDoubleSpinBox()
            sp.setRange(0, 999999)
            sp.setDecimals(0)
            sp.setSingleStep(100)
            sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            sp.wheelEvent = lambda e: e.ignore()
            sp.setValue(spacings[row] if row < len(spacings) else
                        (total_span / nr if nr > 0 and total_span > 0 else 2000))
            sp.valueChanged.connect(self._emit_change)
            self.col_table.setCellWidget(row, 0, sp)

            if row < cnt:
                lbl_num = QLabel(str(row + 1))
                lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl_num.setStyleSheet("font-size:11px;")
                self.col_table.setCellWidget(row, 1, lbl_num)

                if row == lc:
                    name = "驱动柱"
                    sty = "font-size:10px; font-weight:bold; color:#c0392b;"
                elif row < lc:
                    name = f"非驱动柱左{lc - row}"
                    sty = "font-size:10px; color:#555;"
                else:
                    name = f"非驱动柱右{row - lc}"
                    sty = "font-size:10px; color:#555;"
                lbl_name = QLabel(name)
                lbl_name.setStyleSheet(sty)
                self.col_table.setCellWidget(row, 2, lbl_name)

                cb = QCheckBox()
                if row < len(damping):
                    cb.setChecked(damping[row])
                if row == lc:
                    cb.setEnabled(False)
                else:
                    cb.toggled.connect(self._emit_change)
                self.col_table.setCellWidget(row, 3, cb)
            else:
                for ci in range(1, 4):
                    self.col_table.removeCellWidget(row, ci)

        self._table_height(self.col_table, nr)
        self._rebuilding_col_table = False

    def _rebuild_beam_table(self, n_seg, segments, types):
        self._rebuilding_beam_table = True
        self.beam_table.setRowCount(n_seg)
        mid = n_seg // 2
        for row in range(n_seg):
            sp = QDoubleSpinBox()
            sp.setRange(100, 999999)
            sp.setDecimals(0)
            sp.setSingleStep(100)
            sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            sp.wheelEvent = lambda e: e.ignore()
            sp.setValue(segments[row] if row < len(segments) else 10000)
            sp.valueChanged.connect(self._emit_change)
            self.beam_table.setCellWidget(row, 0, sp)

            lbl_num = QLabel(str(row + 1))
            lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_num.setStyleSheet("font-size:11px;")
            self.beam_table.setCellWidget(row, 1, lbl_num)

            auto_type = "F" if (row == mid - 1 or row == mid) else "S"
            cmb = QComboBox()
            cmb.addItems(["F", "S"])
            cmb.setCurrentText(types[row] if row < len(types) else auto_type)
            cmb.currentTextChanged.connect(self._emit_change)
            self.beam_table.setCellWidget(row, 2, cmb)

        self._table_height(self.beam_table, n_seg)
        self._rebuilding_beam_table = False

    # ── 信号 ──
    def _wire_signals(self):
        # 非组件参数 — 自动触发更新
        widgets = [
            self.panel_cnt_total, self.rotation_gap,
            self.left_panel_cnt, self.right_panel_cnt,
            self.beam_seg_cnt,
            self.col_spacing_min, self.col_spacing_max,
        ]
        for w in widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self._emit_change)

        # 组件参数 — 仅联动，不自动触发
        self.panel_len.valueChanged.connect(lambda: None)  # 静默
        self.panel_wid.valueChanged.connect(lambda: None)
        self.panel_thk.valueChanged.connect(lambda: None)

        self.hole_spacing.valueChanged.connect(self._on_hole_spacing_changed)
        self.panel_gap.valueChanged.connect(self._on_panel_gap_changed)
        self.col_cnt.valueChanged.connect(self._on_col_cnt_changed)
        self.beam_seg_cnt.valueChanged.connect(self._on_beam_seg_cnt_changed)

        self.left_cnt_auto.toggled.connect(self._emit_change)
        self.right_cnt_auto.toggled.connect(self._emit_change)
        self.damping_pairs.currentIndexChanged.connect(self._emit_change)
        self.btn_auto_col.clicked.connect(self._on_auto_col)
        self.btn_confirm_panel.clicked.connect(self._on_confirm_panel)

    def _set_panel_locked(self, locked: bool):
        """锁定/解锁组件参数编辑"""
        self._panel_locked = locked
        for w in [self.panel_len, self.panel_wid, self.panel_thk,
                  self.hole_spacing, self.panel_gap]:
            w.setDisabled(locked)
            if locked:
                w.setStyleSheet(
                    "QDoubleSpinBox { padding:3px; font-size:12px; "
                    "background:#f0f0f0; color:#888; border:1px solid #ddd; border-radius:3px; }")
            else:
                w.setStyleSheet("QDoubleSpinBox { padding:3px; font-size:12px; }")

        if locked:
            self.btn_confirm_panel.setText("🔓 解锁组件参数（重新编辑）")
            self.btn_confirm_panel.setStyleSheet(
                "QPushButton { background:#e67e22; color:#fff; padding:6px; "
                "border:none; border-radius:5px; font-weight:bold; font-size:12px; }"
                "QPushButton:hover { background:#d35400; }")
        else:
            self.btn_confirm_panel.setText("🔒 确认组件参数（锁定编辑）")
            self.btn_confirm_panel.setStyleSheet(
                "QPushButton { background:#2980b9; color:#fff; padding:6px; "
                "border:none; border-radius:5px; font-weight:bold; font-size:12px; }"
                "QPushButton:hover { background:#1a6daa; }")

    def _on_confirm_panel(self):
        """切换组件参数锁定状态"""
        self._set_panel_locked(not self._panel_locked)
        if self._panel_locked:
            self._emit_change()  # 锁定后触发一次计算

    def _on_hole_spacing_changed(self, val):
        if self._updating_gap_hole:
            return
        self._updating_gap_hole = True
        self.panel_gap.setValue(round(PURLIN_GAP_CONSTANT - self.panel_wid.value() + val, 1))
        self._updating_gap_hole = False

    def _on_panel_gap_changed(self, val):
        if self._updating_gap_hole:
            return
        self._updating_gap_hole = True
        self.hole_spacing.setValue(round(val + self.panel_wid.value() - PURLIN_GAP_CONSTANT, 1))
        self._updating_gap_hole = False

    def _on_col_cnt_changed(self, val):
        if self._rebuilding_col_table or self._auto_designing:
            return
        if val % 2 == 0:
            self.col_cnt.setValue(val + 1)
            return
        try:
            p = self.build_params()
            ts = p.total_span
        except Exception:
            ts = 47000
        nr = val + 1
        eg = ts / nr if ts > 0 else 2000
        self._rebuild_col_table(val, [eg] * nr, [False] * val, ts)
        self._emit_change()

    def _on_beam_seg_cnt_changed(self, val):
        if self._rebuilding_beam_table:
            return
        if val % 2 != 0:
            self.beam_seg_cnt.setValue(val + 1)
            return
        n = val
        mid = n // 2
        segs = []
        typs = []
        for i in range(n):
            if i == mid - 1 or i == mid:
                segs.append(10600)
                typs.append("F")
            else:
                segs.append(11600)
                typs.append("S")
        self._rebuild_beam_table(n, segs, typs)
        self._emit_change()

    def _emit_change(self):
        if self._rebuilding_col_table or self._rebuilding_beam_table:
            return
        self.param_changed.emit(self.build_params())

    def build_params(self) -> PVParams:
        p = PVParams()
        p.panel_len = self.panel_len.value()
        p.panel_wid = self.panel_wid.value()
        p.panel_thk = self.panel_thk.value()
        p.hole_spacing = self.hole_spacing.value()
        p.panel_gap = self.panel_gap.value()

        p.panel_cnt_total = self.panel_cnt_total.value()
        p.rotation_gap = self.rotation_gap.value()
        p.left_cnt_auto = self.left_cnt_auto.isChecked()
        p.right_cnt_auto = self.right_cnt_auto.isChecked()
        p.left_panel_cnt = self.left_panel_cnt.value()
        p.right_panel_cnt = self.right_panel_cnt.value()

        p.col_cnt = self.col_cnt.value()
        p.col_ht = D["col_ht"]
        p.col_sec_w = D["col_sec_w"]
        # column spacings — 首次用默认值，之后从表格读取
        if self.col_table.rowCount() > 0:
            spacings = []
            for r in range(self.col_table.rowCount()):
                w = self.col_table.cellWidget(r, 0)
                spacings.append(w.value() if isinstance(w, QDoubleSpinBox) else 2000.0)
            p.col_spacings = spacings
            # 从表格读取阻尼（可与阵列区协同）
            damping = []
            for r in range(min(p.col_cnt, self.col_table.rowCount())):
                w = self.col_table.cellWidget(r, 3)
                damping.append(w.isChecked() if isinstance(w, QCheckBox) else False)
            if len(damping) != p.col_cnt:
                damping = [False] * p.col_cnt
            p.col_damping = damping

        p.purlin_w = D["purlin_w"]
        p.purlin_h = D["purlin_h"]
        p.purlin_influence = D["purlin_influence"]
        p.purlin_end_offset = D["purlin_end_offset"]

        p.beam_center_half = D["beam_center_half"]
        p.beam_telescope = D["beam_telescope"]
        p.splice_inf_half = D["splice_inf_half"]
        p.splice_h = D["splice_h"]
        # beam segments — 首次用默认值，之后从表格读取
        if self.beam_table.rowCount() > 0:
            segs = []
            typs = []
            for r in range(self.beam_table.rowCount()):
                w = self.beam_table.cellWidget(r, 0)
                segs.append(w.value() if isinstance(w, QDoubleSpinBox) else 10000)
                cb = self.beam_table.cellWidget(r, 2)
                typs.append(cb.currentText() if isinstance(cb, QComboBox) else "S")
            p.beam_segments = segs
            p.beam_segment_types_pre = typs  # store for manual override
        # beam_sec_h is fixed 150 for drawing
        p.beam_sec_h = 150.0

        p.col_spacing_min = self.col_spacing_min.value()
        p.col_spacing_max = self.col_spacing_max.value()
        p.derive()

        # Restore manual type overrides after derive auto-sets them
        if hasattr(p, 'beam_segment_types_pre') and len(p.beam_segment_types_pre) == len(p.beam_segment_types):
            p.beam_segment_types = list(p.beam_segment_types_pre)
        return p

    def update_ui_from_params(self, p: PVParams):
        self.left_panel_cnt.setDisabled(p.left_cnt_auto)
        self.right_panel_cnt.setDisabled(p.right_cnt_auto)
        if p.left_cnt_auto:
            self.left_panel_cnt.setValue(p.left_panel_cnt)
        if p.right_cnt_auto:
            self.right_panel_cnt.setValue(p.right_panel_cnt)

        # 立柱表格
        nr = p.col_cnt + 1
        if self.col_table.rowCount() != nr:
            self._rebuild_col_table(p.col_cnt, p.col_spacings, p.col_damping, p.total_span)
        else:
            for r in range(nr):
                w = self.col_table.cellWidget(r, 0)
                if isinstance(w, QDoubleSpinBox) and r < len(p.col_spacings):
                    w.setValue(p.col_spacings[r])
            for r in range(p.col_cnt):
                w = self.col_table.cellWidget(r, 3)
                if isinstance(w, QCheckBox) and r < len(p.col_damping):
                    w.setChecked(p.col_damping[r])

        # 主梁表格
        ns = len(p.beam_segments)
        if self.beam_table.rowCount() != ns:
            self._rebuild_beam_table(ns, p.beam_segments, p.beam_segment_types)
        else:
            for r in range(ns):
                w = self.beam_table.cellWidget(r, 0)
                if isinstance(w, QDoubleSpinBox) and r < len(p.beam_segments):
                    w.setValue(p.beam_segments[r])
                cb = self.beam_table.cellWidget(r, 2)
                if isinstance(cb, QComboBox) and r < len(p.beam_segment_types):
                    cb.setCurrentText(p.beam_segment_types[r])

    # ── 自动布置立柱 ──
    def _build_symmetric_spacings(self, n, gaps, half_left, half_right):
        """从单侧 gaps 构建对称 spacings 数组"""
        drive_idx = (n - 1) // 2
        side_count = drive_idx
        spacings = [0.0] * (n + 1)
        for j in range(side_count):
            g = round(gaps[j] / 100) * 100
            spacings[drive_idx + 1 + j] = g
            spacings[drive_idx - j] = g
        actual_half = sum(gaps) if side_count > 0 else 0
        spacings[0] = max(500, round((half_left - actual_half) / 100) * 100)
        spacings[n] = max(500, round((half_right - actual_half) / 100) * 100)
        return spacings, actual_half

    @staticmethod
    def _check_gap_range(spacings, n):
        """检查内部跨距（除末跨外）是否全部在 5000~8000"""
        interior = spacings[1:n]
        if len(interior) <= 1:
            return True
        for i, g in enumerate(interior):
            if i == 0 or i == len(interior) - 1:
                continue
            if g < 5000 or g > 8000:
                return False
        return True

    @staticmethod
    def _score_uniformity(spacings, n, issues):
        """评分函数：跨距方差 + 罚项，越低越好"""
        if any(iss.level == "critical" for iss in issues):
            return float('inf')
        interior = spacings[1:n]
        if not interior:
            return float('inf')
        mean_g = sum(interior) / len(interior)
        variance = sum((g - mean_g) ** 2 for g in interior) / len(interior)
        score = variance
        warns = sum(1 for iss in issues if iss.level == "warning")
        score += warns * 5000
        score += n * 100
        return score

    def _try_fit_columns_greedy(self, n, trial_std, half_left, half_right,
                                 purlin_left, purlin_right, purlin_3rd_left, purlin_3rd_right,
                                 target_inward, bound_l, bound_r,
                                 p, damping_positions):
        """逐跨贪心搜索。n 固定，每次+100即刻检查。返回 (spacings, damp) 或 None。"""
        side_count = (n - 1) // 2
        if side_count == 0:
            return None

        end_gap = trial_std - COL_END_REDUCTION
        if end_gap < 3500:
            end_gap = max(3500, trial_std - 500)

        if side_count > 1:
            gaps = [trial_std] * (side_count - 1) + [end_gap]
        else:
            gaps = [end_gap]

        max_gap = 8000
        min_gap = 3500

        damp = [False] * n
        for pos in damping_positions:
            if pos < side_count:
                damp[pos] = True
                damp[n - 1 - pos] = True

        def _check_valid(spacings):
            if spacings[0] < 0 or spacings[n] < 0:
                return False, None
            if not ParamPanel._check_gap_range(spacings, n):
                return False, None
            tp = PVParams()
            tp.panel_len = p.panel_len
            tp.panel_wid = p.panel_wid
            tp.panel_thk = p.panel_thk
            tp.hole_spacing = p.hole_spacing
            tp.panel_gap = p.panel_gap
            tp.panel_cnt_total = p.panel_cnt_total
            tp.rotation_gap = p.rotation_gap
            tp.left_cnt_auto = p.left_cnt_auto
            tp.right_cnt_auto = p.right_cnt_auto
            tp.left_panel_cnt = p.left_panel_cnt
            tp.right_panel_cnt = p.right_panel_cnt
            tp.col_cnt = n
            tp.col_ht = D["col_ht"]
            tp.col_sec_w = D["col_sec_w"]
            tp.col_spacings = list(spacings)
            tp.col_damping = list(damp)
            tp.purlin_w = D["purlin_w"]
            tp.purlin_h = D["purlin_h"]
            tp.purlin_influence = D["purlin_influence"]
            tp.purlin_end_offset = D["purlin_end_offset"]
            tp.beam_center_half = D["beam_center_half"]
            tp.beam_telescope = D["beam_telescope"]
            tp.splice_inf_half = D["splice_inf_half"]
            tp.splice_h = D["splice_h"]
            tp.beam_segments = list(p.beam_segments)
            tp.beam_segment_types = list(p.beam_segment_types) if hasattr(p, 'beam_segment_types') else []
            tp.col_spacing_min = p.col_spacing_min
            tp.col_spacing_max = p.col_spacing_max
            tp.derive()
            # 边界检查：最外柱必须在 [target_inward, bound] 范围内
            outer_left = tp.col_positions[0]
            outer_right = tp.col_positions[-1]
            if outer_left < bound_l or outer_right > bound_r:
                return False, None
            outer_abs = max(abs(outer_left), abs(outer_right))
            if outer_abs < target_inward:
                return False, None
            issues = check_interference(tp)
            has_critical = any(iss.level == "critical" for iss in issues)
            return not has_critical, issues

        # ── 阶段1：每轮从中心向外各+100，即刻检查 ──
        spacings, _ = self._build_symmetric_spacings(n, list(gaps), half_left, half_right)
        valid, issues = _check_valid(spacings)
        if valid:
            return spacings, damp

        for _ in range(100):  # 安全上限
            increased = False
            for pos in range(side_count):  # 0=中心, 向外
                if gaps[pos] + 100 <= max_gap:
                    gaps[pos] += 100
                    increased = True
                    spacings, _ = self._build_symmetric_spacings(n, list(gaps), half_left, half_right)
                    valid, issues = _check_valid(spacings)
                    if valid:
                        return spacings, damp
            # 一旦超出边界就停止增加，进入阶段2
            if sum(gaps) > max(abs(bound_l), abs(bound_r)):
                break
            if not increased:
                break

        # ── 阶段2：从当前位置向中心递减，即刻检查 ──
        for _ in range(100):  # 安全上限
            decreased = False
            for pos in reversed(range(side_count)):  # 边缘=side-1, 向内
                if gaps[pos] - 100 >= min_gap:
                    gaps[pos] -= 100
                    decreased = True
                    spacings, _ = self._build_symmetric_spacings(n, list(gaps), half_left, half_right)
                    valid, issues = _check_valid(spacings)
                    if valid:
                        return spacings, damp
            if not decreased:
                break

        # ── 阶段3：渐进式随机搜索 ──
        # 只在 trial_std 接近短边理想值时做（避免全部遍历导致卡顿）
        design_half = min(half_left, half_right)
        ideal_avg = max(5000, design_half / side_count) if side_count > 0 else 6000
        if abs(trial_std - ideal_avg) > 800:
            return None

        interior_min = 5000
        rng = random.Random(n * 10000 + int(trial_std))
        # 瞄准窗口中间（避免阻尼柱干涉边界）
        bound_max = max(abs(bound_l), abs(bound_r))
        target = int((target_inward + bound_max) / 2)
        ideal = target / side_count
        # 逐步放宽 spread：从最均匀开始，搜不到再扩大
        for spread in (600, 800, 1000, 1200, 1500, 2000):
            for _ in range(150):
                test_gaps = []
                total = 0
                for pos in range(side_count - 1):
                    lo = int(max(interior_min, ideal - spread))
                    hi = int(min(max_gap, ideal + spread))
                    g = rng.randint(lo // 100, hi // 100) * 100
                    test_gaps.append(g)
                    total += g
                last = target - total
                last = max(min_gap, min(max_gap, last))
                test_gaps.append(last)
                test_gaps.sort(reverse=True)
                spacings, _ = self._build_symmetric_spacings(n, list(test_gaps), half_left, half_right)
                valid, issues = _check_valid(spacings)
                if valid:
                    return spacings, damp
            # 当前 spread 没搜到，放宽后重试

        return None

    def _on_auto_col(self):
        """自动布置立柱 — n范围公式 + 逐跨贪心搜索"""
        if self._auto_designing:
            return
        self._auto_designing = True
        try:
            p = self.build_params()
            if not p.purlin_positions or len(p.purlin_positions) < 4:
                self._auto_designing = False
                return

            step = p.panel_wid + p.panel_gap
            pool = col_spacing_pool(step)
            if not pool:
                self._auto_designing = False
                return

            # ── 1. n 范围公式（按短边设计，长边自动更优）──
            min_panels = min(p.left_panel_cnt, p.right_panel_cnt)
            total_half_span = min_panels * step
            n_min = int(math.ceil(total_half_span * 2 / 8000))
            if n_min % 2 == 0:
                n_min += 1
            n_min = max(5, n_min)
            n_max = int(math.floor(total_half_span * 2 / 5000))
            if n_max % 2 == 0:
                n_max -= 1
            n_max = max(n_min, n_max)

            left_target = (p.purlin_positions[1] + p.purlin_positions[2]) / 2
            right_target = (p.purlin_positions[-2] + p.purlin_positions[-3]) / 2
            half_left = abs(left_target)
            half_right = abs(right_target)
            base_half = min(half_left, half_right)

            purlin_left = p.purlin_positions[1]
            purlin_right = p.purlin_positions[-2]
            purlin_3rd_left = p.purlin_positions[2]
            purlin_3rd_right = p.purlin_positions[-3]
            purlin_last_left = p.purlin_positions[0]
            purlin_last_right = p.purlin_positions[-1]

            # ── 按短边确定对称边界（长边自动更优）──
            short_3rd = min(abs(purlin_3rd_left), abs(purlin_3rd_right))
            short_2nd = min(abs(purlin_left), abs(purlin_right))
            short_last = min(abs(purlin_last_left), abs(purlin_last_right))

            # 非对称阵列：短边只做 Tier 2（第1~2块间），对称到长边自动 Tier 1
            is_asymmetric = p.left_panel_cnt != p.right_panel_cnt

            t1_target = short_3rd
            t1_bound_l = -short_2nd
            t1_bound_r = short_2nd
            t2_target = short_2nd
            t2_bound_l = -short_last
            t2_bound_r = short_last

            dp = self.damping_pairs.currentIndex() + 1
            damping_positions = list(range(dp)) if dp <= 2 else [
                j for j, cb in enumerate(self.damping_pos_checks) if cb.isChecked()
            ]

            # ── 2. 过滤不可行的 n（最大跨距也达不到目标）──
            min_target = t2_target if is_asymmetric else t1_target
            max_bound = max(short_last, short_2nd) if is_asymmetric else short_last

            # ── 3. 遍历 n → trial_std → tier ──
            all_valid = []

            for n in range(n_min, n_max + 1, 2):
                side = (n - 1) // 2
                if side * 8000 < min_target:
                    continue  # 几何上无法达到目标
                for i, std in enumerate(pool):
                    prev = pool[i - 1] if i > 0 else std - 500
                    next_ = pool[i + 1] if i + 1 < len(pool) else std + 500
                    lo = int(((prev + std) / 2 + 50) // 100 * 100)
                    hi = int(((std + next_) / 2 - 50) // 100 * 100)

                    for trial_std in range(lo, hi + 1, 100):
                        found = False
                        tiers = [(t2_target, t2_bound_l, t2_bound_r)] if is_asymmetric else [
                                (t1_target, t1_bound_l, t1_bound_r),
                                (t2_target, t2_bound_l, t2_bound_r)]
                        for tier, (t_target, t_bound_l, t_bound_r) in enumerate(tiers, 2 if is_asymmetric else 1):
                            result = self._try_fit_columns_greedy(
                                n, trial_std, half_left, half_right,
                                purlin_left, purlin_right,
                                purlin_3rd_left, purlin_3rd_right,
                                t_target, t_bound_l, t_bound_r,
                                p, damping_positions)
                            if result is None:
                                continue
                            spacings, damp = result

                            side = (n - 1) // 2
                            tp = PVParams()
                            tp.panel_len = p.panel_len
                            tp.panel_wid = p.panel_wid
                            tp.panel_thk = p.panel_thk
                            tp.hole_spacing = p.hole_spacing
                            tp.panel_gap = p.panel_gap
                            tp.panel_cnt_total = p.panel_cnt_total
                            tp.rotation_gap = p.rotation_gap
                            tp.left_cnt_auto = p.left_cnt_auto
                            tp.right_cnt_auto = p.right_cnt_auto
                            tp.left_panel_cnt = p.left_panel_cnt
                            tp.right_panel_cnt = p.right_panel_cnt
                            tp.col_cnt = n
                            tp.col_ht = D["col_ht"]
                            tp.col_sec_w = D["col_sec_w"]
                            tp.col_spacings = list(spacings)
                            tp.col_damping = list(damp)
                            tp.purlin_w = D["purlin_w"]
                            tp.purlin_h = D["purlin_h"]
                            tp.purlin_influence = D["purlin_influence"]
                            tp.purlin_end_offset = D["purlin_end_offset"]
                            tp.beam_center_half = D["beam_center_half"]
                            tp.beam_telescope = D["beam_telescope"]
                            tp.splice_inf_half = D["splice_inf_half"]
                            tp.splice_h = D["splice_h"]
                            tp.beam_segments = list(p.beam_segments)
                            tp.beam_segment_types = list(p.beam_segment_types) if hasattr(p, 'beam_segment_types') else []
                            tp.col_spacing_min = p.col_spacing_min
                            tp.col_spacing_max = p.col_spacing_max
                            tp.derive()
                            issues = check_interference(tp)
                            score = self._score_uniformity(spacings, n, issues)
                            if score == float('inf'):
                                continue

                            interior = spacings[1:n]
                            avg_gap = sum(interior) / len(interior) if interior else 0
                            outer_pos = tp.col_positions[0] if tp.col_positions else 0
                            all_valid.append((score, trial_std, n, spacings, damp,
                                             avg_gap, outer_pos, list(interior), tier))
                            found = True
                            break
                        if found:
                            break

            if not all_valid:
                self._auto_designing = False
                QMessageBox.warning(self, "自动布置失败",
                    "未找到满足全部约束的方案。\n请调整组件参数后重试。")
                return

            # ── 3. 按(柱数, tier)分组取最优 ──
            best_by_n_tier = {}
            for item in all_valid:
                score = item[0]
                key = (item[2], item[8])
                if key not in best_by_n_tier or score < best_by_n_tier[key][0]:
                    best_by_n_tier[key] = item
            sorted_options = sorted(best_by_n_tier.values(),
                                    key=lambda x: (x[8], x[2]))

            # ── 4. 弹窗 ──
            long_side = max(half_left, half_right)
            dlg = QDialog(self)
            dlg.setWindowTitle("选择立柱布置方案")
            dlg.setMinimumWidth(600)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(
                f"可行柱数: {', '.join(str(n) for n in sorted(set(item[2] for item in sorted_options)))}根 | "
                f"组件{p.left_panel_cnt}+{p.right_panel_cnt}块×{step:.0f}mm | "
                f"无干涉+跨距5000~8000 | 共{len(sorted_options)}方案"))

            group = QButtonGroup(dlg)
            group.setExclusive(True)
            current_tier = 0
            for i, (score, trial_std, n, spacings, damp,
                    avg_gap, outer_pos, gap_list, tier) in enumerate(sorted_options):
                side = (n - 1) // 2
                end_gap_val = gap_list[0] if len(gap_list) > 0 else 0
                gap_str = " → ".join(f"{g:.0f}" for g in gap_list)
                mean_g = sum(gap_list) / len(gap_list) if gap_list else 0
                var = sum((g - mean_g) ** 2 for g in gap_list) / len(gap_list) if gap_list else 0

                if tier != current_tier:
                    current_tier = tier
                    sep = QLabel(
                        "━━━ ⭐ 优选（最外柱在第2~3檩条间）━━━" if tier == 1
                        else "━━━ 📋 备选（最外柱在第1~2檩条间）━━━")
                    sep.setStyleSheet(
                        "font-weight:bold; color:#2980b9; padding:4px 0;" if tier == 1
                        else "font-weight:bold; color:#e67e22; padding:4px 0;")
                    lay.addWidget(sep)

                prefix = "⭐" if tier == 1 else "📋"
                text = (f"{prefix} {n}根 | 每侧{side}根 | 平均跨距{avg_gap:.0f}mm | 方差{var:.0f}\n"
                        f"   跨距: {gap_str} mm\n"
                        f"   最外柱: ±{abs(outer_pos):.0f}mm | 末跨: {end_gap_val:.0f}mm")

                rb = QRadioButton(text)
                rb.setStyleSheet("font-size:12px; padding:4px;")
                if i == 0:
                    rb.setChecked(True)
                group.addButton(rb, i)
                lay.addWidget(rb)

            lay.addSpacing(8)
            bb = QHBoxLayout()
            ok = QPushButton("✅ 应用选中方案")
            ok.setStyleSheet(
                "QPushButton{background:#27ae60;color:#fff;padding:6px;"
                "border-radius:4px;font-weight:bold;}")
            cancel = QPushButton("取消")
            cancel.setStyleSheet("QPushButton{padding:6px;}")
            bb.addStretch()
            bb.addWidget(cancel)
            bb.addWidget(ok)
            lay.addLayout(bb)

            def apply():
                idx = group.checkedId()
                if idx >= 0:
                    _, trial_std, n, spacings, damp = sorted_options[idx][:5]
                    self.col_cnt.setValue(n)
                    self._rebuild_col_table(n, spacings, damp, base_half * 2)
                    self._auto_designing = False
                    dlg.accept()
                    self._emit_change()
                    side = (n - 1) // 2
                    applied = sum(1 for v in damp[:side] if v)
                    if applied < len(damping_positions):
                        skipped = [str(p + 1) for p in damping_positions if p >= side]
                        QMessageBox.information(
                            dlg, "阻尼器调整提示",
                            f"单边仅有 {side} 根非驱动柱，\n"
                            f"末端第 {', '.join(skipped)} 根位置超出范围，已自动跳过。\n"
                            f"实际每边安装 {applied} 对阻尼器。")
                    mw = self.window()
                    if isinstance(mw, QMainWindow):
                        interior = spacings[1:n]
                        if interior:
                            mean_g2 = sum(interior) / len(interior)
                            var2 = sum((g - mean_g2) ** 2 for g in interior) / len(interior)
                        else:
                            var2 = 0
                        mw.statusBar().showMessage(
                            mw.statusBar().currentMessage() +
                            f" | 📐 已选取: 间距{trial_std}mm, {n}根, 方差{var2:.0f}")

            ok.clicked.connect(apply)
            cancel.clicked.connect(lambda: (setattr(self, '_auto_designing', False), dlg.reject()))
            dlg.finished.connect(lambda: setattr(self, '_auto_designing', False))
            dlg.exec()

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "自动布置错误", f"{type(e).__name__}:\n{e}")
            self._auto_designing = False
    def update_status(self, issues: List[InterferenceIssue]):
        self.status_list.clear()
        colors = {
            "critical": ("#ffeaea", "#c0392b", "🔴"),
            "warning": ("#fff8e6", "#b8860b", "🟡"),
            "ok": ("#eafaf1", "#1e8449", "✅"),
        }
        for iss in issues:
            bg, fg, icon = colors.get(iss.level, ("#fff", "#333", ""))
            item = QListWidgetItem(f"{icon} {iss.msg}")
            item.setBackground(QColor(bg))
            item.setForeground(QColor(fg))
            self.status_list.addItem(item)


# ═══════════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("☀️ 光伏跟踪支架阵列设计工具 v2.0 — 1P")
        self.resize(1200, 950)

        self.param_panel = ParamPanel()
        self.canvas = FrontViewWidget()

        # ── 底部面板：立柱间距表 + 主梁段表 ──
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(4, 4, 4, 4)

        # 立柱表
        col_grp = QGroupBox("🏛️ 立柱间距表 (mm)")
        col_grp.setLayout(QVBoxLayout())
        col_grp.layout().setContentsMargins(4, 14, 4, 4)
        col_grp.layout().addWidget(self.param_panel.col_table)
        col_hint = QLabel("首行=左参考→柱1 / 末行=柱N→右参考 / 驱动柱固定在X=0")
        col_hint.setStyleSheet("font-size:10px; color:#999; font-style:italic; padding-left:4px;")
        col_grp.layout().addWidget(col_hint)
        bottom_layout.addWidget(col_grp, 1)

        # 主梁表
        beam_grp = QGroupBox("🛠️ 主梁段长度表 (mm, 从左到右)")
        beam_grp.setLayout(QVBoxLayout())
        beam_grp.layout().setContentsMargins(4, 14, 4, 4)
        beam_grp.layout().addWidget(self.param_panel.beam_table)
        beam_hint = QLabel("中间两根=F(无缩管) 其余=S(缩管260mm) | 连接件中心=重叠区中点 干涉±180mm")
        beam_hint.setStyleSheet("font-size:10px; color:#999; font-style:italic; padding-left:4px;")
        beam_grp.layout().addWidget(beam_hint)
        bottom_layout.addWidget(beam_grp, 1)

        # ── 主布局 ──
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(self.param_panel)
        top_splitter.addWidget(self.canvas)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([340, 660])

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setSizes([500, 300])
        self.setCentralWidget(main_splitter)

        menubar = self.menuBar()
        fm = menubar.addMenu("文件")
        fm.addAction("导出 AutoCAD 脚本 (.scr)", self._on_export_scr)
        fm.addAction("导出参数数据 (.csv)", self._on_export_csv)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        self.statusBar().showMessage("就绪 | 驱动柱中心X=0 | 主梁从±77.5向两边延伸")

        self.param_panel.param_changed.connect(self._on_params_changed)
        self.param_panel.btn_scr.clicked.connect(self._on_export_scr)
        self.param_panel.btn_csv.clicked.connect(self._on_export_csv)

        self._on_params_changed(self.param_panel.build_params())

    @pyqtSlot(object)
    def _on_params_changed(self, p: PVParams):
        self.param_panel.update_ui_from_params(p)
        issues = check_interference(p)
        self.param_panel.update_status(issues)
        self.canvas.draw_view(p, issues)
        crits = sum(1 for i in issues if i.level == "critical")
        warns = sum(1 for i in issues if i.level == "warning")
        parts = [
            f"总跨度={p.total_span:.0f}mm",
            f"组件{p.panel_cnt_total}块(左{p.left_panel_cnt}+右{p.right_panel_cnt})",
            f"立柱{p.col_cnt}根",
            f"主梁{len(p.beam_segments)}段",
            f"连接件{len(p.splice_positions)}处",
        ]
        if crits > 0:
            parts.append(f"⚠ {crits}处干涉!")
        elif warns > 0:
            parts.append(f"⚡ {warns}项提醒")
        else:
            parts.append("✅ 无干涉")
        self.statusBar().showMessage(" | ".join(parts))

    def _on_export_scr(self):
        p = self.param_panel.build_params()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 AutoCAD 脚本", f"跟踪支架_{date.today().isoformat()}.scr",
            "SCR Files (*.scr);;All Files (*)")
        if path:
            export_scr(p, path)
            QMessageBox.information(self, "导出成功", f"已保存至:\n{path}")

    def _on_export_csv(self):
        p = self.param_panel.build_params()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出参数数据", f"跟踪支架_参数_{date.today().isoformat()}.csv",
            "CSV Files (*.csv);;All Files (*)")
        if path:
            export_csv(p, path)
            QMessageBox.information(self, "导出成功", f"已保存至:\n{path}")


# ═══════════════════════════════════════════════════════════════════════════════════
def main():
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        font = app.font()
        font.setPointSize(10)
        app.setFont(font)
        window = MainWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        msg = traceback.format_exc()
        print(msg, file=sys.stderr)
        try:
            QMessageBox.critical(None, "启动失败", msg)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
