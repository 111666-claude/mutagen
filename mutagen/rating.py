# Copyright (C) 2026  Mutagen Contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Unified listener ratings and play counts.

This module gives applications a single way to read and write personal
ratings (0-5 stars) and play counts across tag formats that store them
differently:

* MP3 / ID3: each rating lives in a POPM frame keyed by its owner
  (an email-like string).  The rating byte is in the range 0-255 and the
  play count is the optional POPM counter.  Multiple owners never
  overwrite each other.
* FLAC: the Vorbis comment keys ``RATING`` (a decimal number in the same
  0-255 range as the POPM rating byte) and ``PLAYCOUNT`` (a non-negative
  decimal integer) are used.  Vorbis comments have no notion of an owner,
  so only the single default user is supported; passing an explicit owner
  raises :class:`RatingError`.

The 0-5 star rating and the 0-255 wire value map linearly.  Both
directions round trip exactly for the integer star values::

    stars -> 0, 51, 102, 153, 204, 255 -> stars

Any value read from a file that cannot be interpreted (duplicate or
out-of-range comment fields, a POPM rating byte outside 0-255, a negative
play count, ...) raises :class:`RatingError` instead of being silently
guessed.
"""

from ._util import MutagenError
from .id3 import ID3
from .id3._frames import POPM
from .flac import FLAC, VCFLACDict

__all__ = [
    "RatingError",
    "DEFAULT_OWNER",
    "MIN_RATING",
    "MAX_RATING",
    "MIN_WIRE_RATING",
    "MAX_WIRE_RATING",
    "stars_to_rating",
    "rating_to_stars",
    "get_rating",
    "set_rating",
    "get_play_count",
    "set_play_count",
    "delete_rating",
]


class RatingError(MutagenError):
    """Raised when rating data is missing, ambiguous or malformed."""


#: The owner used when no owner is given.  The POPM spec identifies users
#: by an email address and an empty string is a valid identifier; it is
#: used here so files tagged on behalf of "the default user" stay
#: interoperable with other taggers.
DEFAULT_OWNER = u""

#: Smallest and largest supported star rating.
MIN_RATING = 0
MAX_RATING = 5

#: Smallest and largest value stored on the wire (POPM rating byte and
#: FLAC ``RATING`` comment).
MIN_WIRE_RATING = 0
MAX_WIRE_RATING = 255

_FLAC_RATING_KEY = u"RATING"
_FLAC_PLAYCOUNT_KEY = u"PLAYCOUNT"


def stars_to_rating(stars):
    """stars_to_rating(stars)

    Map a 0-5 star rating to its linear 0-255 wire value.

    Args:
        stars (int): star rating, between :data:`MIN_RATING` and
            :data:`MAX_RATING`

    Returns:
        int: rating in the 0-255 range

    Raises:
        TypeError: if *stars* is not an integer
        ValueError: if *stars* is outside the supported range
    """

    if isinstance(stars, bool) or not isinstance(stars, int):
        raise TypeError("rating must be an int, not %r" % type(stars).__name__)
    if stars < MIN_RATING or stars > MAX_RATING:
        raise ValueError(
            "rating must be between %d and %d stars" %
            (MIN_RATING, MAX_RATING))
    # Exact linear mapping; the numerator is always divisible by 5 for the
    # supported star values (0, 51, 102, 153, 204, 255).
    return stars * MAX_WIRE_RATING // MAX_RATING


def rating_to_stars(rating):
    """rating_to_stars(rating)

    Map a 0-255 wire value back to the nearest 0-5 star rating.

    Values that do not correspond to an exact star value are rounded to
    the nearest one (half values round up), so arbitrary data written by
    other taggers degrades gracefully.

    Args:
        rating (int): wire value, between :data:`MIN_WIRE_RATING` and
            :data:`MAX_WIRE_RATING`

    Returns:
        int: star rating in the 0-5 range

    Raises:
        TypeError: if *rating* is not an integer
        ValueError: if *rating* is outside the supported range
    """

    if isinstance(rating, bool) or not isinstance(rating, int):
        raise TypeError("rating must be an int, not %r" % type(rating).__name__)
    if rating < MIN_WIRE_RATING or rating > MAX_WIRE_RATING:
        raise ValueError(
            "rating must be between %d and %d" %
            (MIN_WIRE_RATING, MAX_WIRE_RATING))
    # Round half up without relying on banker's rounding.
    return (rating * MAX_RATING + MAX_WIRE_RATING // 2) // MAX_WIRE_RATING


def _tags_of(audio):
    """Return the mutable tag object of *audio*, or raise RatingError."""

    # Accept both file objects (MP3, FLAC) and bare tag objects (ID3,
    # VCFLACDict) so callers can work at either level.
    if isinstance(audio, (ID3, VCFLACDict)):
        return audio
    if isinstance(audio, FLAC):
        if audio.tags is None:
            raise RatingError("file has no Vorbis comment block")
        return audio.tags
    tags = getattr(audio, "tags", None)
    if isinstance(tags, (ID3, VCFLACDict)):
        return tags
    if tags is None and hasattr(audio, "add_tags"):
        # A supported audio file without any tag block (e.g. an MP3 with
        # no ID3 tag); call add_tags() first.
        raise RatingError(
            "file has no tags; call add_tags() before writing ratings")
    raise RatingError(
        "unsupported tag object %r" % type(audio).__name__)


def _require_owner(owner):
    if owner is None:
        return DEFAULT_OWNER
    if not isinstance(owner, str):
        raise TypeError("owner must be a string, not %r" %
                        type(owner).__name__)
    return owner


def _popm_frame(tags, owner, create=False):
    """Return the POPM frame for *owner*, optionally creating it."""

    key = POPM(email=owner).HashKey
    try:
        return tags[key]
    except KeyError:
        if not create:
            return None
        frame = POPM(email=owner, rating=0)
        tags.add(frame)
        return frame


def _parse_non_negative_int(text, key):
    # A strict canonical decimal integer: ASCII digits only, at least one.
    # Whitespace, signs, floats, hex and non-ASCII numerals are rejected.
    if not isinstance(text, str) or not text or \
            not all("0" <= c <= "9" for c in text):
        raise RatingError("malformed %s value: %r" % (key, text))
    return int(text)


def _single_comment(tags, key):
    """Return the unique string value of a FLAC comment, or None."""

    values = tags.get(key)
    if values is None:
        return None
    if len(values) != 1:
        raise RatingError(
            "conflicting %s tags: %r" % (key, values))
    return values[0]


def get_rating(audio, owner=None):
    """get_rating(audio, owner=None)

    Read the 0-5 star rating.

    Args:
        audio: an :class:`~mutagen.mp3.MP3`, :class:`~mutagen.flac.FLAC`,
            :class:`~mutagen.id3.ID3` or
            :class:`~mutagen._vorbis.VCommentDict` instance
        owner (str): POPM owner (email) for ID3 files; ignored for FLAC,
            where any owner other than the default user is rejected

    Returns:
        int: star rating (0-5), or `None` if no rating has been stored

    Raises:
        RatingError: for conflicting, out-of-range or malformed data, or
            when an explicit owner is given for a FLAC file
        TypeError: for invalid argument types
    """

    tags = _tags_of(audio)

    if isinstance(tags, ID3):
        owner = _require_owner(owner)
        frame = _popm_frame(tags, owner)
        if frame is None:
            return None
        if frame.rating < MIN_WIRE_RATING or \
                frame.rating > MAX_WIRE_RATING:
            # Defensive: a POPM rating is a single byte, so this can only
            # happen if a custom frame was hand built.
            raise RatingError(
                "POPM rating out of range for %r: %r" %
                (owner, frame.rating))
        return rating_to_stars(frame.rating)

    if owner is not None and owner != DEFAULT_OWNER:
        raise RatingError(
            "FLAC ratings only support the default user, not owner %r"
            % owner)
    text = _single_comment(tags, _FLAC_RATING_KEY)
    if text is None:
        return None
    value = _parse_non_negative_int(text, _FLAC_RATING_KEY)
    if value < MIN_WIRE_RATING or value > MAX_WIRE_RATING:
        raise RatingError(
            "RATING out of %d-%d range: %r" %
            (MIN_WIRE_RATING, MAX_WIRE_RATING, text))
    return rating_to_stars(value)


def set_rating(audio, stars, owner=None):
    """set_rating(audio, stars, owner=None)

    Write a 0-5 star rating.

    Existing frames or comments for the same owner/key are replaced in
    place; all other tags (including other POPM owners on ID3 files) are
    left untouched.  The change is made on the in-memory tag object, so
    call :meth:`save` on the file afterwards to persist it.

    Args:
        audio: an :class:`~mutagen.mp3.MP3`, :class:`~mutagen.flac.FLAC`,
            :class:`~mutagen.id3.ID3` or
            :class:`~mutagen._vorbis.VCommentDict` instance
        stars (int): star rating (0-5)
        owner (str): POPM owner (email) for ID3 files; rejected for FLAC

    Raises:
        RatingError: when an explicit owner is given for a FLAC file
        TypeError: for invalid argument types
        ValueError: if *stars* is outside 0-5
    """

    tags = _tags_of(audio)
    wire = stars_to_rating(stars)

    if isinstance(tags, ID3):
        owner = _require_owner(owner)
        frame = _popm_frame(tags, owner, create=True)
        frame.rating = wire
        return

    if owner is not None and owner != DEFAULT_OWNER:
        raise RatingError(
            "FLAC ratings only support the default user, not owner %r"
            % owner)
    # __setitem__ removes every old value first, so conflicting duplicates
    # are normalized on write.
    tags[_FLAC_RATING_KEY] = str(wire)


def get_play_count(audio, owner=None):
    """get_play_count(audio, owner=None)

    Read the number of times the file has been played.

    Args:
        audio: an :class:`~mutagen.mp3.MP3`, :class:`~mutagen.flac.FLAC`,
            :class:`~mutagen.id3.ID3` or
            :class:`~mutagen._vorbis.VCommentDict` instance
        owner (str): POPM owner (email) for ID3 files; ignored for FLAC

    Returns:
        int: non-negative play count, or `None` if none has been stored.
        A POPM frame without a counter reports `None`; a FLAC file with
        no ``PLAYCOUNT`` comment likewise reports `None`.

    Raises:
        RatingError: for conflicting, negative or malformed data
        TypeError: for invalid argument types
    """

    tags = _tags_of(audio)

    if isinstance(tags, ID3):
        owner = _require_owner(owner)
        frame = _popm_frame(tags, owner)
        if frame is None or not hasattr(frame, "count"):
            return None
        if frame.count < 0:
            raise RatingError(
                "negative POPM play count for %r: %r" %
                (owner, frame.count))
        return frame.count

    if owner is not None and owner != DEFAULT_OWNER:
        raise RatingError(
            "FLAC play counts only support the default user, not owner %r"
            % owner)
    text = _single_comment(tags, _FLAC_PLAYCOUNT_KEY)
    if text is None:
        return None
    count = _parse_non_negative_int(text, _FLAC_PLAYCOUNT_KEY)
    return count


def set_play_count(audio, count, owner=None):
    """set_play_count(audio, count, owner=None)

    Write the number of times the file has been played.

    On ID3 files the POPM frame for *owner* is created (with a zero
    rating) if it does not exist yet.  The change is made in memory;
    call :meth:`save` on the file to persist it.

    Args:
        audio: an :class:`~mutagen.mp3.MP3`, :class:`~mutagen.flac.FLAC`,
            :class:`~mutagen.id3.ID3` or
            :class:`~mutagen._vorbis.VCommentDict` instance
        count (int): non-negative play count
        owner (str): POPM owner (email) for ID3 files; rejected for FLAC

    Raises:
        RatingError: when an explicit owner is given for a FLAC file
        TypeError: for invalid argument types
        ValueError: if *count* is negative
    """

    tags = _tags_of(audio)

    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError(
            "play count must be an int, not %r" % type(count).__name__)
    if count < 0:
        raise ValueError("play count must be non-negative")

    if isinstance(tags, ID3):
        owner = _require_owner(owner)
        frame = _popm_frame(tags, owner, create=True)
        frame.count = count
        return

    if owner is not None and owner != DEFAULT_OWNER:
        raise RatingError(
            "FLAC play counts only support the default user, not owner %r"
            % owner)
    tags[_FLAC_PLAYCOUNT_KEY] = str(count)


def delete_rating(audio, owner=None):
    """delete_rating(audio, owner=None)

    Remove the stored rating and play count.

    On ID3 files only the POPM frame belonging to *owner* is removed;
    frames belonging to other owners survive.  On FLAC files both the
    ``RATING`` and ``PLAYCOUNT`` comments are removed.

    Args:
        audio: an :class:`~mutagen.mp3.MP3`, :class:`~mutagen.flac.FLAC`,
            :class:`~mutagen.id3.ID3` or
            :class:`~mutagen._vorbis.VCommentDict` instance
        owner (str): POPM owner (email) for ID3 files; rejected for FLAC

    Returns:
        bool: `True` if something was removed, `False` if there was nothing

    Raises:
        RatingError: when an explicit owner is given for a FLAC file
        TypeError: for invalid argument types
    """

    tags = _tags_of(audio)

    if isinstance(tags, ID3):
        owner = _require_owner(owner)
        frame = _popm_frame(tags, owner)
        if frame is None:
            return False
        del tags[frame.HashKey]
        return True

    if owner is not None and owner != DEFAULT_OWNER:
        raise RatingError(
            "FLAC ratings only support the default user, not owner %r"
            % owner)
    removed = False
    for key in (_FLAC_RATING_KEY, _FLAC_PLAYCOUNT_KEY):
        try:
            del tags[key]
        except KeyError:
            pass
        else:
            removed = True
    return removed
