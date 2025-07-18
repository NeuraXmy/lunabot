# This code adapted from https://github.com/python-pillow/Pillow/issues/4644 to resolve an issue
# described in https://github.com/python-pillow/Pillow/issues/4640
#
# There is a long-standing issue with the Pillow library that messes up GIF transparency by replacing the
# transparent pixels with black pixels (among other issues) when the GIF is saved using PIL.Image.save().
# This code works around the issue and allows us to properly generate transparent GIFs.

from typing import Tuple, List, Union
from collections import defaultdict
from random import randrange
from itertools import chain
from PIL import Image, ImageSequence
import numpy as np

QUANTIZE_METHOD = Image.Quantize.MAXCOVERAGE
DITHER = 0

class TransparentAnimatedGifConverter(object):
    _PALETTE_SLOTSET = set(range(256))

    def __init__(self, img_rgba: Image, alpha_threshold: int = 0):
        self._img_rgba = img_rgba
        self._alpha_threshold = alpha_threshold

    def _process_pixels(self):
        """Set the transparent pixels to the color 0."""
        self._transparent_pixels = set(
            idx for idx, alpha in enumerate(
                self._img_rgba.getchannel(channel='A').getdata())
            if alpha <= self._alpha_threshold)

    def _set_parsed_palette(self):
        """Parse the RGB palette color `tuple`s from the palette."""
        palette = self._img_p.getpalette()
        self._img_p_used_palette_idxs = set(
            idx for pal_idx, idx in enumerate(self._img_p_data)
            if pal_idx not in self._transparent_pixels)
        self._img_p_parsedpalette = dict(
            (idx, tuple(palette[idx * 3:idx * 3 + 3]))
            for idx in self._img_p_used_palette_idxs)

    def _get_similar_color_idx(self):
        """Return a palette index with the closest similar color."""
        old_color = self._img_p_parsedpalette[0]
        dict_distance = defaultdict(list)
        for idx in range(1, 256):
            color_item = self._img_p_parsedpalette[idx]
            if color_item == old_color:
                return idx
            distance = sum((
                abs(old_color[0] - color_item[0]),  # Red
                abs(old_color[1] - color_item[1]),  # Green
                abs(old_color[2] - color_item[2])))  # Blue
            dict_distance[distance].append(idx)
        return dict_distance[sorted(dict_distance)[0]][0]

    def _remap_palette_idx_zero(self):
        """Since the first color is used in the palette, remap it."""
        free_slots = self._PALETTE_SLOTSET - self._img_p_used_palette_idxs
        new_idx = free_slots.pop() if free_slots else \
            self._get_similar_color_idx()
        self._img_p_used_palette_idxs.add(new_idx)
        self._palette_replaces['idx_from'].append(0)
        self._palette_replaces['idx_to'].append(new_idx)
        self._img_p_parsedpalette[new_idx] = self._img_p_parsedpalette[0]
        del(self._img_p_parsedpalette[0])

    def _get_unused_color(self) -> tuple:
        """ Return a color for the palette that does not collide with any other already in the palette."""
        used_colors = set(self._img_p_parsedpalette.values())
        while True:
            new_color = (randrange(256), randrange(256), randrange(256))
            if new_color not in used_colors:
                return new_color

    def _process_palette(self):
        """Adjust palette to have the zeroth color set as transparent. Basically, get another palette
        index for the zeroth color."""
        self._set_parsed_palette()
        if 0 in self._img_p_used_palette_idxs:
            self._remap_palette_idx_zero()
        self._img_p_parsedpalette[0] = self._get_unused_color()

    def _adjust_pixels(self):
        """Convert the pixels into their new values."""
        if self._palette_replaces['idx_from']:
            trans_table = bytearray.maketrans(
                bytes(self._palette_replaces['idx_from']),
                bytes(self._palette_replaces['idx_to']))
            self._img_p_data = self._img_p_data.translate(trans_table)
        for idx_pixel in self._transparent_pixels:
            self._img_p_data[idx_pixel] = 0
        self._img_p.frombytes(data=bytes(self._img_p_data))

    def _adjust_palette(self):
        """Modify the palette in the new `Image`."""
        unused_color = self._get_unused_color()
        final_palette = chain.from_iterable(
            self._img_p_parsedpalette.get(x, unused_color) for x in range(256))
        self._img_p.putpalette(data=final_palette)

    def process(self) -> Image:
        """Return the processed mode `P` `Image`."""
        rgb_img = self._img_rgba.convert(mode='RGB')
        pal_img = rgb_img.quantize(256)
        self._img_p = rgb_img.quantize(palette=pal_img, method=QUANTIZE_METHOD, dither=DITHER)
        self._img_p_data = bytearray(self._img_p.tobytes())
        self._palette_replaces = dict(idx_from=list(), idx_to=list())
        self._process_pixels()
        self._process_palette()
        self._adjust_pixels()
        self._adjust_palette()
        self._img_p.info['transparency'] = 0
        self._img_p.info['background'] = 0
        return self._img_p

def _create_animated_gif(images: List[Image.Image], durations: Union[int, List[int]], alpha_threshold: int = 0) -> Tuple[Image.Image, dict]:
    """If the image is a GIF, create an its thumbnail here."""
    save_kwargs = dict()
    new_images: List[Image.Image] = []

    for frame in images:
        thumbnail = frame.copy()  # type: Image
        thumbnail_rgba = thumbnail.convert(mode='RGBA')
        thumbnail_rgba.thumbnail(size=frame.size, reducing_gap=3.0)
        converter = TransparentAnimatedGifConverter(img_rgba=thumbnail_rgba, alpha_threshold=alpha_threshold)
        thumbnail_p = converter.process()  # type: Image
        new_images.append(thumbnail_p)

    output_image = new_images[0]
    save_kwargs.update(
        format='GIF',
        save_all=True,
        optimize=False,
        append_images=new_images[1:],
        duration=durations,
        disposal=2,  # Other disposals don't work
        loop=0)
    return output_image, save_kwargs

def _save_transparent_gif(images: List[Image.Image], durations: Union[int, List[int]], save_file, alpha_threshold: int = 0):
    """Creates a transparent GIF, adjusting to avoid transparency issues that are present in the PIL library

    Note that this does NOT work for partial alpha. The partial alpha gets discarded and replaced by solid colors.

    Parameters:
        images: a list of PIL Image objects that compose the GIF frames
        durations: an int or List[int] that describes the animation durations for the frames of this GIF
        save_file: A filename (string), pathlib.Path object or file object. (This parameter corresponds
                   and is passed to the PIL.Image.save() method.)
    Returns:
        Image - The PIL Image object (after first saving the image to the specified target)
    """
    root_frame, save_args = _create_animated_gif(images, durations, alpha_threshold)
    root_frame.save(save_file, **save_args)

# 从GIF获取帧间隔
def get_gif_duration(img: Image.Image):
    return img.info.get('duration', 50)

# 从GIF获取帧序列
def get_frames_from_gif(img: Image.Image):
    return [frame.copy() for frame in ImageSequence.Iterator(img)]

# 从帧序列保存透明GIF
def save_transparent_gif(frames: Union[Image.Image, List[Image.Image]], duration: int, save_path: str, alpha_threshold: float = 0.5):
    alpha_threshold = max(0.0, min(1.0, alpha_threshold))
    alpha_threshold = int(alpha_threshold * 255)
    if isinstance(frames, Image.Image):
        frames = [frames]
    _save_transparent_gif(frames, duration, save_path, alpha_threshold)

# 保存高质量静态GIF
def save_high_quality_static_gif(img: Image, save_path: str, alpha_threshold: float=0.5):
    import random
    import os
    from PIL.Image import Palette
    alpha_threshold = int(alpha_threshold * 255)
    def color_distance(c1, c2):
        return sum((a - b) ** 2 for a, b in zip(c1, c2))
    img = img.convert("RGBA")
    original_img = img
    retry_num = 0
    while True:    
        if retry_num > 20:
            raise Exception("生成透明GIF失败")
        img = original_img.copy()
        transparent_color = (
            random.randint(0, 255), 
            random.randint(0, 255), 
            random.randint(0, 255)
        )
        def check_color_exists(pixel):
            return color_distance(pixel[:3], transparent_color) < 300
        if any(map(check_color_exists, img.getdata())):
            retry_num += 1
            continue
        def replace_alpha(pixel):
            return (*transparent_color, 255) if pixel[3] < alpha_threshold else pixel
        trans_data = list(map(replace_alpha, img.getdata()))
        img.putdata(trans_data)
        img: Image = img.convert("RGB")
        pal_img = img.quantize(256)
        img = img.quantize(palette=pal_img, method=QUANTIZE_METHOD, dither=DITHER)
        palette = img.getpalette()[:768]
        transparent_color_index, min_dist = None, float("inf")
        for i in range(256):
            color = palette[i*3:i*3+3]
            dist = color_distance(color, transparent_color)
            if dist < min_dist:
                transparent_color_index, min_dist = i, dist
        if transparent_color_index is None:
            raise Exception("The specific color was not found in the palette.")
        save_path = os.path.abspath(save_path)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img.save(save_path, save_all=True, append_images=[img], duration=100, loop=0, transparency=transparent_color_index)
        break

# 从帧序列保存APNG
def save_apng(images: List[Image.Image], save_path: str, duration=50, loop=0):
    """
    将RGBA图像列表保存为APNG文件
    Args:
        images: PIL Image对象列表
        output_path: 输出文件路径
        duration: 每帧持续时间（毫秒）
        loop: 循环次数（0表示无限循环）
    """
    if not images:
        raise ValueError("图像列表不能为空")
    rgba_images = []
    for img in images:
        img = img.convert('RGBA')
        rgba_images.append(img)
    rgba_images[0].save(
        save_path,
        format='PNG',
        save_all=True,
        append_images=rgba_images[1:],
        duration=duration,
        loop=loop
    )

# 图像乘颜色
def multiply_image_by_color(img: Image.Image, color: tuple):
    if img.mode.upper() not in ['RGB', 'RGBA']:
        img = img.convert('RGBA')
    channel = 4 if img.mode.upper() == 'RGBA' else 3
    img_np = np.array(img, dtype=np.float32)
    if len(color) == 3:
        color = (*color, 255)
    color_np = np.array(color[:channel], dtype=np.float32)
    img_np = img_np * color_np / 255
    img_np = np.clip(img_np, 0, 255).astype(np.uint8)
    return Image.fromarray(img_np, mode=img.mode)
