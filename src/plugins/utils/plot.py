from __future__ import annotations
from enum import Enum
from typing import Union, Tuple, List, Optional
from PIL import Image, ImageFont, ImageDraw, ImageFilter, ImageEnhance
from PIL.ImageFont import ImageFont as Font
import threading
import contextvars
from dataclasses import dataclass
import os
import numpy as np
from copy import deepcopy
import math
from pilmoji import Pilmoji
from pilmoji import getsize as getsize_emoji
from pilmoji.source import GoogleEmojiSource
import emoji

DEBUG_MODE = False

# =========================== 绘图 =========================== #

ALIGN_MAP = {
    'c': ('c', 'c'), 'l': ('l', 'c'), 'r': ('r', 'c'), 't': ('c', 't'), 'b': ('c', 'b'),
    'tl': ('l', 't'), 'tr': ('r', 't'), 'bl': ('l', 'b'), 'br': ('r', 'b'),
    'lt': ('l', 't'), 'lb': ('l', 'b'), 'rt': ('r', 't'), 'rb': ('r', 'b'), 
}

def crop_by_align(original_size, crop_size, align):
    w, h = original_size
    cw, ch = crop_size
    assert cw <= w and ch <= h, "Crop size must be smaller than original size"
    x, y = 0, 0
    xa, ya = ALIGN_MAP[align]
    if xa == 'l':
        x = 0
    elif xa == 'r':
        x = w - cw
    elif xa == 'c':
        x = (w - cw) // 2
    if ya == 't':
        y = 0
    elif ya == 'b':
        y = h - ch
    elif ya == 'c':
        y = (h - ch) // 2
    return x, y, x + cw, y + ch


BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
TRANSPARENT = (0, 0, 0, 0)
SHADOW = (0, 0, 0, 150)

ROUNDRECT_ANTIALIASING_TARGET_RADIUS = 32

FONT_DIR = "data/utils/fonts/"
DEFAULT_FONT = "SourceHanSansCN-Regular"
DEFAULT_BOLD_FONT = "SourceHanSansCN-Bold"
DEFAULT_HEAVY_FONT = "SourceHanSansCN-Heavy"
DEFAULT_EMOJI_FONT = "EmojiOneColor-SVGinOT"

Color = Tuple[int, int, int, int]
Position = Tuple[int, int]
Size = Tuple[int, int]

def color_code_to_rgb(code: str) -> Color:
    if code.startswith("#"):
        code = code[1:]
    if len(code) == 3:
        return int(code[0], 16) * 16, int(code[1], 16) * 16, int(code[2], 16) * 16, 255
    elif len(code) == 6:
        return int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16), 255
    raise ValueError("Invalid color code")

def rgb_to_color_code(rgb: Color) -> str:
    r, g, b = rgb[:3]
    return f"#{r:02x}{g:02x}{b:02x}"

def lerp_color(c1, c2, t):
    ret = []
    for i in range(len(c1)):
        ret.append(max(0, min(255, int(c1[i] * (1 - t) + c2[i] * t))))
    return tuple(ret)

def adjust_color(c, r=None, g=None, b=None, a=None):
    c = list(c)
    if len(c) == 3: c.append(255)
    if r is not None: c[0] = r
    if g is not None: c[1] = g
    if b is not None: c[2] = b
    if a is not None: c[3] = a
    return tuple(c)

def get_font(path: str, size: int) -> Font:
    paths = [path]
    paths.append(os.path.join(FONT_DIR, path))
    paths.append(os.path.join(FONT_DIR, path + ".ttf"))
    paths.append(os.path.join(FONT_DIR, path + ".otf"))
    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise FileNotFoundError(f"Font file not found: {path}")

def get_text_size(font: Font, text: str) -> Size:
    if emoji.emoji_count(text) > 0:
        return getsize_emoji(text, font=font)
    else:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

def get_text_offset(font: Font, text: str) -> Position:
    bbox = font.getbbox(text)
    return bbox[0], bbox[1]

def resize_keep_ratio(img: Image.Image, max_size: Union[int, float], mode='long', scale=None) -> Image.Image:
    """
    Resize image to keep the aspect ratio, with a maximum size.  
    mode in ['long', 'short', 'w', 'h', 'wxh', 'scale']
    """
    w, h = img.size
    if mode == 'long':
        if w > h:
            ratio = max_size / w
        else:
            ratio = max_size / h
    elif mode == 'short':
        if w > h:
            ratio = max_size / h
        else:
            ratio = max_size / w
    elif mode == 'w':
        ratio = max_size / w
    elif mode == 'h':
        ratio = max_size / h
    elif mode == 'wxh':
        ratio = math.sqrt(max_size / (w * h))
    elif mode == 'scale':
        ratio = max_size
    else:
        raise ValueError(f"Invalid mode: {mode}")
    if scale:
        ratio *= scale
    return img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.BILINEAR)


class Gradient:
    def get_colors(self, size: Size) -> np.ndarray: 
        # [W, H, 4]
        raise NotImplementedError()

    def get_img(self, size: Size, mask: Image.Image=None) -> Image.Image:
        img = Image.fromarray(self.get_colors(size), 'RGBA')
        if mask:
            assert mask.size == size, "Mask size must match image size"
            if mask.mode == 'RGBA':
                mask = mask.split()[3]
            else:
                mask = mask.convert('L')
            img.putalpha(mask)
        return img

class LinearGradient(Gradient):
    def __init__(self, c1: Color, c2: Color, p1: Position, p2: Position):
        self.c1 = c1
        self.c2 = c2
        self.p1 = p1
        self.p2 = p2
        assert p1 != p2, "p1 and p2 cannot be the same point"

    def get_colors(self, size: Size) -> np.ndarray:
        w, h = size
        pixel_p1 = self.p1 * np.array([w, h])
        pixel_p2 = self.p2 * np.array([w, h])
        y_indices, x_indices = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
        coords = np.stack((x_indices, y_indices), axis=-1) # (H, W, 2)
        gradient_vector = pixel_p2 - pixel_p1
        length_sq = np.sum(gradient_vector**2)
        vector_p1_to_pixel = coords - pixel_p1 # (H, W, 2)
        dot_product = np.sum(vector_p1_to_pixel * gradient_vector, axis=-1) # (H, W)
        t = dot_product / length_sq
        t_clamped = np.clip(t, 0, 1) 
        colors = (1 - t_clamped[:, :, np.newaxis]) * self.c1 + t_clamped[:, :, np.newaxis] * self.c2
        colors = np.clip(colors, 0, 255).astype(np.uint8)
        return colors

class RadialGradient(Gradient):
    def __init__(self, c1: Color, c2: Color, center: Position, radius: float):
        self.c1 = c1
        self.c2 = c2
        self.center = center
        self.radius = radius

    def get_colors(self, size: Size) -> np.ndarray:
        w, h = size
        center = np.array(self.center) * np.array((w, h))
        y_indices, x_indices = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
        coords = np.stack((x_indices, y_indices), axis=-1)
        dist = np.linalg.norm(coords - center, axis=-1) / self.radius
        dist = np.clip(dist, 0, 1)
        colors = dist[:, :, np.newaxis] * np.array(self.c1) + (1 - dist)[:, :, np.newaxis] * np.array(self.c2)
        return colors.astype(np.uint8)
    
        

class Painter:
    def __init__(self, img: Image.Image):
        self.img = img
        self.offset = (0, 0)
        self.size = img.size
        self.w = img.size[0]
        self.h = img.size[1]
        self.region_stack = []

    def set_region(self, pos: Position, size: Size):
        assert isinstance(pos[0], int) and isinstance(pos[1], int), "Position must be integer"
        assert isinstance(size[0], int) and isinstance(size[1], int), "Size must be integer"
        self.region_stack.append((self.offset, self.size))
        self.offset = pos
        self.size = size
        self.w = size[0]
        self.h = size[1]
        if DEBUG_MODE:
            print(f"set region {pos} size={size}")
        return self

    def shrink_region(self, dlt: Position):
        pos = (self.offset[0] + dlt[0], self.offset[1] + dlt[1])
        size = (self.size[0] - dlt[0] * 2, self.size[1] - dlt[1] * 2)
        return self.set_region(pos, size)

    def expand_region(self, dlt: Position):
        pos = (self.offset[0] - dlt[0], self.offset[1] - dlt[1])
        size = (self.size[0] + dlt[0] * 2, self.size[1] + dlt[1] * 2)
        return self.set_region(pos, size)

    def move_region(self, dlt: Position, size: Size = None):
        offset = (self.offset[0] + dlt[0], self.offset[1] + dlt[1])
        size = size or self.size
        return self.set_region(offset, size)

    def restore_region(self, depth=1):
        if not self.region_stack:
            self.offset = (0, 0)
            self.size = self.img.size
            self.w = self.img.size[0]
            self.h = self.img.size[1]
        else:
            self.offset, self.size = self.region_stack.pop()
            self.w = self.size[0]
            self.h = self.size[1]
        if depth > 1:
            return self.restore_region(depth - 1)
        return self

    def get(self) -> Image.Image:
        return self.img

    def _text(
        self, 
        text: str, 
        pos: Position, 
        font: Font,
        fill: Color = BLACK,
        align: str = "left"
    ):
        std_size = get_text_size(font, "哇")
        has_emoji = emoji.emoji_count(text) > 0
        if not has_emoji:
            draw = ImageDraw.Draw(self.img)
            text_offset = (0, -std_size[1])
            pos = (pos[0] - text_offset[0] + self.offset[0], pos[1] - text_offset[1] + self.offset[1])
            draw.text(pos, text, font=font, fill=fill, align=align, anchor='ls')
        else:
            with Pilmoji(self.img, source=GoogleEmojiSource) as pilmoji:
                text_offset = (0, -std_size[1])
                pos = (pos[0] - text_offset[0] + self.offset[0], pos[1] - text_offset[1] + self.offset[1])
                pilmoji.text(pos, text, font=font, fill=fill, align=align, emoji_position_offset=(0, -std_size[1]), anchor='ls')
        return self
    
    def text(
        self, 
        text: str, 
        pos: Position, 
        font: Font,
        fill: Union[Color, LinearGradient] = BLACK,
        align: str = "left"
    ):
        if isinstance(fill, LinearGradient):
            gradient = fill
            fill = BLACK
        else:
            gradient = None

        if (len(fill) == 3 or fill[3] == 255) and not gradient:
            self._text(text, pos, font, fill, align)
        else:
            text_size = get_text_size(font, text)
            overlay_size = (text_size[0] + 1, text_size[1] + 1)
            overlay = Image.new('RGBA', overlay_size, (0, 0, 0, 0))
            p = Painter(overlay)
            p._text(text, (0, 0), font, fill=fill, align=align)
            if gradient:
                gradient_img = gradient.get_img(overlay_size, overlay)
                overlay = gradient_img
            elif fill[3] < 255:
                overlay_alpha = overlay.split()[3]
                overlay_alpha = Image.eval(overlay_alpha, lambda a: int(a * fill[3] / 255))
                overlay.putalpha(overlay_alpha)
            self.img.alpha_composite(overlay, (pos[0] + self.offset[0], pos[1] + self.offset[1]))
        return self
        
    def paste(
        self, 
        sub_img: Image.Image,
        pos: Position, 
        size: Size = None
    ) -> Image.Image:
        if size and size != sub_img.size:
            sub_img = sub_img.resize(size)
        if sub_img.mode == 'RGBA':
            self.img.paste(sub_img, (pos[0] + self.offset[0], pos[1] + self.offset[1]), sub_img)
        else:
            self.img.paste(sub_img, (pos[0] + self.offset[0], pos[1] + self.offset[1]))
        return self

    def paste_with_alphablend(
        self, 
        sub_img: Image.Image,
        pos: Position, 
        size: Size = None,
        alpha: float = None
    ) -> Image.Image:
        if size and size != sub_img.size:
            sub_img = sub_img.resize(size)
        pos = (pos[0] + self.offset[0], pos[1] + self.offset[1])
        overlay = Image.new('RGBA', sub_img.size, (0, 0, 0, 0))
        overlay.paste(sub_img, (0, 0))
        if alpha is not None:
            overlay_alpha = overlay.split()[3]
            overlay_alpha = Image.eval(overlay_alpha, lambda a: int(a * alpha))
            overlay.putalpha(overlay_alpha)
        self.img.alpha_composite(overlay, pos)
        return self

    def rect(
        self, 
        pos: Position, 
        size: Size, 
        fill: Union[Color, Gradient], 
        stroke: Color=None, 
        stroke_width: int=1,
    ):
        if isinstance(fill, Gradient):
            gradient = fill
            fill = BLACK
        else:
            gradient = None

        pos = (pos[0] + self.offset[0], pos[1] + self.offset[1])
        bbox = pos + (pos[0] + size[0], pos[1] + size[1])

        if fill[3] == 255 and not gradient:
            draw = ImageDraw.Draw(self.img)
            draw.rectangle(bbox, fill=fill, outline=stroke, width=stroke_width)
        else:
            overlay_size = (size[0] + 1, size[1] + 1)
            overlay = Image.new('RGBA', overlay_size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((0, 0, size[0], size[1]), fill=fill, outline=stroke, width=stroke_width)
            if gradient:
                gradient_img = gradient.get_img(overlay_size, overlay)
                overlay = gradient_img
            self.img.alpha_composite(overlay, (pos[0], pos[1]))

        return self
        
    def roundrect(
        self, 
        pos: Position, 
        size: Size, 
        fill: Union[Color, Gradient],
        radius: int, 
        stroke: Color=None, 
        stroke_width: int=1,
        corners = (True, True, True, True),
    ):
        if isinstance(fill, Gradient):
            gradient = fill
            fill = BLACK
        else:
            gradient = None

        pos = (pos[0] + self.offset[0], pos[1] + self.offset[1])

        aa_scale = max(radius, ROUNDRECT_ANTIALIASING_TARGET_RADIUS) / radius if radius > 0 else 1.0
        aa_size = (int(size[0] * aa_scale), int(size[1] * aa_scale))
        aa_radius = radius * aa_size[0] / size[0] if size[0] > 0 else radius

        overlay_size = (aa_size[0] + 1, aa_size[1] + 1)
        overlay = Image.new('RGBA', overlay_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle((0, 0, aa_size[0], aa_size[1]), fill=fill, radius=aa_radius, outline=stroke, width=stroke_width, corners=corners)
        if gradient:
            gradient_img = gradient.get_img(overlay_size, overlay)
            overlay = gradient_img

        overlay = overlay.resize((size[0] + 1, size[1] + 1), Image.Resampling.BICUBIC)
        self.img.alpha_composite(overlay, (pos[0], pos[1]))
        
        return self

    def pieslice(
        self,
        pos: Position,
        size: Size,
        start_angle: float,
        end_angle: float,
        fill: Color,
        stroke: Color=None,
        stroke_width: int=1,
    ):
        if isinstance(fill, Gradient):
            gradient = fill
            fill = BLACK
        else:
            gradient = None

        pos = (pos[0] + self.offset[0], pos[1] + self.offset[1])
        bbox = pos + (pos[0] + size[0], pos[1] + size[1])

        if fill[3] == 255 and not gradient:
            draw = ImageDraw.Draw(self.img)
            draw.pieslice(bbox, start_angle, end_angle, fill=fill, width=stroke_width, outline=stroke)
        else:
            overlay_size = (size[0] + 1, size[1] + 1)
            overlay = Image.new('RGBA', overlay_size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.pieslice((0, 0, size[0], size[1]), start_angle, end_angle, fill=fill, width=stroke_width, outline=stroke)
            if gradient:
                gradient_img = gradient.get_img(overlay_size, overlay)
                overlay = gradient_img
            self.img.alpha_composite(overlay, (pos[0], pos[1]))
        
        return self

# =========================== 布局类型 =========================== #

DEFAULT_PADDING = 0
DEFAULT_MARGIN = 0
DEFAULT_SEP = 8


class WidgetBg:
    def draw(self, p: Painter):
        raise NotImplementedError()

class FillBg(WidgetBg):
    def __init__(self, fill: Color, stroke: Color=None, stroke_width: int=1):
        self.fill = fill
        self.stroke = stroke
        self.stroke_width = stroke_width

    def draw(self, p: Painter):
        p.rect((0, 0), p.size, self.fill, self.stroke, self.stroke_width)

class RoundRectBg(WidgetBg):
    def __init__(self, fill: Color, radius: int, stroke: Color=None, stroke_width: int=1, corners = (True, True, True, True)):
        self.fill = fill
        self.radius = radius
        self.stroke = stroke
        self.stroke_width = stroke_width
        self.corners = corners
    
    def draw(self, p: Painter):
        p.roundrect((0, 0), p.size, self.fill, self.radius, self.stroke, self.stroke_width, self.corners)

class ImageBg(WidgetBg):
    def __init__(self, img: Union[str, Image.Image], align: str='c', mode='fit', blur=True, fade=0.1):
        if isinstance(img, str):
            self.img = Image.open(img)
        else:
            self.img = img
        assert align in ALIGN_MAP
        self.align = align
        assert mode in ('fit', 'fill', 'fixed', 'repeat')
        self.mode = mode
        if blur:
            self.img = self.img.filter(ImageFilter.GaussianBlur(radius=3))
        if fade > 0:
            self.img = ImageEnhance.Brightness(self.img).enhance(1 - fade)

    def draw(self, p: Painter):
        if self.mode == 'fit':
            ha, va = ALIGN_MAP[self.align]
            scale = max(p.w / self.img.size[0], p.h / self.img.size[1])
            w, h = int(self.img.size[0] * scale), int(self.img.size[1] * scale)
            if va == 'c':
                y = (p.h - h) // 2
            elif va == 't':
                y = 0
            else:
                y = p.h - h
            if ha == 'c':
                x = (p.w - w) // 2
            elif ha == 'l':
                x = 0
            else:
                x = p.w - w
            p.paste(self.img, (x, y), (w, h))
        if self.mode == 'fill':
            p.paste(self.img, (0, 0), p.size)
        if self.mode == 'fixed':
            ha, va = ALIGN_MAP[self.align]
            if va == 'c':
                y = (p.h - self.img.size[1]) // 2
            elif va == 't':
                y = 0
            else:
                y = p.h - self.img.size[1]
            if ha == 'c':
                x = (p.w - self.img.size[0]) // 2
            elif ha == 'l':
                x = 0
            else:
                x = p.w - self.img.size[0]
            p.paste(self.img, (x, y))
        if self.mode =='repeat':
            w, h = self.img.size
            for y in range(0, p.h, h):
                for x in range(0, p.w, w):
                    p.paste(self.img, (x, y))


class Widget:
    _thread_local = contextvars.ContextVar('local', default=None)

    def __init__(self):
        self.parent: Optional[Widget] = None

        self.content_halign = 'l'
        self.content_valign = 't'
        self.vmargin = DEFAULT_MARGIN
        self.hmargin = DEFAULT_MARGIN
        self.vpadding = DEFAULT_PADDING
        self.hpadding = DEFAULT_PADDING
        self.w = None
        self.h = None
        self.bg = None
        self.omit_parent_bg = False
        self.offset = (0, 0)
        self.offset_xanchor = 'l'
        self.offset_yanchor = 't'

        self._calc_w = None
        self._calc_h = None
        
        self.draw_funcs = []

        if Widget.get_current_widget():
            Widget.get_current_widget().add_item(self)

    def get_content_align(self) -> str:
        for k, v in ALIGN_MAP.items():
            if v == (self.content_halign, self.content_valign):
                return k
        return None

    @classmethod
    def get_current_widget_stack(cls) -> List[Widget]:
        local = cls._thread_local.get()
        if local is None: return None
        return local.wstack

    @classmethod
    def get_current_widget(cls) -> Optional[Widget]:
        stk = cls.get_current_widget_stack()
        if stk is None: return None
        return stk[-1]

    def __enter__(self):
        local = self._thread_local.get() 
        if local is None:
            local = threading.local()
            local.wstack = []
        local.wstack.append(self)
        self._thread_local.set(local)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        local = self._thread_local.get()
        assert local is not None and local.wstack[-1] == self
        local.wstack.pop()
        if not local.wstack:
            self._thread_local.set(None)

    def add_item(self, item: Widget):
        raise NotImplementedError()

    def set_parent(self, parent: Widget):
        self.parent = parent
        return self

    def set_content_align(self, align: str):
        if align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.content_halign, self.content_valign = ALIGN_MAP[align]
        return self

    def set_margin(self, margin: Union[int, Tuple[int, int]]):
        if isinstance(margin, int):
            self.vmargin = margin
            self.hmargin = margin
        else:
            self.hmargin = margin[0]
            self.vmargin = margin[1]
        return self

    def set_padding(self, padding: Union[int, Tuple[int, int]]):
        if isinstance(padding, int):
            self.vpadding = padding
            self.hpadding = padding
        else:
            self.hpadding = padding[0]
            self.vpadding = padding[1]
        return self

    def set_size(self, size: Tuple[int, int]):
        if not size: size = (None, None)
        self.w = size[0]
        self.h = size[1]
        return self

    def set_w(self, w: int):
        self.w = w
        return self
    
    def set_h(self, h: int):
        self.h = h
        return self

    def set_offset(self, offset: Tuple[int, int]):
        self.offset = offset
        return self
    
    def set_offset_anchor(self, anchor: str):
        if anchor not in ALIGN_MAP:
            raise ValueError('Invalid anchor')
        self.offset_xanchor, self.offset_yanchor = ALIGN_MAP[anchor]
        return self

    def set_bg(self, bg: WidgetBg):
        self.bg = bg
        return self

    def set_omit_parent_bg(self, omit: bool):
        self.omit_parent_bg = omit
        return self

    def _get_content_size(self):
        return (0, 0)
    
    def _get_self_size(self):
        if not all([self._calc_w, self._calc_h]):
            content_w, content_h = self._get_content_size()
            content_w_limit = self.w - self.hpadding * 2 if self.w is not None else content_w
            content_h_limit = self.h - self.vpadding * 2 if self.h is not None else content_h
            if content_w > content_w_limit or content_h > content_h_limit:
                raise ValueError(f'Content size is too large with ({content_w}, {content_h}) > ({content_w_limit}, {content_h_limit})')
            self._calc_w = content_w_limit + self.hmargin * 2 + self.hpadding * 2
            self._calc_h = content_h_limit + self.vmargin * 2 + self.vpadding * 2
        return (int(self._calc_w), int(self._calc_h))

    def _get_content_pos(self):
        w, h = self._get_self_size()
        w -= self.hpadding * 2 + self.hmargin * 2
        h -= self.vpadding * 2 + self.vmargin * 2
        cw, ch = self._get_content_size()
        if self.content_halign == 'l':
            cx = 0
        elif self.content_halign == 'r':
            cx = w - cw
        elif self.content_halign == 'c':
            cx = (w - cw) // 2
        if self.content_valign == 't':
            cy = 0
        elif self.content_valign == 'b':
            cy = h - ch
        elif self.content_valign == 'c':
            cy = (h - ch) // 2
        return (cx, cy)
        
    def _draw_self(self, p: Painter):
        if DEBUG_MODE:
            import random
            color = (random.randint(0, 200), random.randint(0, 200), random.randint(0, 200), 255)
            p.rect((0, 0), (p.w, p.h), TRANSPARENT, stroke=color, stroke_width=2)
            font = get_font(DEFAULT_FONT, 16)
            s = f"{self.__class__.__name__}({p.w},{p.h})"
            s += f"self={self._get_self_size()}"
            s += f"content={self._get_content_size()}"
            p.text(s, (3, 3), font=font, fill=color)
            print(f"Draw {self.__class__.__name__} at {p.offset} size={p.size}")
        
        if self.bg:
            self.bg.draw(p)

        for draw_func in self.draw_funcs:
            draw_func(self, p)
    
    def _draw_content(self, p: Painter):
        pass

    def add_draw_func(self, func):
        self.draw_funcs.append(func)
        return self
    
    def clear_draw_funcs(self):
        self.draw_funcs.clear()
        return self
    
    def draw(self, p: Painter):
        assert p.size == self._get_self_size()

        if self.offset_xanchor == 'l': 
            offset_x = self.offset[0]
        elif self.offset_xanchor == 'r':
            offset_x = self.offset[0] - p.w
        else:
            offset_x = self.offset[0] - p.w // 2
        if self.offset_yanchor == 't':
            offset_y = self.offset[1]
        elif self.offset_yanchor == 'b':
            offset_y = self.offset[1] - p.h
        else:
            offset_y = self.offset[1] - p.h // 2

        p.move_region((offset_x, offset_y))
        p.shrink_region((self.hmargin, self.vmargin))
        self._draw_self(p)

        p.shrink_region((self.hpadding, self.vpadding))
        cx, cy = self._get_content_pos()
        p.move_region((cx, cy)) 
        self._draw_content(p)

        p.restore_region(4)
  
        

class Frame(Widget):
    def __init__(self, items: List[Widget]=None):
        super().__init__()
        self.items = items or []
        for item in self.items:
            item.set_parent(self)
    
    def add_item(self, item: Widget):
        item.set_parent(self)
        self.items.append(item)
        return self
    
    def set_items(self, items: List[Widget]):
        for item in self.items:
            item.set_parent(None)
        self.items = items
        for item in self.items:
            item.set_parent(self)
        return self

    def _get_content_size(self):
        size = (0, 0)
        for item in self.items:
            w, h = item._get_self_size()
            size = (max(size[0], w), max(size[1], h))
        return size
    
    def _draw_content(self, p: Painter):
        cw, ch = self._get_content_size()
        for item in self.items:
            w, h = item._get_self_size()
            x, y = 0, 0
            if self.content_halign == 'l':
                x = 0
            elif self.content_halign == 'r':
                x = cw - w
            elif self.content_halign == 'c':
                x = (cw - w) // 2
            if self.content_valign == 't':
                y = 0
            elif self.content_valign == 'b':
                y = ch - h
            elif self.content_valign == 'c':
                y = (ch - h) // 2
            p.move_region((x, y), (w, h))
            item.draw(p)
            p.restore_region()
    

class HSplit(Widget):
    def __init__(self, items: List[Widget]=None, ratios: List[float]=None, sep=DEFAULT_SEP, item_size_mode='fixed', item_align='c'):
        super().__init__()
        self.items = items or []
        for item in self.items:
            item.set_parent(self)
        self.ratios = ratios 
        self.sep = sep
        assert item_size_mode in ('expand', 'fixed')
        self.item_size_mode = item_size_mode
        if item_align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[item_align]
        self.item_bg = None

    def set_items(self, items: List[Widget]):
        for item in self.items:
            item.set_parent(None)
        self.items = items
        for item in self.items:
            item.set_parent(self)
        return self
    
    def add_item(self, item: Widget):
        item.set_parent(self)
        self.items.append(item)
        return self

    def set_item_align(self, align: str):
        if align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[align]
        return self

    def set_sep(self, sep: int):
        self.sep = sep  
        return self

    def set_ratios(self, ratios: List[float]):
        self.ratios = ratios
        return self

    def set_item_size_mode(self, mode: str):
        assert mode in ('expand', 'fixed')
        self.item_size_mode = mode
        return self

    def set_item_bg(self, bg: WidgetBg):
        self.item_bg = bg
        return self

    def _get_item_sizes(self):
        ratios = self.ratios if self.ratios else [item._get_self_size()[0] for item in self.items]
        if self.item_size_mode == 'expand':
            assert self.w is not None, 'Expand mode requires width'
            ratio_sum = sum(ratios)
            unit_w = (self.w - self.sep * (len(ratios) - 1) - self.hpadding * 2) / ratio_sum
        else:
            unit_w = 0
            for r, item in zip(ratios, self.items):
                iw, ih = item._get_self_size()
                if r > 0: unit_w = max(unit_w, iw / r)
        ret = []
        h = max([item._get_self_size()[1] for item in self.items])
        for r, item in zip(ratios, self.items):
            ret.append((int(unit_w * r), h))
        return ret

    def _get_content_size(self):
        if not self.items:
            return (0, 0)
        sizes = self._get_item_sizes()
        return (sum(s[0] for s in sizes) + self.sep * (len(sizes) - 1), max(s[1] for s in sizes))
    
    def _draw_content(self, p: Painter):
        if not self.items:
            return
        sizes = self._get_item_sizes()
        cur_x = 0
        for item, (w, h) in zip(self.items, sizes):
            iw, ih = item._get_self_size()
            p.move_region((cur_x, 0), (w, h))
            x, y = 0, 0
            if self.item_bg and not item.omit_parent_bg:
                self.item_bg.draw(p)
            if self.item_halign == 'l':
                x += 0
            elif self.item_halign == 'r':
                x += w - iw
            elif self.item_halign == 'c':
                x += (w - iw) // 2
            if self.item_valign == 't':
                y += 0
            elif self.item_valign == 'b':
                y += h - ih
            elif self.item_valign == 'c':
                y += (h - ih) // 2
            p.move_region((x, y), (iw, ih))
            item.draw(p)
            p.restore_region(2)
            cur_x += w + self.sep


class VSplit(Widget):
    def __init__(self, items: List[Widget]=None, ratios: List[float]=None, sep=DEFAULT_SEP, item_size_mode='fixed', item_align='c'):
        super().__init__()
        self.items = items or []
        for item in self.items:
            item.set_parent(self)
        self.ratios = ratios 
        self.sep = sep
        assert item_size_mode in ('expand', 'fixed')
        self.item_size_mode = item_size_mode
        if item_align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[item_align]
        self.item_bg = None

    def set_items(self, items: List[Widget]):
        for item in self.items:
            item.set_parent(None)
        self.items = items
        for item in self.items:
            item.set_parent(self)
        return self
        
    def add_item(self, item: Widget):
        item.set_parent(self)
        self.items.append(item)
        return self

    def set_item_align(self, align: str):
        if align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[align]
        return self
    
    def set_sep(self, sep: int):
        self.sep = sep  
        return self

    def set_ratios(self, ratios: List[float]):
        self.ratios = ratios
        return self

    def set_item_size_mode(self, mode: str):
        assert mode in ('expand', 'fixed')
        self.item_size_mode = mode
        return self

    def set_item_bg(self, bg: WidgetBg):
        self.item_bg = bg
        return self

    def _get_item_sizes(self):
        ratios = self.ratios if self.ratios else [item._get_self_size()[1] for item in self.items]
        if self.item_size_mode == 'expand':
            assert self.h is not None, 'Expand mode requires height'
            ratio_sum = sum(ratios)
            unit_h = (self.h - self.sep * (len(ratios) - 1) - self.vpadding * 2) / ratio_sum
        else:
            unit_h = 0
            for r, item in zip(ratios, self.items):
                iw, ih = item._get_self_size()
                if r > 0: unit_h = max(unit_h, ih / r)
        ret = []
        w = max([item._get_self_size()[0] for item in self.items])
        for r, item in zip(ratios, self.items):
            ret.append((w, int(unit_h * r)))
        return ret
    
    def _get_content_size(self):
        if not self.items:
            return (0, 0)
        sizes = self._get_item_sizes()
        return (max(s[0] for s in sizes), sum(s[1] for s in sizes) + self.sep * (len(sizes) - 1))
    
    def _draw_content(self, p: Painter):
        if not self.items:
            return
        sizes = self._get_item_sizes()
        cur_y = 0
        for item, (w, h) in zip(self.items, sizes):
            iw, ih = item._get_self_size()
            p.move_region((0, cur_y), (w, h))
            if self.item_bg and not item.omit_parent_bg:
                self.item_bg.draw(p)
            x, y = 0, 0
            if self.item_halign == 'l':
                x += 0
            elif self.item_halign == 'r':
                x += w - iw
            elif self.item_halign == 'c':
                x += (w - iw) // 2
            if self.item_valign == 't':
                y += 0
            elif self.item_valign == 'b':
                y += h - ih
            elif self.item_valign == 'c':
                y += (h - ih) // 2
            p.move_region((x, y), (iw, ih))
            item.draw(p)
            p.restore_region(2)
            cur_y += h + self.sep
    

class Grid(Widget):
    def __init__(self, items: List[Widget]=None, row_count=None, col_count=None, item_size_mode='fixed', item_align='c', hsep=DEFAULT_SEP, vsep=DEFAULT_SEP, vertical=False):
        super().__init__()
        self.items = items or []
        for item in self.items:
            item.set_parent(self)
        self.row_count = row_count
        self.col_count = col_count
        assert not (self.row_count and self.col_count), 'Either row_count or col_count should be None'
        assert item_size_mode in ('expand', 'fixed')
        self.item_size_mode = item_size_mode
        self.hsep = hsep
        self.vsep = vsep
        if item_align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[item_align]
        self.item_bg = None
        self.vertical = vertical

    def set_vertical(self, vertical: bool):
        self.vertical = vertical
        return self

    def set_items(self, items: List[Widget]):
        for item in self.items:
            item.set_parent(None)
        self.items = items
        for item in self.items:
            item.set_parent(self)
        return self
        
    def add_item(self, item: Widget):
        item.set_parent(self)
        self.items.append(item)
        return self
    
    def set_item_align(self, align: str):
        if align not in ALIGN_MAP:
            raise ValueError('Invalid align')
        self.item_halign, self.item_valign = ALIGN_MAP[align]
        return self

    def set_sep(self, hsep=None, vsep=None):
        if hsep is not None:
            self.hsep = hsep
        if vsep is not None:
            self.vsep = vsep
        return self

    def set_row_count(self, count: int):
        self.row_count = count
        self.col_count = None
        return self

    def set_col_count(self, count: int):
        self.col_count = count
        self.row_count = None
        return self

    def set_item_size_mode(self, mode: str):
        assert mode in ('expand', 'fixed')
        self.item_size_mode = mode
        return self

    def set_item_bg(self, bg: WidgetBg):
        self.item_bg = bg
        return self

    def _get_grid_rc_and_size(self):
        r, c = self.row_count, self.col_count
        assert r and not c or c and not r, 'Either row_count or col_count should be None'
        if not r: r = (len(self.items) + c - 1) // c
        if not c: c = (len(self.items) + r - 1) // r
        if self.item_size_mode == 'expand':
            assert self.w is not None and self.h is not None, 'Expand mode requires width and height'
            gw = (self.w - self.hsep * (c - 1) - self.hpadding * 2) / c
            gh = (self.h - self.vsep * (r - 1) - self.vpadding * 2) / r
        else:
            gw, gh = 0, 0
            for item in self.items:
                iw, ih = item._get_self_size()
                gw = max(gw, iw)
                gh = max(gh, ih)
        return (int(r), int(c)), (int(gw), int(gh))
    
    def _get_content_size(self):
        (r, c), (gw, gh) = self._get_grid_rc_and_size()
        return (int(c * gw + self.hsep * (c - 1)), int(r * gh + self.vsep * (r - 1)))
    
    def _draw_content(self, p: Painter):
        (r, c), (gw, gh) = self._get_grid_rc_and_size()
        for idx, item in enumerate(self.items):
            if not self.vertical:
                i, j = idx // c, idx % c
            else:
                i, j = idx % r, idx // r
            x = j * (gw + self.hsep)
            y = i * (gh + self.vsep)
            p.move_region((x, y), (gw, gh))
            if self.item_bg and not item.omit_parent_bg:
                self.item_bg.draw(p)
            x, y = 0, 0
            iw, ih = item._get_self_size()
            if self.item_halign == 'l':
                x += 0
            elif self.item_halign == 'r':
                x += gw - iw
            elif self.item_halign == 'c':
                x += (gw - iw) // 2
            if self.item_valign == 't':
                y += 0
            elif self.item_valign == 'b':
                y += gh - ih
            elif self.item_valign == 'c':
                y += (gh - ih) // 2
            p.move_region((x, y), (iw, ih))
            item.draw(p)
            p.restore_region(2)


@dataclass
class TextStyle:
    font: str = DEFAULT_FONT
    size: int = 16
    color: Tuple[int, int, int, int] = BLACK


class TextBox(Widget):
    def __init__(self, text: str = '', style: TextStyle = None, line_count=None, line_sep=2, wrap=True, overflow='shrink', use_real_line_count=False):
        """
        overflow: 'shrink', 'clip'
        """
        super().__init__()
        self.text = str(text)
        self.style = style or TextStyle()
        self.line_count = line_count
        self.line_sep = line_sep
        self.wrap = wrap
        assert overflow in ('shrink', 'clip')
        self.overflow = overflow
        self.use_real_line_count = use_real_line_count

        if line_count is None:
            self.line_count = 99999 if use_real_line_count else 1

        self.set_padding(2)
        self.set_margin(0)

    def set_text(self, text: str):
        self.text = text
        return self

    def set_style(self, style: TextStyle):
        self.style = style
        return self
   
    def set_line_count(self, count: int):
        self.line_count = count
        return self
    
    def set_line_sep(self, sep: int):
        self.line_sep = sep
        return self

    def set_wrap(self, wrap: bool):
        self.wrap = wrap
        return self

    def set_overflow(self, overflow: str):
        assert overflow in ('shrink', 'clip')
        self.overflow = overflow

    def _get_pil_font(self):
        return get_font(self.style.font, self.style.size)

    def _get_clip_text_to_width_idx(self, text: str, width: int, suffix=''):
        font = self._get_pil_font()
        w, _ = get_text_size(font, text + suffix)
        if w <= width:
            return None
        l, r = 0, len(text)
        while l <= r:
            m = (l + r) // 2
            w, _ = get_text_size(font, text[:m] + suffix)
            if   w < width: l = m + 1
            elif w > width: r = m - 1
            else: return m
        return r

    def _get_lines(self):
        lines = self.text.split('\n')  
        clipped_lines = []
        for line in lines:
            if self.w:
                w = self.w - self.hpadding * 2
                suffix = '...' if self.overflow == 'shrink' else ''
                if self.wrap:
                    while True:
                        line_suffix = suffix if len(clipped_lines) == self.line_count - 1 else ''
                        clip_idx = self._get_clip_text_to_width_idx(line, w, line_suffix)
                        if clip_idx is None:
                            clipped_lines.append(line)
                            break
                        clipped_lines.append(line[:clip_idx] + line_suffix)
                        line = line[clip_idx:]
                        if len(clipped_lines) == self.line_count:
                            break
                else:
                    clip_idx = self._get_clip_text_to_width_idx(line, w, suffix)
                    if clip_idx is not None:
                        line = line[:clip_idx] + suffix
                    clipped_lines.append(line)
            else:
                clipped_lines.append(line)
        return clipped_lines[:self.line_count]

    def _get_content_size(self):
        lines = self._get_lines()
        w, h = 0, 0
        font = self._get_pil_font()
        for line in lines:
            lw, _ = get_text_size(font, line)
            w = max(w, lw)
        line_count = len(lines) if self.use_real_line_count else self.line_count
        h = line_count * (self.style.size + self.line_sep) - self.line_sep
        if self.w:
            w = self.w - self.hpadding * 2
        if self.h:
            h = self.h - self.vpadding * 2
        return (w, h)
        
    def _draw_content(self, p: Painter):
        font = self._get_pil_font()
        lines = self._get_lines()
        text_h = (self.style.size + self.line_sep) * len(lines) - self.line_sep
        if self.content_valign == 't':
            start_y = 0
        elif self.content_valign == 'b':
            start_y = p.h - text_h
        elif self.content_valign == 'c':
            start_y = (p.h - text_h) // 2

        for i, line in enumerate(lines):
            lw, _ = get_text_size(font, line)
            x, y = 0, start_y + i * (self.style.size + self.line_sep)
            if self.content_halign == 'l':
                x += 0
            elif self.content_halign == 'r':
                x += p.w - lw
            elif self.content_halign == 'c':
                x += (p.w - lw) // 2
            p.move_region((x, y), (lw, self.style.size))
            p.text(line, (0, 0), font=font, fill=self.style.color)
            p.restore_region()
    

class ImageBox(Widget):
    def __init__(self, image: Union[str, Image.Image], image_size_mode=None, size=None, use_alphablend=False, alpha_adjust=1.0):
        """
        image_size_mode: 'fit', 'fill', 'original'
        """
        super().__init__()
        if isinstance(image, str):
            self.image = Image.open(image)
        else:
            self.image = image

        if size:
            self.set_size(size)

        if image_size_mode is None:
            if size and (size[0] or size[1]):
                self.set_image_size_mode('fit')
            else:
                self.set_image_size_mode('original')
        else:
            self.set_image_size_mode(image_size_mode)
        
        self.set_margin(0)
        self.set_padding(0)

        self.set_use_alphablend(use_alphablend)
        self.set_alpha_adjust(alpha_adjust)

    def set_alpha_adjust(self, alpha_adjust: float):
        self.alpha_adjust = alpha_adjust
        return self

    def set_use_alphablend(self, use_alphablend):
        self.use_alphablend = use_alphablend
        return self

    def set_image(self, image: Union[str, Image.Image]):
        if isinstance(image, str):
            self.image = Image.open(image)
        else:
            self.image = image
        return self

    def set_image_size_mode(self, mode: str):
        assert mode in ('fit', 'fill', 'original')
        self.image_size_mode = mode
        return self

    def _get_content_size(self):
        w, h = self.image.size
        if self.image_size_mode == 'original':
            return (w, h)
        elif self.image_size_mode == 'fit':
            assert self.w is not None or self.h is not None, 'Fit mode requires width or height'
            tw = self.w - self.hpadding * 2 if self.w else 1000000
            th = self.h - self.vpadding * 2 if self.h else 1000000
            scale = min(tw / w, th / h)
            return (int(w * scale), int(h * scale))
        elif self.image_size_mode == 'fill':
            assert self.w is not None or self.h is not None, 'Fill mode requires width or height'
            if self.w and self.h:
                return (int(self.w - self.hpadding * 2), int(self.h - self.vpadding * 2))
            else:
                tw = self.w - self.hpadding * 2 if self.w else 1000000
                th = self.h - self.vpadding * 2 if self.h else 1000000
                scale = max(tw / w, th / h)
                return (int(w * scale), int(h * scale))
    
    def _draw_content(self, p: Painter):
        w, h = self._get_content_size()
        if self.use_alphablend:
            p.paste_with_alphablend(self.image, (0, 0), (w, h), self.alpha_adjust)
        else:
            p.paste(self.image, (0, 0), (w, h))


class Spacer(Widget):
    def __init__(self, w: int = 1, h: int = 1):
        super().__init__()
        self.set_size((w, h))
    
    def _get_content_size(self):
        return (self.w - 2 * self.hpadding, self.h - 2 * self.vpadding)

    def _draw_content(self, p: Painter):
        pass


class Canvas(Frame):
    def __init__(self, w=None, h=None, bg: WidgetBg=None):
        super().__init__()
        self.set_size((w, h))
        self.set_bg(bg)
        self.set_margin(0)

    def get_img(self, scale: float = None) -> Image.Image:
        size = self._get_self_size()
        assert size[0] * size[1] < 4096 * 4096, f'Canvas size is too large ({size[0]} x {size[1]})'
        img = Image.new('RGBA', size, TRANSPARENT)
        p = Painter(img)
        self.draw(p)
        img = p.get()
        if scale:
            img = img.resize((int(size[0] * scale), int(size[1] * scale)), Image.Resampling.BILINEAR)
        return img


# =========================== 控件函数 =========================== #

# 由带颜色代码的字符串获取彩色文本组件
def colored_text_box(s: str, style: TextStyle, padding=2, use_shadow=False, shadow_color=SHADOW, **text_box_kargs) -> HSplit:
    try:
        segs = [{ 'text': None, 'color': None }]
        while True:
            i = s.find('<#')
            if i == -1:
                segs[-1]['text'] = s
                break
            j = s.find('>', i)
            segs[-1]['text'] = s[:i]
            code = s[i+2:j]
            if len(code) == 6:
                r, g, b = int(code[:2], 16), int(code[2:4], 16), int(code[4:], 16)
            elif len(code) == 3:
                r, g, b = int(code[0], 16)*17, int(code[1], 16)*17, int(code[2], 16)*17
            else:
                raise ValueError(f"颜色代码格式错误: {code}")
            segs.append({ 'text': None, 'color': (r, g, b) })
            s = s[j+1:]
    except Exception as e:
        segs = [{ 'text': s, 'color': None }]

    with HSplit().set_padding(padding).set_sep(0) as hs:
        for seg in segs:
            text, color = seg['text'], seg['color']
            if text:
                if not use_shadow:
                    color_style = deepcopy(style)
                    if color is not None: color_style.color = color
                    TextBox(text, style=color_style, **text_box_kargs).set_padding(0)
                else:
                    font = style.font
                    font_size = style.size
                    c1 = color if color else style.color
                    c2 = shadow_color
                    draw_shadowed_text(
                        text, font, font_size, c1, c2,
                        content_align='l', padding=0,
                        **text_box_kargs
                    )
    return hs

# 绘制带阴影的文本
def draw_shadowed_text(
    text: str, 
    font: str,
    font_size: int, 
    c1: Color, 
    c2: Color = SHADOW,
    offset: Union[int, Tuple[int, int]] = 2, 
    w: int = None, 
    h: int = None,
    content_align: str = 'c',
    padding: int = 2,
    **textbox_kargs,
) -> Frame:
    if isinstance(offset, int):
        offset = (offset, offset)
    with Frame().set_size((w, h)).set_content_align(content_align) as frame:
        if c2:
            TextBox(text, TextStyle(font=font, size=font_size, color=c2), **textbox_kargs).set_offset(offset).set_padding(padding)
        TextBox(text, TextStyle(font=font, size=font_size, color=c1), **textbox_kargs).set_padding(padding)
    return frame