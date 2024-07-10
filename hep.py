"""
header : 20 bytes :

0x00:0x03   magic bytes : HEP\0
0x04:0x07   file size (little endian, from start of header to last byte of file)
0x08:0x0F   ? (e.g., 00 00 30 1D 06 00 00 00 / 00 00 30 25 06 00 00 00), seems to depend on dimensions
0x10:0x13   ? (e.g., 10 00 00 00)
0x14:0x17   width
0x18:0x1B   height
0x1C:0x1F   ? (e.g., 02 00 00 00)
{width*height}
n*4 bytes : palette (RGBA)
"""

import struct
import numpy as np
from PIL import Image
from typing import TYPE_CHECKING

from .utils.io import BytesReader
from .mzx import mzx_decompress, mzx_compress
if TYPE_CHECKING :
    from .mzp import MzpImage

def fix_alpha(a) :
    if a & 0x80 == 0 :
        return np.uint8(((a << 1) | (a >> 6)) & 0xFF)
    else :
        return np.uint8(0xFF)
np_fix_alpha = np.vectorize(fix_alpha)

def unfix_alpha(a: np.uint8) :
    if a == 0xFF :
        return a
    else :
        return np.uint8(a >> 1)
np_unfix_alpha = np.vectorize(unfix_alpha)

HEP_MAGIC = int.from_bytes(b'HEP\0', 'little')
HEP_HEADER_SIZE = 0x20
HEP_PALETTE_SIZE = 0x400

def hep_extract_tile(mzp: "MzpImage", tile_index: int) :
    decomp = mzx_decompress(mzp[tile_index+1].to_file())

    (   magic, file_size, _, _, _, width, height, _
    ) = struct.unpack("<IIIIIIII", decomp.read(HEP_HEADER_SIZE))
    nb_pixels = width*height
    assert magic == HEP_MAGIC
    assert width == mzp.tile_width
    assert height == mzp.tile_height
    assert file_size == HEP_HEADER_SIZE + nb_pixels + HEP_PALETTE_SIZE

    decomp.seek(HEP_HEADER_SIZE + nb_pixels)
    palette = np.frombuffer(decomp.read(HEP_PALETTE_SIZE), dtype=np.uint8)
    assert palette.size == HEP_PALETTE_SIZE
    palette.shape = (256, 4)
    palette = np.hstack((palette[:, :3], np_fix_alpha(palette[:, 3:])), dtype=np.uint8)

    decomp.seek(HEP_HEADER_SIZE)
    pixels = palette[np.frombuffer(decomp.read(nb_pixels), dtype=np.uint8)]

    return pixels

def hep_insert_tile(mzp: "MzpImage", tile_index: int, pixels: np.ndarray) :
    import imagequant
    
    pixels = pixels.reshape((mzp.tile_width, mzp.tile_height, 4))
    img = Image.fromarray(pixels, "RGBA")

    img = imagequant.quantize_pil_image(
        img,
        dithering_level=1.0,  # from 0.0 to 1.0
        max_colors=256,       # from 1 to 256
        min_quality=0,        # from 0 to 100
        max_quality=100,      # from 0 to 100
    )
    palette = img.palette
    pixels = np.array(img)
    assert palette is not None

    assert palette.mode == "RGBA"
    palette = np.fromiter(palette.palette, dtype=np.uint8)
    palette.shape = (256, 4)
    palette = np.hstack((palette[:, :3], np_unfix_alpha(palette[:, 3:])), dtype=np.uint8)
    
    file = mzx_decompress(mzp[tile_index+1].to_file())
    file.seek(HEP_HEADER_SIZE)
    file.write(pixels.tobytes())
    assert file.tell() == HEP_HEADER_SIZE + mzp.tile_width * mzp.tile_height
    file.write(palette.tobytes())
    file.seek(0)
    mzp[tile_index+1].from_file(mzx_compress(file))
