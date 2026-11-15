# Copyright (C) 2026  Mutagen Authors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""A unified front-cover entry point for MP3 (ID3 APIC), FLAC (PICTURE
block) and M4A/MP4 (``covr`` atom).

The native tag APIs all model embedded pictures, but each format exposes
them differently:

* MP3 stores them as :class:`mutagen.id3.APIC` frames,
* FLAC stores them as :class:`mutagen.flac.Picture` metadata blocks,
* M4A stores them as :class:`mutagen.mp4.MP4Cover` items under ``covr``.

This module hides those differences behind three functions operating on a
loaded :class:`mutagen.FileType` object::

    from mutagen import File
    from mutagen.cover import get_front_cover, set_front_cover, remove_front_cover

    audio = File("game-ost.mp3")
    cover = get_front_cover(audio)          # CoverArt or None
    if cover is not None:
        cover.data, cover.image_type        # raw bytes and "jpeg"/"png"

    set_front_cover(audio, new_jpeg_bytes)  # replace (or add) the main cover
    audio.save()                             # persist, like every mutagen edit

    remove_front_cover(audio)               # only the front cover is removed
    audio.save()

Only JPEG and PNG data can be written; the real image type is always
determined from the byte content, never from a MIME string claimed by the
file. Back covers, other pictures and unrelated audio tags are never
touched.
"""

from ._util import MutagenError

__all__ = [
    "CoverArt",
    "CoverError",
    "error",
    "InvalidImageError",
    "UnsupportedCoverFormatError",
    "get_front_cover",
    "set_front_cover",
    "remove_front_cover",
]

JPEG = "jpeg"
PNG = "png"

_MIME_TYPES = {
    JPEG: "image/jpeg",
    PNG: "image/png",
}

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class CoverError(MutagenError):
    """Base class for all errors raised by this module."""


error = CoverError
"""Alias of :class:`CoverError`, following the per-module ``error``
convention used throughout mutagen."""


class InvalidImageError(CoverError):
    """The data is empty or is neither a JPEG nor a PNG image.

    Only JPEG and PNG covers can be embedded across MP3, FLAC and M4A.
    """


class UnsupportedCoverFormatError(CoverError):
    """The loaded audio object is not an MP3, FLAC or M4A/MP4 file."""


def _sniff_image_type(data):
    """Return ``"jpeg"``/``"png"`` for known magic bytes, else ``None``."""

    if data.startswith(_JPEG_MAGIC):
        return JPEG
    if data.startswith(_PNG_MAGIC):
        return PNG
    return None


class CoverArt(object):
    """CoverArt(data, image_type)

    A format-independent picture returned by :func:`get_front_cover` and
    accepted by :func:`set_front_cover`.

    Attributes:
        data (`bytes`): raw, undecoded image bytes
        image_type (`str`): the real image type detected from the byte
            content -- either :data:`CoverArt.JPEG` or :data:`CoverArt.PNG`
        mime (`str`): the MIME type matching :attr:`image_type`
    """

    JPEG = JPEG
    PNG = PNG

    def __init__(self, data, image_type):
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        if image_type not in _MIME_TYPES:
            raise ValueError(
                "image_type must be %r or %r, got %r"
                % (JPEG, PNG, image_type))
        self.data = data
        self.image_type = image_type

    @property
    def mime(self):
        """`text`: MIME type of the picture (``image/jpeg``/``image/png``)."""

        return _MIME_TYPES[self.image_type]

    def __eq__(self, other):
        try:
            return (self.data == other.data and
                    self.image_type == other.image_type)
        except AttributeError:
            return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return hash((self.image_type, self.data))

    def __repr__(self):
        return "%s(%d bytes, %r)" % (
            type(self).__name__, len(self.data), self.image_type)


def _require_supported(audio):
    # Imported lazily so that importing mutagen.cover does not pull in every
    # format implementation (and to avoid any import cycle).
    from .mp3 import MP3
    from .flac import FLAC
    from .mp4 import MP4

    if isinstance(audio, (MP3, FLAC, MP4)):
        return
    raise UnsupportedCoverFormatError(
        "%r is not an MP3, FLAC or M4A/MP4 file"
        % (type(audio).__name__,))


def _cover_from_data(data, declared_mime=None):
    """Build a CoverArt from raw bytes, validating the real image type."""

    image_type = _sniff_image_type(data)
    if image_type is not None:
        return CoverArt(bytes(data), image_type)
    # An embedded picture the format still accepts but this module cannot
    # round-trip (GIF/BMP/...): surface it explicitly instead of guessing.
    raise InvalidImageError(
        "front cover is not a JPEG or PNG image%s"
        % (" (declared %s)" % declared_mime if declared_mime else ""))


def _get_id3(audio):
    # get_front_cover for MP3: the first front-cover APIC frame.
    if audio.tags is None:
        return None
    from .id3 import PictureType

    for frame in audio.tags.getall("APIC"):
        if int(frame.type) == PictureType.COVER_FRONT:
            return _cover_from_data(frame.data, frame.mime)
    return None


def _set_id3(audio, data, image_type):
    from .id3 import APIC, PictureType

    if audio.tags is None:
        audio.add_tags()

    # Remove every existing front cover; back covers and other frames stay.
    frames = [
        frame for frame in audio.tags.getall("APIC")
        if int(frame.type) != PictureType.COVER_FRONT
    ]
    audio.tags.setall("APIC", frames)
    audio.tags.add(APIC(
        encoding=3,  # UTF-8
        mime=_MIME_TYPES[image_type],
        type=PictureType.COVER_FRONT,
        desc=u"",
        data=data,
    ))


def _remove_id3(audio):
    if audio.tags is None:
        return False
    from .id3 import PictureType

    fronts = [
        frame for frame in audio.tags.getall("APIC")
        if int(frame.type) == PictureType.COVER_FRONT
    ]
    if not fronts:
        return False
    audio.tags.setall("APIC", [
        frame for frame in audio.tags.getall("APIC")
        if int(frame.type) != PictureType.COVER_FRONT
    ])
    return True


def _get_flac(audio):
    from .id3 import PictureType

    for picture in audio.pictures:
        if int(picture.type) == PictureType.COVER_FRONT:
            return _cover_from_data(picture.data, picture.mime)
    return None


def _set_flac(audio, data, image_type):
    from .flac import Picture
    from .id3 import PictureType

    # Replace an existing front cover in place; other picture blocks stay.
    for picture in audio.pictures:
        if int(picture.type) == PictureType.COVER_FRONT:
            picture.data = data
            picture.mime = _MIME_TYPES[image_type]
            return

    picture = Picture()
    picture.type = PictureType.COVER_FRONT
    picture.mime = _MIME_TYPES[image_type]
    picture.desc = u""
    picture.data = data
    audio.add_picture(picture)


def _remove_flac(audio):
    from .id3 import PictureType
    from .flac import Picture

    fronts = {
        id(block) for block in audio.metadata_blocks
        if block.code == Picture.code and
        int(block.type) == PictureType.COVER_FRONT
    }
    if not fronts:
        return False
    audio.metadata_blocks[:] = [
        block for block in audio.metadata_blocks
        if id(block) not in fronts
    ]
    return True


def _get_mp4(audio):
    if audio.tags is None or "covr" not in audio.tags:
        return None
    covers = audio.tags["covr"]
    if not covers:
        return None
    from .mp4 import AtomDataType

    cover = bytes(covers[0])
    return _cover_from_data(
        cover,
        "png" if getattr(covers[0], "imageformat", None) ==
        AtomDataType.PNG else
        ("jpeg" if getattr(covers[0], "imageformat", None) ==
         AtomDataType.JPEG else None))


def _set_mp4(audio, data, image_type):
    from .mp4 import MP4Cover, AtomDataType

    if audio.tags is None:
        audio.add_tags()

    cover_format = (
        AtomDataType.PNG if image_type == PNG else AtomDataType.JPEG)
    new_cover = MP4Cover(data, cover_format)

    existing = list(audio.tags.get("covr", []))
    if existing:
        # Replace only the first (main) cover; extra covr entries are kept.
        existing[0] = new_cover
    else:
        existing = [new_cover]
    audio.tags["covr"] = existing


def _remove_mp4(audio):
    if audio.tags is None or "covr" not in audio.tags:
        return False
    covers = list(audio.tags["covr"])
    if not covers:
        return False
    covers.pop(0)  # only the main cover
    if covers:
        audio.tags["covr"] = covers
    else:
        del audio.tags["covr"]
    return True


def get_front_cover(audio):
    """Return the main (front) cover embedded in *audio*.

    Args:
        audio: a loaded :class:`mutagen.mp3.MP3`,
            :class:`mutagen.flac.FLAC` or :class:`mutagen.mp4.MP4`
            instance (as returned by :func:`mutagen.File`).

    Returns:
        CoverArt: the front cover, with its raw bytes and the real JPEG/PNG
        type detected from the content.

        `None` if the file has no tags or no front cover.

    Raises:
        UnsupportedCoverFormatError: if *audio* is not one of the three
            supported formats.
    """

    _require_supported(audio)

    from .mp3 import MP3
    from .flac import FLAC

    if isinstance(audio, MP3):
        return _get_id3(audio)
    if isinstance(audio, FLAC):
        return _get_flac(audio)
    return _get_mp4(audio)


def set_front_cover(audio, data, image_type=None):
    """Add or replace the main (front) cover in *audio*.

    Other pictures (back covers, booklets, ...) and all unrelated audio
    tags are preserved. Call ``audio.save()`` afterwards to persist the
    change, as with any mutagen edit.

    Args:
        audio: a loaded :class:`mutagen.mp3.MP3`,
            :class:`mutagen.flac.FLAC` or :class:`mutagen.mp4.MP4`.
        data (`bytes`): raw JPEG or PNG image bytes.
        image_type (`str`, optional): :data:`CoverArt.JPEG` or
            :data:`CoverArt.PNG`. When `None` (the default) the type is
            sniffed from the magic bytes of *data*.

    Raises:
        InvalidImageError: if *data* is empty or its type cannot be
            determined as JPEG/PNG (and no valid *image_type* was given).
        UnsupportedCoverFormatError: if *audio* is not one of the three
            supported formats.
    """

    _require_supported(audio)

    if not isinstance(data, bytes):
        raise InvalidImageError("image data must be bytes")
    if not data:
        raise InvalidImageError("image data is empty")

    if image_type is None:
        image_type = _sniff_image_type(data)
        if image_type is None:
            raise InvalidImageError(
                "image data is neither JPEG nor PNG; pass image_type only "
                "for data with recognizable JPEG/PNG magic bytes")
    elif image_type not in _MIME_TYPES:
        raise InvalidImageError(
            "unsupported image type %r; only %r and %r are supported"
            % (image_type, JPEG, PNG))
    elif _sniff_image_type(data) not in (None, image_type):
        raise InvalidImageError(
            "image_type %r does not match the actual image data"
            % image_type)

    from .mp3 import MP3
    from .flac import FLAC

    if isinstance(audio, MP3):
        _set_id3(audio, data, image_type)
    elif isinstance(audio, FLAC):
        _set_flac(audio, data, image_type)
    else:
        _set_mp4(audio, data, image_type)


def remove_front_cover(audio):
    """Remove the main (front) cover from *audio*.

    Back covers, other embedded pictures and all unrelated audio tags are
    preserved. Call ``audio.save()`` afterwards to persist the change.

    Args:
        audio: a loaded :class:`mutagen.mp3.MP3`,
            :class:`mutagen.flac.FLAC` or :class:`mutagen.mp4.MP4`.

    Returns:
        bool: `True` if a front cover was removed, `False` if there was
        none (including files without any tags -- such files are left
        untouched and no empty tag block is created).

    Raises:
        UnsupportedCoverFormatError: if *audio* is not one of the three
            supported formats.
    """

    _require_supported(audio)

    from .mp3 import MP3
    from .flac import FLAC

    if isinstance(audio, MP3):
        return _remove_id3(audio)
    if isinstance(audio, FLAC):
        return _remove_flac(audio)
    return _remove_mp4(audio)
