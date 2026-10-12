import sys
import os
import math
import uuid
import json
import csv
import fitz  # PyMuPDF
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QFileDialog, QComboBox, 
                               QSpinBox, QLabel, QGraphicsView, QGraphicsScene, 
                               QMessageBox, QGroupBox, QFormLayout, QLineEdit, QColorDialog,
                               QScrollArea, QCheckBox)
from PySide6.QtGui import QPixmap, QImage, QPen, QBrush, QColor, QPolygonF, QCursor, QShortcut, QKeySequence, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF

# ==========================================
# Geometry, Shadows & PDF Output Functions
# ==========================================
def calculate_fov_polygon(x, y, radius, angle_deg, fov_spread_deg):
    points = [(x, y)]
    start_angle = math.radians(angle_deg - (fov_spread_deg / 2))
    end_angle = math.radians(angle_deg + (fov_spread_deg / 2))
    
    steps = max(15, int(fov_spread_deg / 10))
    for i in range(steps + 1):
        theta = start_angle + (end_angle - start_angle) * (i / steps)
        px = x + radius * math.cos(theta)
        py = y - radius * math.sin(theta)
        points.append((px, py))
    
    points.append((x, y)) 
    return points

def calculate_shadow_polygon(cx, cy, wx1, wy1, wx2, wy2, max_dist=10000):
    def project_point(px, py):
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy)
        if dist == 0: dist = 0.0001
        return cx + (dx / dist) * max_dist, cy + (dy / dist) * max_dist

    ext_x1, ext_y1 = project_point(wx1, wy1)
    ext_x2, ext_y2 = project_point(wx2, wy2)

    return [QPointF(wx1, wy1), QPointF(wx2, wy2), QPointF(ext_x2, ext_y2), QPointF(ext_x1, ext_y1), QPointF(wx1, wy1)]

def add_camera_to_pdf(page, x, y, cam, camera_types):
    shape = page.new_shape()
    shape_drawn = False 
    
    cam_type = cam['type']
    angle_deg = cam['angle']
    radius = cam['radius']
    fov = cam['fov']
    type_info = camera_types.get(cam_type, {})
    s = cam.get("icon_scale", 100) / 100.0
    opacity_val = cam.get("opacity", 30) / 100.0

    cam_color = cam.get("color")
    if isinstance(cam_color, str): cam_color = QColor(cam_color)
    elif not cam_color: cam_color = QColor(type_info.get("color", Qt.gray))
        
    r, g, b = (cam_color.redF(), cam_color.greenF(), cam_color.blueF())

    for poly_pts in cam.get("export_polygons", []):
        if poly_pts and len(poly_pts) > 2:
            closed_pts = poly_pts + [poly_pts[0]]
            shape.draw_polyline(closed_pts)
            shape_drawn = True
            
    if shape_drawn:
        shape.finish(color=(r, g, b), fill=(r, g, b), fill_opacity=opacity_val, width=0)

    def draw_safe_arc(cx, cy, r_arc, a_start, a_end, steps=25):
        pts = []
        s_rad = math.radians(a_start)
        e_rad = math.radians(a_end)
        for i in range(steps + 1):
            theta = s_rad + (e_rad - s_rad) * (i / steps)
            px = cx + r_arc * math.cos(theta)
            py = cy - r_arc * math.sin(theta)
            pts.append((px, py))
        shape.draw_polyline(pts)

    if cam_type == 'Speaker':
        for w_dist in [radius * 0.3, radius * 0.6, radius * 0.9]:
            draw_safe_arc(x, y, w_dist, angle_deg - fov/2, angle_deg + fov/2)
            shape.finish(color=(r, g, b), width=1.5*s)
            shape_drawn = True

    if cam.get("is_360", False):
        arc_rad = 18 * s
        draw_safe_arc(x, y, arc_rad, angle_deg + 45, angle_deg + 315, steps=30)
        shape.finish(color=(r, g, b), dashes="[3 3] 0", width=1.5*s)
        
        end_rad = math.radians(angle_deg + 315)
        ax = x + arc_rad * math.cos(end_rad)
        ay = y - arc_rad * math.sin(end_rad)
        tg_rad = end_rad + math.pi/2
        
        p2x = ax + 5*s * math.cos(tg_rad + 2.5)
        p2y = ay - 5*s * math.sin(tg_rad + 2.5)
        p3x = ax + 5*s * math.cos(tg_rad - 2.5)
        p3y = ay - 5*s * math.sin(tg_rad - 2.5)
        
        shape.draw_polyline([(ax, ay), (p2x, p2y), (p3x, p3y), (ax, ay)])
        shape.finish(color=(r, g, b), fill=(r, g, b), width=0.1)
        shape_drawn = True

    if type_info.get("icon_path") and os.path.exists(type_info.get("icon_path")):
        half_sz = 12 * s
        rect = fitz.Rect(x - half_sz, y - half_sz, x + half_sz, y + half_sz)
        page.insert_image(rect, filename=type_info["icon_path"]) 
    elif cam_type == 'Speaker':
        def r_pt(px, py):
            rad = math.radians(angle_deg)
            nx = x + (px - x)*math.cos(rad) - (py - y)*math.sin(rad)
            ny = y - (px - x)*math.sin(rad) - (py - y)*math.cos(rad)
            return (nx, ny)
        spk_pts = [
            r_pt(x - 4*s, y - 3*s), r_pt(x + 2*s, y - 3*s),
            r_pt(x + 8*s, y - 7*s), r_pt(x + 8*s, y + 7*s),
            r_pt(x + 2*s, y + 3*s), r_pt(x - 4*s, y + 3*s)
        ]
        closed_spk_pts = spk_pts + [spk_pts[0]]
        shape.draw_polyline(closed_spk_pts)
        shape.finish(color=(0,0,0), fill=(r,g,b), width=1*s)
        shape_drawn = True
    elif cam_type == 'Dome':
        shape.draw_circle((x, y), 8 * s)
        shape.finish(color=(r, g, b), fill=(r, g, b), width=1 * s)
        shape_drawn = True
    elif cam_type == 'Bullet':
        shape.draw_rect(fitz.Rect(x - 6*s, y - 6*s, x + 6*s, y + 6*s))
        shape.finish(color=(r, g, b), fill=(r, g, b), width=1 * s)
        shape_drawn = True
    elif cam_type == 'PTZ':
        shape.draw_circle((x, y), 10 * s)
        shape.draw_line((x - 10*s, y), (x + 10*s, y))
        shape.draw_line((x, y - 10*s), (x, y + 10*s))
        shape.finish(color=(r, g, b), fill=(1, 1, 1), width=1.5 * s)
        shape_drawn = True
        
    if shape_drawn:
        shape.commit()
    
    cam_name = cam.get("name", "")
    if cam_name:
        font_sz = max(6, int(10 * s))
        text_length = len(cam_name) * (font_sz * 0.6)
        off_x = 14 * s
        off_y = 16 * s
        
        bg_shape = page.new_shape()
        bg_shape.draw_rect(fitz.Rect(x + off_x, y - off_y, x + off_x + text_length + 2, y - off_y + (font_sz + 5)))
        bg_shape.finish(color=(1, 1, 1), fill=(1, 1, 1), fill_opacity=0.8, width=0)
        bg_shape.commit()
        page.insert_text((x + off_x + 1, y - off_y + (font_sz + 1)), cam_name, fontsize=font_sz, fontname="hebo", color=(0, 0, 0))

def draw_legend_on_pdf(page, page_cams, camera_types, global_cams=None, lx=10, ly=10, custom_scale=100):
    page_width = page.rect.width
    scale = max(1.0, page_width / 1200.0) * (custom_scale / 100.0)
    
    p_counts = {}
    p_cam_total, p_spk_total = 0, 0
    for cam in page_cams.values(): 
        ctype = cam['type']
        p_counts[ctype] = p_counts.get(ctype, 0) + 1
        if ctype == 'Speaker': p_spk_total += 1
        else: p_cam_total += 1
        
    g_counts = {}
    g_cam_total, g_spk_total = 0, 0
    if global_cams:
        for cam in global_cams.values(): 
            ctype = cam['type']
            g_counts[ctype] = g_counts.get(ctype, 0) + 1
            if ctype == 'Speaker': g_spk_total += 1
            else: g_cam_total += 1
            
    num_items = max(1, len(p_counts)) + (max(1, len(g_counts)) + 1 if global_cams else 0)

    width = 200 * scale 
    height = (30 + (num_items * 25)) * scale
    if global_cams: height += 15 * scale 
    
    bg_shape = page.new_shape()
    bg_shape.draw_rect(fitz.Rect(lx, ly, lx + width, ly + height))
    bg_shape.finish(color=(0, 0, 0), fill=(1, 1, 1), fill_opacity=1.0, width=1.0 * scale)
    bg_shape.commit()
    
    y_offset = ly + (20 * scale)
    font_title, font_body = 10 * scale, 9 * scale
    
    def draw_list(title, c_dict, c_tot, s_tot, y_start):
        header_txt = f"{title} (Cams: {c_tot} | Spkrs: {s_tot})"
        page.insert_text((lx + (10 * scale), y_start), header_txt, fontsize=font_title, fontname="hebo", color=(0, 0, 0))
        y_start += (20 * scale)
        
        if not c_dict:
            page.insert_text((lx + (35 * scale), y_start + (4 * scale)), "None", fontsize=font_body, fontname="helv", color=(0, 0, 0))
            y_start += (25 * scale)
            return y_start
            
        icon_shape = page.new_shape()
        for ctype, count in c_dict.items():
            type_info = camera_types.get(ctype, {})
            page.insert_text((lx + (35 * scale), y_start + (4 * scale)), f"{ctype}: {count} units", fontsize=font_body, fontname="helv", color=(0, 0, 0))
            ix, iy = lx + (18 * scale), y_start
            
            base_col = type_info.get("color", Qt.gray)
            if isinstance(base_col, str): base_col = QColor(base_col)
            elif not isinstance(base_col, QColor): base_col = QColor(base_col)
            r, g, b = base_col.redF(), base_col.greenF(), base_col.blueF()
            
            if type_info.get("icon_path") and os.path.exists(type_info.get("icon_path")):
                icon_sz = 8 * scale
                page.insert_image(fitz.Rect(ix - icon_sz, iy - icon_sz, ix + icon_sz, iy + icon_sz), filename=type_info["icon_path"])
            elif ctype == 'Speaker':
                spk_pts = [(ix - 4*scale, iy - 3*scale), (ix + 2*scale, iy - 3*scale), (ix + 8*scale, iy - 7*scale), (ix + 8*scale, iy + 7*scale), (ix + 2*scale, iy + 3*scale), (ix - 4*scale, iy + 3*scale)]
                closed_spk_pts = spk_pts + [spk_pts[0]]
                icon_shape.draw_polyline(closed_spk_pts)
                icon_shape.finish(color=(0,0,0), fill=(r,g,b), width=1*scale)
            elif ctype == 'Dome':
                icon_shape.draw_circle((ix, iy), 5 * scale)
                icon_shape.finish(color=(r, g, b), fill=(r, g, b), width=1 * scale)
            elif ctype == 'Bullet':
                icon_shape.draw_rect(fitz.Rect(ix - (4 * scale), iy - (4 * scale), ix + (4 * scale), iy + (4 * scale)))
                icon_shape.finish(color=(r, g, b), fill=(r, g, b), width=1 * scale)
            elif ctype == 'PTZ':
                icon_shape.draw_circle((ix, iy), 6 * scale)
                icon_shape.draw_line((ix - (6 * scale), iy), (ix + (6 * scale), iy))
                icon_shape.draw_line((ix, iy - (6 * scale)), (ix, iy + (6 * scale)))
                icon_shape.finish(color=(r, g, b), fill=(1, 1, 1), width=1 * scale)
            else:
                icon_shape.draw_circle((ix, iy), 5 * scale)
                icon_shape.finish(color=(r, g, b), fill=(r, g, b), width=1 * scale)
            y_start += (25 * scale)
        icon_shape.commit()
        return y_start

    y_offset = draw_list(f"PAGE {page.number + 1}", p_counts, p_cam_total, p_spk_total, y_offset)
    if global_cams:
        y_offset += (10 * scale)
        draw_list("GRAND TOTAL", g_counts, g_cam_total, g_spk_total, y_offset)

# ==========================================
# Custom Interactivity View
# ==========================================
class ClickableGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.parent_app = parent
        self.setMouseTracking(True)
        self.setRenderHint(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFocusPolicy(Qt.StrongFocus)

        self.is_panning = False
        self.pan_distance = 0
        self.click_pos = None
        self.scene_click_pos = None
        
        self.clicked_cam_id = None
        self.is_moving_cam = False
        self.is_rotating_cam = False
        
        self.is_moving_legend = False

        self.is_drawing_wall = False
        self.is_drawing_curve = False
        self.wall_start = None
        self.curve_points = []
        self.temp_wall_item = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.is_drawing_wall = False
            self.is_drawing_curve = False
            if self.temp_wall_item:
                self.scene().removeItem(self.temp_wall_item)
                self.temp_wall_item = None
            self.parent_app.tool_mode.setCurrentIndex(0)
            self.setCursor(Qt.ArrowCursor)
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            zoom_in_factor = 1.15
            if event.angleDelta().y() > 0: self.scale(zoom_in_factor, zoom_in_factor)
            else: self.scale(1 / zoom_in_factor, 1 / zoom_in_factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if not self.parent_app.current_pdf_path: return super().mousePressEvent(event)

        pos = event.position().toPoint()
        item = self.itemAt(pos)
        item_type = item.data(1) if item else None
        item_id = item.data(0) if item else None
        
        self.click_pos = pos
        self.scene_click_pos = self.mapToScene(pos)
        tool_mode = self.parent_app.tool_mode.currentText()

        if event.button() == Qt.LeftButton:
            if tool_mode == "Tool: Draw Straight Wall":
                self.is_drawing_wall = True
                self.wall_start = self.scene_click_pos
                self.temp_wall_item = self.scene().addLine(self.wall_start.x(), self.wall_start.y(), self.wall_start.x(), self.wall_start.y(), QPen(Qt.yellow, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                return
            elif tool_mode == "Tool: Draw Curved Wall":
                self.is_drawing_curve = True
                self.curve_points = [self.scene_click_pos]
                path = QPainterPath(self.scene_click_pos)
                self.temp_wall_item = self.scene().addPath(path, QPen(Qt.yellow, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                return

            if item_type == "camera":
                self.clicked_cam_id = item_id
                self.parent_app.select_camera(self.clicked_cam_id)
            elif item_type != "legend":
                self.clicked_cam_id = None
                self.parent_app.deselect_camera()
                self.parent_app.add_camera_marker(self.scene_click_pos.x(), self.scene_click_pos.y())
                
        elif event.button() == Qt.RightButton:
            if item_type == "wall" and not event.modifiers():
                self.parent_app.delete_wall(item_id)
                return

            if event.modifiers() == Qt.ControlModifier:
                if item_type == "camera":
                    self.clicked_cam_id = item_id
                    self.parent_app.select_camera(self.clicked_cam_id)
                    cam = self.parent_app.camera_data[self.clicked_cam_id]
                    dist = math.hypot(self.scene_click_pos.x() - cam['x'], self.scene_click_pos.y() - cam['y'])
                    if dist < 20: 
                        self.is_moving_cam = True
                        self.setCursor(Qt.SizeAllCursor)
                    else:
                        self.is_rotating_cam = True
                        self.setCursor(Qt.CrossCursor)
                    return
                elif item_type == "legend":
                    self.is_moving_legend = True
                    self.setCursor(Qt.SizeAllCursor)
                    return

            self.is_panning = True
            self.pan_distance = 0
            self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.parent_app.current_pdf_path: return super().mouseMoveEvent(event)
        
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)

        if self.is_drawing_wall and self.temp_wall_item:
            self.temp_wall_item.setLine(self.wall_start.x(), self.wall_start.y(), scene_pos.x(), scene_pos.y())
            return
            
        if self.is_drawing_curve and self.temp_wall_item:
            if math.hypot(scene_pos.x() - self.curve_points[-1].x(), scene_pos.y() - self.curve_points[-1].y()) > 15:
                self.curve_points.append(scene_pos)
                path = QPainterPath(self.curve_points[0])
                for pt in self.curve_points[1:]:
                    path.lineTo(pt)
                self.temp_wall_item.setPath(path)
            return

        if self.is_panning and self.click_pos:
            delta = pos - self.click_pos
            self.pan_distance += delta.manhattanLength()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.click_pos = pos
            
        elif self.is_moving_cam and self.clicked_cam_id:
            self.parent_app.update_cam_transform(self.clicked_cam_id, x=scene_pos.x(), y=scene_pos.y())
            
        elif self.is_rotating_cam and self.clicked_cam_id:
            cam = self.parent_app.camera_data[self.clicked_cam_id]
            dx = scene_pos.x() - cam['x']
            dy = scene_pos.y() - cam['y']
            angle = math.degrees(math.atan2(-dy, dx))
            self.parent_app.update_cam_transform(self.clicked_cam_id, angle=int(angle % 360))
            
        elif self.is_moving_legend:
            leg_data = self.parent_app.legends.setdefault(self.parent_app.current_page, {'x': 10, 'y': 10, 'scale': 100})
            leg_data['x'] = scene_pos.x()
            leg_data['y'] = scene_pos.y()
            self.parent_app.draw_legend_ui()
            self.parent_app.mark_layout_dirty()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self.parent_app.current_pdf_path: return super().mouseReleaseEvent(event)
        self.setCursor(Qt.ArrowCursor)

        if event.button() == Qt.LeftButton:
            if self.is_drawing_wall:
                self.is_drawing_wall = False
                if self.temp_wall_item: self.scene().removeItem(self.temp_wall_item)
                scene_pos = self.mapToScene(event.position().toPoint())
                if math.hypot(scene_pos.x() - self.wall_start.x(), scene_pos.y() - self.wall_start.y()) > 10:
                    pts = [(self.wall_start.x(), self.wall_start.y()), (scene_pos.x(), scene_pos.y())]
                    self.parent_app.add_wall(pts)
                return
                
            elif self.is_drawing_curve:
                self.is_drawing_curve = False
                if self.temp_wall_item: self.scene().removeItem(self.temp_wall_item)
                if len(self.curve_points) > 1:
                    pts = [(p.x(), p.y()) for p in self.curve_points]
                    self.parent_app.add_wall(pts)
                return

        if event.button() == Qt.RightButton:
            if self.is_panning:
                if self.pan_distance < 10 and self.clicked_cam_id and not event.modifiers():
                    self.parent_app.delete_camera(self.clicked_cam_id)
                self.is_panning = False
            elif self.is_moving_cam or self.is_rotating_cam or self.is_moving_legend:
                self.parent_app.save_state()  
                
            self.is_moving_cam = False
            self.is_rotating_cam = False
            self.is_moving_legend = False

        super().mouseReleaseEvent(event)

# ==========================================
# Main GUI Implementation
# ==========================================
class Xyk0TechOverlayTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Xyk0Tech CCTV Plan Overlayer - Movable Legends Edition")
        self.setGeometry(100, 100, 1400, 850)

        self.current_pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        
        self.camera_data = {}
        self.walls = {}  
        self.legends = {} # {page_index: {'x': x, 'y': y, 'scale': 100}}
        self.current_legend_items = []
        
        self.ordered_camera_ids = []
        self.active_cam_id = None
        self.unsaved_layout_changes = False
        
        self.history = []
        self.history_index = -1
        self.is_restoring = False
        
        self.load_global_settings()
        
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # ----------------- SIDEBAR (SCROLLABLE) -----------------
        sidebar_container = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_container)
        sidebar_layout.setAlignment(Qt.AlignTop)
        sidebar_layout.setSpacing(15)
        
        file_group = QGroupBox("1. Project Files")
        file_layout = QVBoxLayout()
        self.btn_load = QPushButton("Load Base PDF Plan")
        self.btn_load.clicked.connect(self.load_pdf_dialog)
        file_layout.addWidget(self.btn_load)

        nav_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("<< Prev")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.lbl_page_info = QLabel("Page 0 / 0")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.btn_next_page = QPushButton("Next >>")
        self.btn_next_page.clicked.connect(self.next_page)
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)
        nav_layout.addWidget(self.btn_prev_page)
        nav_layout.addWidget(self.lbl_page_info)
        nav_layout.addWidget(self.btn_next_page)
        file_layout.addLayout(nav_layout)

        file_h_layout = QHBoxLayout()
        self.btn_save_layout = QPushButton("Save Layout")
        self.btn_save_layout.clicked.connect(self.save_layout)
        self.btn_save_layout.setEnabled(False)
        self.btn_load_layout = QPushButton("Load Layout")
        self.btn_load_layout.clicked.connect(self.load_layout)
        file_h_layout.addWidget(self.btn_save_layout)
        file_h_layout.addWidget(self.btn_load_layout)
        file_layout.addLayout(file_h_layout)
        file_group.setLayout(file_layout)
        sidebar_layout.addWidget(file_group)

        tool_group = QGroupBox("Tool Mode")
        tool_layout = QVBoxLayout()
        self.tool_mode = QComboBox()
        self.tool_mode.addItems(["Tool: Place Camera", "Tool: Draw Straight Wall", "Tool: Draw Curved Wall"])
        tool_layout.addWidget(self.tool_mode)
        tool_group.setLayout(tool_layout)
        sidebar_layout.addWidget(tool_group)

        settings_group = QGroupBox("2. Camera Settings")
        form_layout = QFormLayout()
        
        type_layout = QHBoxLayout()
        self.cam_type_combo = QComboBox()
        self.cam_type_combo.addItems(self.camera_types.keys())
        self.cam_type_combo.currentTextChanged.connect(self.on_type_changed)
        type_layout.addWidget(self.cam_type_combo)
        
        self.btn_change_icon = QPushButton("Change Icon")
        self.btn_change_icon.clicked.connect(self.change_type_icon)
        type_layout.addWidget(self.btn_change_icon)
        form_layout.addRow("Type:", type_layout)

        self.cam_name_input = QLineEdit()
        self.cam_name_input.setPlaceholderText("Select cam to set label...")
        self.cam_name_input.setEnabled(False)
        self.cam_name_input.editingFinished.connect(self.sync_active_camera_name)
        form_layout.addRow("Name:", self.cam_name_input)

        self.btn_color = QPushButton("Pick Color")
        self.btn_color.clicked.connect(self.change_active_color)
        form_layout.addRow("Color:", self.btn_color)

        self.angle_spinbox = QSpinBox()
        self.angle_spinbox.setRange(0, 359)
        self.angle_spinbox.setSuffix(" °")
        self.angle_spinbox.setSingleStep(15)
        self.angle_spinbox.valueChanged.connect(self.sync_active_camera)
        self.angle_spinbox.editingFinished.connect(self.save_state)
        form_layout.addRow("Angle:", self.angle_spinbox)
        
        self.radius_spinbox = QSpinBox()
        self.radius_spinbox.setRange(10, 1000)
        self.radius_spinbox.setValue(80)
        self.radius_spinbox.setSuffix(" px")
        self.radius_spinbox.setSingleStep(10)
        self.radius_spinbox.valueChanged.connect(self.sync_active_camera)
        self.radius_spinbox.editingFinished.connect(self.save_state)
        form_layout.addRow("Radius/Dist:", self.radius_spinbox)

        self.fov_spinbox = QSpinBox()
        self.fov_spinbox.setRange(10, 360)
        self.fov_spinbox.setValue(360)
        self.fov_spinbox.setSuffix(" °")
        self.fov_spinbox.setSingleStep(5)
        self.fov_spinbox.valueChanged.connect(self.sync_active_camera)
        self.fov_spinbox.editingFinished.connect(self.save_state)
        form_layout.addRow("FOV Spread:", self.fov_spinbox)
        
        self.icon_scale_spinbox = QSpinBox()
        self.icon_scale_spinbox.setRange(10, 500)
        self.icon_scale_spinbox.setValue(100)
        self.icon_scale_spinbox.setSuffix(" %")
        self.icon_scale_spinbox.setSingleStep(10)
        self.icon_scale_spinbox.valueChanged.connect(self.sync_active_camera)
        self.icon_scale_spinbox.editingFinished.connect(self.save_state)
        form_layout.addRow("Icon Scale:", self.icon_scale_spinbox)

        self.opacity_spinbox = QSpinBox()
        self.opacity_spinbox.setRange(5, 100)
        self.opacity_spinbox.setValue(30)
        self.opacity_spinbox.setSuffix(" %")
        self.opacity_spinbox.setSingleStep(5)
        self.opacity_spinbox.valueChanged.connect(self.sync_active_camera)
        self.opacity_spinbox.editingFinished.connect(self.save_state)
        form_layout.addRow("FOV Opacity:", self.opacity_spinbox)

        self.chk_360 = QCheckBox("Show 360° Sweep Indicator")
        self.chk_360.clicked.connect(self.sync_active_camera)
        self.chk_360.clicked.connect(self.save_state)
        form_layout.addRow("", self.chk_360)

        self.btn_delete_cam = QPushButton("Delete Selected Camera")
        self.btn_delete_cam.clicked.connect(self.delete_selected_camera_ui)
        self.btn_delete_cam.setStyleSheet("background-color: #ffcccc; color: #cc0000; font-weight: bold;")
        self.btn_delete_cam.setEnabled(False)
        form_layout.addRow("", self.btn_delete_cam)

        instructions = (
            "<i>• <b>Camera Mode:</b> Click to drop.<br>"
            "• <b>Wall Modes:</b> Drag to draw line/curve.<br>"
            "• <b>Ctrl+Right Drag:</b> Move Cam / Legend Box<br>"
            "• <b>Right-Click Wall:</b> Delete Wall<br>"
            "• <b>Right-Drag:</b> Pan Canvas<br>"
            "• <b>ESC:</b> Cancel Drawing Wall</i>"
        )
        self.lbl_instruction = QLabel(instructions)
        form_layout.addRow("", self.lbl_instruction)
        settings_group.setLayout(form_layout)
        sidebar_layout.addWidget(settings_group)

        custom_group = QGroupBox("Add Custom Camera")
        custom_layout = QVBoxLayout()
        self.custom_name_input = QLineEdit()
        self.custom_name_input.setPlaceholderText("Type (e.g. LPR, Fisheye)")
        custom_layout.addWidget(self.custom_name_input)
        self.btn_upload_icon = QPushButton("Upload Icon & Add Type")
        self.btn_upload_icon.clicked.connect(self.add_custom_camera_type)
        custom_layout.addWidget(self.btn_upload_icon)
        custom_group.setLayout(custom_layout)
        sidebar_layout.addWidget(custom_group)

        edit_group = QGroupBox("Edits & Counts")
        edit_layout = QVBoxLayout()
        
        undo_redo_layout = QHBoxLayout()
        self.btn_undo = QPushButton("Undo (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton("Redo (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo)
        undo_redo_layout.addWidget(self.btn_undo)
        undo_redo_layout.addWidget(self.btn_redo)
        edit_layout.addLayout(undo_redo_layout)
        
        # LEGEND SCALE SPINBOX
        leg_scale_layout = QHBoxLayout()
        leg_scale_layout.addWidget(QLabel("Legend Scale:"))
        self.legend_scale_spinbox = QSpinBox()
        self.legend_scale_spinbox.setRange(10, 500)
        self.legend_scale_spinbox.setValue(100)
        self.legend_scale_spinbox.setSuffix(" %")
        self.legend_scale_spinbox.setSingleStep(10)
        self.legend_scale_spinbox.valueChanged.connect(self.sync_legend_scale)
        self.legend_scale_spinbox.editingFinished.connect(self.save_state)
        leg_scale_layout.addWidget(self.legend_scale_spinbox)
        edit_layout.addLayout(leg_scale_layout)
        
        self.lbl_counts = QLabel("Total: 0")
        self.lbl_counts.setStyleSheet("font-weight: bold; margin-top: 10px;")
        edit_layout.addWidget(self.lbl_counts)
        edit_group.setLayout(edit_layout)
        sidebar_layout.addWidget(edit_group)

        export_group = QGroupBox("3. Engineer Handoff")
        export_layout = QVBoxLayout()
        self.btn_export = QPushButton("Export Overlaid PDF")
        self.btn_export.clicked.connect(self.export_pdf)
        self.btn_export.setEnabled(False)
        export_layout.addWidget(self.btn_export)

        self.btn_export_csv = QPushButton("Export to CSV (Data)")
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_csv.setEnabled(False)
        export_layout.addWidget(self.btn_export_csv)
        
        self.btn_export_dxf = QPushButton("Export to DXF (Current Page)")
        self.btn_export_dxf.clicked.connect(self.export_dxf)
        self.btn_export_dxf.setEnabled(False)
        export_layout.addWidget(self.btn_export_dxf)

        export_group.setLayout(export_layout)
        sidebar_layout.addWidget(export_group)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar_container)
        sidebar_scroll.setMinimumWidth(320)
        sidebar_scroll.setMaximumWidth(380)

        # ----------------- CANVAS -----------------
        self.scene = QGraphicsScene()
        self.view = ClickableGraphicsView(self.scene, self)
        
        main_layout.addWidget(sidebar_scroll)
        main_layout.addWidget(self.view, 1)
        
        self.update_counts() 
        self.on_type_changed(self.cam_type_combo.currentText())

    # ==========================================
    # State Engine (Undo / Redo)
    # ==========================================
    def get_current_state(self):
        cams_out = [{"id": cid, "page": c.get("page", 0), "type": c["type"], "name": c.get("name", ""), "x": c["x"], "y": c["y"], "angle": c["angle"], "radius": c["radius"], "fov": c["fov"], "icon_scale": c.get("icon_scale", 100), "opacity": c.get("opacity", 30), "is_360": c.get("is_360", False), "color": c["color"].name()} for cid, c in self.camera_data.items()]
        walls_out = [{"id": wid, "page": w.get("page", 0), "pts": w["pts"]} for wid, w in self.walls.items()]
        return {"cameras": cams_out, "walls": walls_out, "legends": self.legends}

    def save_state(self):
        if self.is_restoring: return
        state = self.get_current_state()
        
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        self.history_index += 1
        
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_index -= 1

    def restore_state(self, state):
        self.is_restoring = True
        
        for cam in self.camera_data.values():
            for item in cam.get("ui_items", []): self.scene.removeItem(item)
        for wall in self.walls.values():
            if wall.get('item'): self.scene.removeItem(wall['item'])
            
        self.camera_data.clear()
        self.walls.clear()
        self.ordered_camera_ids.clear()
        self.active_cam_id = None
        self.cam_name_input.clear()
        self.cam_name_input.setEnabled(False)
        self.btn_delete_cam.setEnabled(False)
        
        # Load legends, converting JSON string keys back to integers for page indexing
        self.legends = {int(k): dict(v) for k, v in state.get("legends", {}).items()}
        
        for w in state.get("walls", []):
            wall_id = w["id"]
            self.walls[wall_id] = {"id": wall_id, "pts": w["pts"], "page": w.get("page", 0), "item": None}
            
        for cam in state.get("cameras", []):
            cam_id = cam["id"]
            base_col = self.camera_types.get(cam["type"], {}).get("color", QColor(Qt.gray))
            self.camera_data[cam_id] = {
                "id": cam_id, "page": cam.get("page", 0), "type": cam["type"], "name": cam.get("name", ""), "x": cam["x"], "y": cam["y"],
                "angle": cam["angle"], "radius": cam["radius"], "fov": cam["fov"], "icon_scale": cam.get("icon_scale", 100), "opacity": cam.get("opacity", 30), "is_360": cam.get("is_360", False),
                "color": QColor(cam.get("color", base_col.name())), "ui_items": [], "export_polygons": []
            }
            self.ordered_camera_ids.append(cam_id)
            
        self.render_page() 
        self.is_restoring = False

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.restore_state(self.history[self.history_index])
            self.mark_layout_dirty()

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.restore_state(self.history[self.history_index])
            self.mark_layout_dirty()

    # ==========================================
    # Global Settings I/O 
    # ==========================================
    def load_global_settings(self):
        self.camera_types = {}
        config_file = "xyk0tech_config.json"
        default_types = {
            "Dome": {"color": QColor(Qt.blue), "is_custom": False, "def_rad": 80, "def_fov": 360, "icon_path": None, "def_icon_scale": 100, "def_opacity": 30},
            "Bullet": {"color": QColor(Qt.red), "is_custom": False, "def_rad": 120, "def_fov": 60, "icon_path": None, "def_icon_scale": 100, "def_opacity": 30},
            "PTZ": {"color": QColor(Qt.darkGreen), "is_custom": False, "def_rad": 200, "def_fov": 90, "icon_path": None, "def_icon_scale": 100, "def_opacity": 30},
            "Speaker": {"color": QColor("#FFA500"), "is_custom": False, "def_rad": 180, "def_fov": 90, "icon_path": None, "def_icon_scale": 100, "def_opacity": 30}
        }
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f: data = json.load(f)
                for k, v in data.items():
                    self.camera_types[k] = {
                        "color": QColor(v.get("color", "#808080")), "is_custom": v.get("is_custom", False),
                        "def_rad": v.get("def_rad", 100), "def_fov": v.get("def_fov", 75), "icon_path": v.get("icon_path"),
                        "def_icon_scale": v.get("def_icon_scale", 100), "def_opacity": v.get("def_opacity", 30)
                    }
                    if self.camera_types[k]["icon_path"] and not os.path.exists(self.camera_types[k]["icon_path"]):
                        self.camera_types[k]["icon_path"] = None 
            except: self.camera_types = default_types
        else: self.camera_types = default_types

    def save_global_settings(self):
        config_data = {}
        for k, v in self.camera_types.items():
            config_data[k] = {"color": v["color"].name(), "is_custom": v["is_custom"], "def_rad": v["def_rad"], "def_fov": v["def_fov"], "icon_path": v["icon_path"], "def_icon_scale": v.get("def_icon_scale", 100), "def_opacity": v.get("def_opacity", 30)}
        try:
            with open("xyk0tech_config.json", 'w') as f: json.dump(config_data, f, indent=4)
        except: pass

    def mark_layout_dirty(self):
        if self.current_pdf_path: self.unsaved_layout_changes = True

    def closeEvent(self, event):
        if self.unsaved_layout_changes:
            choice = QMessageBox.question(self, "Unsaved Layout Changes", "Save layout before closing?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Save:
                if not self.save_layout():
                    event.ignore()
                    return
            elif choice == QMessageBox.Cancel:
                event.ignore()
                return
        self.save_global_settings()
        event.accept()

    # ==========================================
    # Project Layout I/O & Page Rendering
    # ==========================================
    def load_pdf_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Plan", "", "PDF Files (*.pdf)")
        if file_path: self.load_base_pdf(file_path)

    def load_base_pdf(self, file_path):
        try:
            self.current_pdf_path = file_path
            self.camera_data.clear()
            self.walls.clear()
            self.legends.clear()
            self.ordered_camera_ids.clear()
            self.active_cam_id = None
            self.cam_name_input.clear()
            self.cam_name_input.setEnabled(False)
            self.btn_delete_cam.setEnabled(False)
            
            doc = fitz.open(file_path)
            self.total_pages = doc.page_count
            doc.close()
            
            self.current_page = 0
            self.render_page()
            
            self.history = []
            self.history_index = -1
            self.save_state()
            
            self.btn_export.setEnabled(True)
            self.btn_export_csv.setEnabled(True)
            self.btn_export_dxf.setEnabled(True)
            self.btn_save_layout.setEnabled(True)
            self.unsaved_layout_changes = False
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to load PDF: {str(e)}")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.render_page()

    def render_page(self):
        if not self.current_pdf_path: return
        
        self.scene.clear()
        self.current_legend_items.clear()
        
        if self.active_cam_id and self.camera_data.get(self.active_cam_id, {}).get("page", 0) != self.current_page:
            self.deselect_camera()
            
        doc = fitz.open(self.current_pdf_path)
        page = doc[self.current_page]
        page.set_rotation(0)
        pix = page.get_pixmap()
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        self.scene.addPixmap(QPixmap.fromImage(img))
        doc.close()

        for wall in self.walls.values():
            if wall.get("page", 0) == self.current_page:
                pts = wall["pts"]
                path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
                for p in pts[1:]: path.lineTo(QPointF(p[0], p[1]))
                item = self.scene.addPath(path, QPen(Qt.yellow, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                item.setData(0, wall["id"])
                item.setData(1, "wall")
                wall["item"] = item
            else:
                wall["item"] = None
                
        for cam_id, cam in self.camera_data.items():
            cam["ui_items"] = [] 
            if cam.get("page", 0) == self.current_page:
                self.draw_camera_ui(cam_id)
                
        self.lbl_page_info.setText(f"Page {self.current_page + 1} / {self.total_pages}")
        self.btn_prev_page.setEnabled(self.current_page > 0)
        self.btn_next_page.setEnabled(self.current_page < self.total_pages - 1)
        self.update_counts()

    def save_layout(self):
        if not self.current_pdf_path: return False
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Layout File", "", "JSON Files (*.json)")
        if not save_path: return False

        types_out = {k: {"icon_path": v.get("icon_path", ""), "def_rad": v.get("def_rad", 100), "def_fov": v.get("def_fov", 75), "def_icon_scale": v.get("def_icon_scale", 100), "def_opacity": v.get("def_opacity", 30), "is_custom": v.get("is_custom", False)} for k, v in self.camera_types.items()}
        project_data = {"pdf_path": self.current_pdf_path, "camera_types": types_out}
        project_data.update(self.get_current_state())

        try:
            with open(save_path, 'w') as f: json.dump(project_data, f, indent=4)
            self.unsaved_layout_changes = False
            QMessageBox.information(self, "Success", "Layout saved successfully.")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save layout: {str(e)}")
            return False

    def load_layout(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Layout File", "", "JSON Files (*.json)")
        if not file_path: return
        try:
            with open(file_path, 'r') as f: project_data = json.load(f)
            pdf_path = project_data.get("pdf_path")
            if not pdf_path or not os.path.exists(pdf_path):
                QMessageBox.warning(self, "PDF Missing", "The associated PDF file could not be found. Please locate it manually.")
                pdf_path, _ = QFileDialog.getOpenFileName(self, "Locate Associated PDF", "", "PDF Files (*.pdf)")
                if not pdf_path: return 

            self.load_base_pdf(pdf_path)

            loaded_types = project_data.get("camera_types", project_data.get("custom_types", {}))
            for k, v in loaded_types.items():
                if k not in self.camera_types:
                    self.camera_types[k] = {"color": QColor(v.get("color", "#808080")), "is_custom": True, "icon_path": v.get("icon_path", ""), "def_rad": v.get("def_rad", 100), "def_fov": v.get("def_fov", 75), "def_icon_scale": v.get("def_icon_scale", 100), "def_opacity": v.get("def_opacity", 30)}
                    self.cam_type_combo.addItem(k)
            self.save_global_settings()

            walls_adapted = []
            for w in project_data.get("walls", []):
                if "pts" in w: walls_adapted.append(w)
                else: walls_adapted.append({"id": w["id"], "page": 0, "pts": [(w["x1"], w["y1"]), (w["x2"], w["y2"])]})
            project_data["walls"] = walls_adapted
            
            self.restore_state(project_data)
            
            self.history = []
            self.history_index = -1
            self.save_state()
            self.unsaved_layout_changes = False
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to load layout: {str(e)}")

    # ==========================================
    # Exports
    # ==========================================
    def export_csv(self):
        if not self.camera_data: return
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Data", "", "CSV Files (*.csv)")
        if save_path:
            with open(save_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Page', 'Camera_ID', 'Name_Label', 'Type', 'X', 'Y', 'Angle', 'Radius', 'FOV', 'Icon_Scale', 'Opacity', 'Is_360'])
                for cam in self.camera_data.values(): 
                    writer.writerow([cam.get('page', 0) + 1, cam['id'], cam.get("name", ""), cam['type'], round(cam['x'], 2), round(cam['y'], 2), cam['angle'], cam['radius'], cam['fov'], cam.get('icon_scale', 100), cam.get('opacity', 30), cam.get('is_360', False)])

    def export_dxf(self):
        if not self.camera_data: return
        try: import ezdxf
        except ImportError: return QMessageBox.warning(self, "Missing Library", "Please run 'pip install ezdxf' in terminal.")
        save_path, _ = QFileDialog.getSaveFileName(self, "Save CAD (Current Page Only)", "", "DXF Files (*.dxf)")
        if save_path:
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            pdf_doc = fitz.open(self.current_pdf_path)
            page = pdf_doc[self.current_page]
            page.set_rotation(0)
            pdf_height = page.rect.height
            for cam in self.camera_data.values():
                if cam.get("page", 0) == self.current_page:
                    x, y = cam['x'], pdf_height - cam['y']
                    s = cam.get("icon_scale", 100) / 100.0
                    msp.add_circle((x, y), radius=10 * s, dxfattribs={'color': 1})
                    display_name = cam.get("name") if cam.get("name") else cam['type']
                    msp.add_text(display_name, dxfattribs={'height': 15 * s, 'color': 2}).set_placement((x + 15 * s, y))
            for wall in self.walls.values():
                if wall.get("page", 0) == self.current_page:
                    pts = [(p[0], pdf_height - p[1]) for p in wall['pts']]
                    msp.add_lwpolyline(pts, dxfattribs={'color': 3})
            doc.saveas(save_path)
            QMessageBox.information(self, "Success", "AutoCAD DXF generated for current page.")

    def export_pdf(self):
            if not self.current_pdf_path or not self.camera_data: return
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Multi-Page PDF", "", "PDF Files (*.pdf)")
            if save_path:
                try:
                    doc = fitz.open(self.current_pdf_path)
                    for page_idx in range(doc.page_count):
                        page = doc[page_idx]
                        page.set_rotation(0)
                    
                        page_cams = {k: v for k, v in self.camera_data.items() if v.get("page", 0) == page_idx}
                        page_walls = {k: v for k, v in self.walls.items() if v.get("page", 0) == page_idx}
                    
                        for cam in page_cams.values(): 
                            x, y, angle, radius, fov = cam['x'], cam['y'], cam['angle'], cam['radius'], cam['fov']
                        
                            base_poly = calculate_fov_polygon(x, y, radius, angle, fov)
                            fov_path = QPainterPath()
                            fov_path.setFillRule(Qt.WindingFill) 
                            fov_path.addPolygon(QPolygonF([QPointF(p[0], p[1]) for p in base_poly]))

                            total_shadow = QPainterPath()
                            total_shadow.setFillRule(Qt.WindingFill)
                        
                            cam_bounds = QRectF(x - radius, y - radius, radius * 2, radius * 2)

                            for wall in page_walls.values():
                                pts = wall['pts']
                                min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
                                min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
                            
                                # FIXED: Added a 10px mathematical padding to the wall's invisible bounding box.
                                # This prevents perfectly straight horizontal or vertical walls (which have a width/height of 0)
                                # from failing the geometry intersection check.
                                wall_rect = QRectF(min_x - 5, min_y - 5, (max_x - min_x) + 10, (max_y - min_y) + 10)
                            
                                if wall_rect.intersects(cam_bounds):
                                    for i in range(len(pts) - 1):
                                        p1, p2 = pts[i], pts[i+1]
                                        shadow_pts = calculate_shadow_polygon(x, y, p1[0], p1[1], p2[0], p2[1])
                                        shadow_path = QPainterPath()
                                        shadow_path.addPolygon(QPolygonF(shadow_pts))
                                        shadow_path.closeSubpath()
                                    
                                        if total_shadow.isEmpty():
                                            total_shadow = shadow_path
                                        else:
                                            total_shadow = total_shadow.united(shadow_path)

                            if not total_shadow.isEmpty():
                                fov_path = fov_path.subtracted(total_shadow)

                            cam["export_polygons"] = [[(pt.x(), pt.y()) for pt in poly] for poly in fov_path.toFillPolygons()]
                            add_camera_to_pdf(page, cam['x'], cam['y'], cam, self.camera_types)
                    
                        if page_walls:
                            wall_shape = page.new_shape()
                            has_valid_walls = False
                            for wall in page_walls.values():
                                if len(wall['pts']) > 1:
                                    wall_shape.draw_polyline(wall['pts'])
                                    has_valid_walls = True
                            if has_valid_walls:
                                wall_shape.finish(color=(1, 1, 0), width=3)
                                wall_shape.commit()

                        leg_data = self.legends.get(page_idx, {'x': 10, 'y': 10, 'scale': 100})
                        if page_idx == doc.page_count - 1:
                            draw_legend_on_pdf(page, page_cams, self.camera_types, global_cams=self.camera_data, lx=leg_data['x'], ly=leg_data['y'], custom_scale=leg_data['scale'])
                        else:
                            draw_legend_on_pdf(page, page_cams, self.camera_types, lx=leg_data['x'], ly=leg_data['y'], custom_scale=leg_data['scale'])
                        
                    doc.save(save_path)
                    doc.close()
                    QMessageBox.information(self, "Success", "Multi-Page PDF exported successfully.")
                except Exception as e: QMessageBox.critical(self, "Error", f"Failed to save PDF: {str(e)}")

    # ==========================================
    # Logic Handling
    # ==========================================
    def draw_legend_ui(self):
        if not self.current_pdf_path: return
        for item in self.current_legend_items:
            self.scene.removeItem(item)
        self.current_legend_items.clear()

        leg_data = self.legends.setdefault(self.current_page, {'x': 10, 'y': 10, 'scale': 100})
        lx, ly = leg_data['x'], leg_data['y']
        c_scale = leg_data['scale'] / 100.0

        page_cams = {k: v for k, v in self.camera_data.items() if v.get("page", 0) == self.current_page}
        p_counts = set(c['type'] for c in page_cams.values())

        is_last_page = (self.current_page == self.total_pages - 1)
        g_counts = set()
        if is_last_page:
            g_counts = set(c['type'] for c in self.camera_data.values())

        num_items = max(1, len(p_counts)) + (max(1, len(g_counts)) + 1 if is_last_page else 0)

        bg_width = self.scene.sceneRect().width() if self.scene.sceneRect().width() > 0 else 1200.0
        base_scale = max(1.0, bg_width / 1200.0) * c_scale

        width = 200 * base_scale
        height = (30 + (num_items * 25)) * base_scale
        if is_last_page: height += 15 * base_scale

        rect_item = self.scene.addRect(lx, ly, width, height, QPen(Qt.black, 2, Qt.DashLine), QBrush(QColor(255, 255, 255, 200)))
        rect_item.setData(0, "legend")
        rect_item.setData(1, "legend")
        
        font_sz = max(6, int(10 * base_scale))
        text_item = self.scene.addText("")
        text_item.setHtml(f"<div style='color: black; font-weight: bold; font-family: sans-serif; font-size: {font_sz}pt;'>LEGEND BOX<br>(Ctrl+Right Drag)</div>")
        text_item.setPos(lx + 5 * base_scale, ly + 5 * base_scale)
        text_item.setData(0, "legend")
        text_item.setData(1, "legend")

        self.current_legend_items.extend([rect_item, text_item])
        
        self.legend_scale_spinbox.blockSignals(True)
        self.legend_scale_spinbox.setValue(leg_data['scale'])
        self.legend_scale_spinbox.blockSignals(False)

    def sync_legend_scale(self):
        if self.current_pdf_path:
            self.legends[self.current_page]['scale'] = self.legend_scale_spinbox.value()
            self.draw_legend_ui()
            self.mark_layout_dirty()

    def update_counts(self):
        page_cam_tot, page_spk_tot = 0, 0
        page_counts = {k: 0 for k in self.camera_types.keys()}
        
        grand_cam_tot, grand_spk_tot = 0, 0
        grand_counts = {k: 0 for k in self.camera_types.keys()}
        
        for cam in self.camera_data.values():
            ctype = cam["type"]
            is_speaker = (ctype == "Speaker")
            
            if ctype in grand_counts: grand_counts[ctype] += 1
            if is_speaker: grand_spk_tot += 1
            else: grand_cam_tot += 1
                
            if cam.get("page", 0) == self.current_page:
                if ctype in page_counts: page_counts[ctype] += 1
                if is_speaker: page_spk_tot += 1
                else: page_cam_tot += 1
                
        text = f"PAGE {self.current_page + 1} SUMMARY\n"
        text += f"Cameras: {page_cam_tot} | Speakers: {page_spk_tot}\n"
        for k, v in page_counts.items():
            if v > 0: text += f" - {k}: {v}\n"
            
        text += f"\nGRAND TOTAL\n"
        text += f"Cameras: {grand_cam_tot} | Speakers: {grand_spk_tot}\n"
        for k, v in grand_counts.items():
            if v > 0: text += f" - {k}: {v}\n"
            
        self.lbl_counts.setText(text)
        self.draw_legend_ui()

    def update_color_button_style(self, color):
        self.btn_color.setStyleSheet(f"background-color: {color.name()}; color: {'white' if color.lightness() < 128 else 'black'}; font-weight: bold;" if color else "")

    def sync_active_camera_name(self):
        if self.active_cam_id and self.active_cam_id in self.camera_data:
            new_name = self.cam_name_input.text().strip()
            if self.camera_data[self.active_cam_id].get("name") != new_name:
                self.camera_data[self.active_cam_id]["name"] = new_name
                self.draw_camera_ui(self.active_cam_id)
                self.mark_layout_dirty()
                self.save_state()

    def change_active_color(self):
        if self.active_cam_id:
            col = QColorDialog.getColor(self.camera_data[self.active_cam_id]["color"], self, "Select Range Color")
            if col.isValid():
                self.camera_data[self.active_cam_id]["color"] = col
                self.update_color_button_style(col)
                self.draw_camera_ui(self.active_cam_id)
                self.mark_layout_dirty()
                self.save_state()
        else:
            cam_type = self.cam_type_combo.currentText()
            col = QColorDialog.getColor(self.camera_types.get(cam_type, {}).get("color", QColor(Qt.gray)), self, f"Select Default Color")
            if col.isValid():
                self.camera_types[cam_type]["color"] = col
                self.update_color_button_style(col)
                self.save_global_settings()

    def change_type_icon(self):
        cam_type = self.cam_type_combo.currentText()
        path, _ = QFileDialog.getOpenFileName(self, f"Select Icon", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.camera_types[cam_type]["icon_path"] = path
            self.save_global_settings()
            self.mark_layout_dirty()
            for cid in self.ordered_camera_ids:
                if self.camera_data[cid]['type'] == cam_type and self.camera_data[cid].get("page", 0) == self.current_page: 
                    self.draw_camera_ui(cid)

    def on_type_changed(self, cam_type):
        if not self.active_cam_id:
            info = self.camera_types.get(cam_type, {})
            self.radius_spinbox.blockSignals(True)
            self.fov_spinbox.blockSignals(True)
            self.icon_scale_spinbox.blockSignals(True)
            self.opacity_spinbox.blockSignals(True)
            
            self.radius_spinbox.setValue(info.get("def_rad", 100))
            self.fov_spinbox.setValue(info.get("def_fov", 75))
            self.icon_scale_spinbox.setValue(info.get("def_icon_scale", 100))
            self.opacity_spinbox.setValue(info.get("def_opacity", 30))
            
            self.radius_spinbox.blockSignals(False)
            self.fov_spinbox.blockSignals(False)
            self.icon_scale_spinbox.blockSignals(False)
            self.opacity_spinbox.blockSignals(False)
            
            self.btn_color.setEnabled(True)
            self.update_color_button_style(info.get("color", QColor(Qt.gray)))

    def add_custom_camera_type(self):
        name = self.custom_name_input.text().strip()
        if not name or name in self.camera_types: return QMessageBox.warning(self, "Error", "Invalid or duplicate name.")
        path, _ = QFileDialog.getOpenFileName(self, "Select Icon", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.camera_types[name] = {"color": QColor(Qt.gray), "is_custom": True, "icon_path": path, "def_rad": 100, "def_fov": 75, "def_icon_scale": 100, "def_opacity": 30}
            self.cam_type_combo.addItem(name)
            self.cam_type_combo.setCurrentText(name)
            self.custom_name_input.clear()
            self.save_global_settings()
            self.mark_layout_dirty()

    def add_wall(self, pts, wall_id=None):
        if not wall_id: wall_id = str(uuid.uuid4())
        
        path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
        for p in pts[1:]: path.lineTo(QPointF(p[0], p[1]))
        
        item = self.scene.addPath(path, QPen(Qt.yellow, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        item.setData(0, wall_id)
        item.setData(1, "wall") 
        self.walls[wall_id] = {"id": wall_id, "page": self.current_page, "pts": pts, "item": item}
        
        if not self.is_restoring:
            self.mark_layout_dirty()
            for cam_id, cam in self.camera_data.items(): 
                if cam.get("page", 0) == self.current_page: self.draw_camera_ui(cam_id)
            self.save_state()

    def delete_wall(self, wall_id):
        if wall_id in self.walls:
            if self.walls[wall_id]['item']: self.scene.removeItem(self.walls[wall_id]['item'])
            del self.walls[wall_id]
            self.mark_layout_dirty()
            for cam_id, cam in self.camera_data.items(): 
                if cam.get("page", 0) == self.current_page: self.draw_camera_ui(cam_id)
            self.save_state()

    def add_camera_marker(self, x, y):
        cam_type = self.cam_type_combo.currentText()
        cam_id = str(uuid.uuid4())
        
        total_of_type = sum(1 for c in self.camera_data.values() if c["type"] == cam_type) + 1
        generated_name = f"{cam_type} {total_of_type}"
        
        self.camera_data[cam_id] = {
            "id": cam_id, "page": self.current_page, "type": cam_type, "name": generated_name, "x": x, "y": y, 
            "angle": self.angle_spinbox.value(), "radius": self.radius_spinbox.value(), "fov": self.fov_spinbox.value(), 
            "icon_scale": self.icon_scale_spinbox.value(), "opacity": self.opacity_spinbox.value(), "is_360": self.chk_360.isChecked(),
            "color": QColor(self.camera_types.get(cam_type, {}).get("color", QColor(Qt.gray))), "ui_items": [], "export_polygons": []
        }
        self.ordered_camera_ids.append(cam_id)
        self.draw_camera_ui(cam_id)
        self.select_camera(cam_id)
        self.update_counts()
        self.mark_layout_dirty()
        self.save_state()

    def draw_camera_ui(self, cam_id):
            cam = self.camera_data[cam_id]
            for item in cam.get("ui_items", []): self.scene.removeItem(item)
        
            x, y, angle, radius, fov = cam['x'], cam['y'], cam['angle'], cam['radius'], cam['fov']
            type_info = self.camera_types.get(cam['type'], {})
            s = cam.get("icon_scale", 100) / 100.0
            opacity_pct = cam.get("opacity", 30)
        
            is_active = (cam_id == self.active_cam_id)
            base_color = cam["color"]
            
            alpha = int(255 * (opacity_pct / 100.0))
            active_alpha = min(255, alpha + 50) if is_active else alpha
            
            fill_brush = QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), active_alpha))
            stroke_pen = QPen(Qt.black, 1.5, Qt.DashLine) if is_active else QPen(Qt.NoPen)

            base_poly = calculate_fov_polygon(x, y, radius, angle, fov)
            fov_path = QPainterPath()
            fov_path.setFillRule(Qt.WindingFill) 
            fov_path.addPolygon(QPolygonF([QPointF(p[0], p[1]) for p in base_poly]))

            total_shadow = QPainterPath()
            total_shadow.setFillRule(Qt.WindingFill)
            
            cam_bounds = QRectF(x - radius, y - radius, radius * 2, radius * 2)

            for wall in self.walls.values():
                if wall.get("page", 0) == self.current_page and wall['item'] and wall['item'].sceneBoundingRect().intersects(cam_bounds):
                    pts = wall['pts']
                    for i in range(len(pts) - 1):
                        p1, p2 = pts[i], pts[i+1]
                        shadow_pts = calculate_shadow_polygon(x, y, p1[0], p1[1], p2[0], p2[1])
                        shadow_path = QPainterPath()
                        shadow_path.addPolygon(QPolygonF(shadow_pts))
                        shadow_path.closeSubpath()
                        
                        if total_shadow.isEmpty():
                            total_shadow = shadow_path
                        else:
                            total_shadow = total_shadow.united(shadow_path)

            if not total_shadow.isEmpty():
                fov_path = fov_path.subtracted(total_shadow)

            cam["export_polygons"] = [[(pt.x(), pt.y()) for pt in poly] for poly in fov_path.toFillPolygons()]

            drawn_items = [self.scene.addPath(fov_path, stroke_pen, fill_brush)]

            if cam['type'] == 'Speaker':
                wave_pen = QPen(base_color, max(1.5, 2*s))
                for w_dist in [radius * 0.3, radius * 0.6, radius * 0.9]:
                    w_rect = QRectF(x - w_dist, y - w_dist, w_dist*2, w_dist*2)
                    w_path = QPainterPath()
                    w_path.arcMoveTo(w_rect, angle - fov/2)
                    w_path.arcTo(w_rect, angle - fov/2, fov)
                    drawn_items.append(self.scene.addPath(w_path, wave_pen))

            if cam.get("is_360", False):
                arc_rad = 18 * s
                arc_rect = QRectF(x - arc_rad, y - arc_rad, arc_rad * 2, arc_rad * 2)
                arc_path = QPainterPath()
                
                start_ang = angle + 45
                arc_path.arcMoveTo(arc_rect, -start_ang) 
                arc_path.arcTo(arc_rect, -start_ang, -270) 
                arc_pen = QPen(base_color, max(1.5, 2*s), Qt.DashLine)
                drawn_items.append(self.scene.addPath(arc_path, arc_pen))
                
                arrow_ang = math.radians(start_ang + 270)
                ax = x + arc_rad * math.cos(arrow_ang)
                ay = y - arc_rad * math.sin(arrow_ang)
                
                tg = arrow_ang + math.pi/2
                arrow_poly = QPolygonF([
                    QPointF(ax, ay),
                    QPointF(ax + 5*s * math.cos(tg + 2.5), ay - 5*s * math.sin(tg + 2.5)),
                    QPointF(ax + 5*s * math.cos(tg - 2.5), ay - 5*s * math.sin(tg - 2.5))
                ])
                drawn_items.append(self.scene.addPolygon(arrow_poly, QPen(Qt.NoPen), QBrush(base_color)))

            if type_info.get("icon_path") and os.path.exists(type_info.get("icon_path", "")):
                icon_sz = int(24 * s)
                half_sz = icon_sz / 2.0
                pixmap = QPixmap(type_info["icon_path"]).scaled(icon_sz, icon_sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_item = self.scene.addPixmap(pixmap)
                icon_item.setPos(x - half_sz, y - half_sz)
                drawn_items.append(icon_item)
            elif cam['type'] == 'Speaker':
                def rot_pt(px, py, cx, cy, ang_deg):
                    rad = math.radians(ang_deg)
                    nx = cx + (px - cx)*math.cos(rad) - (py - cy)*math.sin(rad)
                    ny = cy - (px - cx)*math.sin(rad) - (py - cy)*math.cos(rad)
                    return QPointF(nx, ny)
                spk_pts = [
                    rot_pt(x - 4*s, y - 3*s, x, y, angle), rot_pt(x + 2*s, y - 3*s, x, y, angle),
                    rot_pt(x + 8*s, y - 7*s, x, y, angle), rot_pt(x + 8*s, y + 7*s, x, y, angle),
                    rot_pt(x + 2*s, y + 3*s, x, y, angle), rot_pt(x - 4*s, y + 3*s, x, y, angle)
                ]
                drawn_items.append(self.scene.addPolygon(QPolygonF(spk_pts), QPen(Qt.black), QBrush(base_color)))
            else:
                drawn_items.append(self.scene.addEllipse(x - 8*s, y - 8*s, 16*s, 16*s, QPen(Qt.black), QBrush(base_color)))
                if cam['type'] in ["Bullet", "PTZ"]:
                    drawn_items.append(self.scene.addLine(x, y, x + 30*s * math.cos(math.radians(angle)), y - 30*s * math.sin(math.radians(angle)), QPen(base_color, max(1, 2*s))))

            cam_name = cam.get("name", "")
            if cam_name:
                font_sz = max(6, int(10 * s))
                text_item = self.scene.addText("")
                text_item.setHtml(f"<div style='color: black; background-color: rgba(255, 255, 255, 0.8); padding: 1px 3px; font-size: {font_sz}pt;'><b>{cam_name}</b></div>")
                text_item.setPos(x + 12*s, y - (10 + 15*s))
                drawn_items.append(text_item)

            for item in drawn_items:
                item.setData(0, cam_id)
                item.setData(1, "camera") 
            cam["ui_items"] = drawn_items

    def select_camera(self, cam_id):
        prev_active = self.active_cam_id
        self.active_cam_id = cam_id
        if prev_active and prev_active in self.camera_data and self.camera_data[prev_active].get("page", 0) == self.current_page: 
            self.draw_camera_ui(prev_active)
        
        cam = self.camera_data[cam_id]
        
        self.cam_type_combo.blockSignals(True)
        self.angle_spinbox.blockSignals(True)
        self.radius_spinbox.blockSignals(True)
        self.fov_spinbox.blockSignals(True)
        self.icon_scale_spinbox.blockSignals(True)
        self.opacity_spinbox.blockSignals(True)
        self.chk_360.blockSignals(True)
        self.cam_name_input.blockSignals(True)
        
        self.cam_type_combo.setCurrentText(cam['type'])
        self.angle_spinbox.setValue(cam['angle'])
        self.radius_spinbox.setValue(cam['radius'])
        self.fov_spinbox.setValue(cam['fov'])
        self.icon_scale_spinbox.setValue(cam.get('icon_scale', 100))
        self.opacity_spinbox.setValue(cam.get('opacity', 30))
        self.chk_360.setChecked(cam.get("is_360", False))
        self.cam_name_input.setText(cam.get("name", ""))
        
        self.cam_type_combo.blockSignals(False)
        self.angle_spinbox.blockSignals(False)
        self.radius_spinbox.blockSignals(False)
        self.fov_spinbox.blockSignals(False)
        self.icon_scale_spinbox.blockSignals(False)
        self.opacity_spinbox.blockSignals(False)
        self.chk_360.blockSignals(False)
        self.cam_name_input.blockSignals(False)
        
        self.btn_color.setEnabled(True)
        self.cam_name_input.setEnabled(True)
        self.btn_delete_cam.setEnabled(True)
        self.update_color_button_style(cam["color"])
        if cam.get("page", 0) == self.current_page:
            self.draw_camera_ui(cam_id)

    def deselect_camera(self):
        if self.active_cam_id:
            cam_id = self.active_cam_id
            self.active_cam_id = None
            
            self.cam_name_input.blockSignals(True)
            self.cam_name_input.clear()
            self.cam_name_input.setEnabled(False)
            self.btn_delete_cam.setEnabled(False)
            self.cam_name_input.blockSignals(False)
            
            if cam_id in self.camera_data and self.camera_data[cam_id].get("page", 0) == self.current_page: 
                self.draw_camera_ui(cam_id)
            self.on_type_changed(self.cam_type_combo.currentText())

    def sync_active_camera(self):
        if self.active_cam_id and self.active_cam_id in self.camera_data:
            self.camera_data[self.active_cam_id]['angle'] = self.angle_spinbox.value()
            self.camera_data[self.active_cam_id]['radius'] = self.radius_spinbox.value()
            self.camera_data[self.active_cam_id]['fov'] = self.fov_spinbox.value()
            self.camera_data[self.active_cam_id]['icon_scale'] = self.icon_scale_spinbox.value()
            self.camera_data[self.active_cam_id]['opacity'] = self.opacity_spinbox.value()
            self.camera_data[self.active_cam_id]['is_360'] = self.chk_360.isChecked()
            if self.camera_data[self.active_cam_id].get("page", 0) == self.current_page:
                self.draw_camera_ui(self.active_cam_id)
            self.mark_layout_dirty()

    def update_cam_transform(self, cam_id, x=None, y=None, angle=None):
        if x is not None and y is not None: self.camera_data[cam_id]['x'], self.camera_data[cam_id]['y'] = x, y
        if angle is not None:
            self.camera_data[cam_id]['angle'] = angle
            if cam_id == self.active_cam_id:
                self.angle_spinbox.blockSignals(True)
                self.angle_spinbox.setValue(angle)
                self.angle_spinbox.blockSignals(False)
        if self.camera_data[cam_id].get("page", 0) == self.current_page:
            self.draw_camera_ui(cam_id)
        self.mark_layout_dirty()

    def delete_selected_camera_ui(self):
        if self.active_cam_id:
            self.delete_camera(self.active_cam_id)

    def delete_camera(self, cam_id):
        if cam_id in self.camera_data:
            for item in self.camera_data[cam_id].get("ui_items", []): self.scene.removeItem(item)
            del self.camera_data[cam_id]
            self.ordered_camera_ids.remove(cam_id)
            if self.active_cam_id == cam_id: self.deselect_camera()
            self.update_counts()
            self.mark_layout_dirty()
            self.save_state()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Xyk0TechOverlayTool()
    window.show()
    sys.exit(app.exec())