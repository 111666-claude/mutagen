# Copyright (C) 2026  Mutagen Contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Unified access to timed (line-synchronised) lyrics.

Different audio formats store synchronised lyrics differently. This
module presents one entry point on top of the native tag objects:

* MP3/ID3: ``SYLT`` frames, one per language, using the millisecond
  time stamp format. Frames using the MPEG-frame unit are not timed
  lyrics in the sense of this module and are ignored.
* FLAC: the Vorbis comment ``LYRICS`` field holding an LRC block. LRC
  has no language concept, so the default language
  (:data:`DEFAULT_LANGUAGE`) is used.

The lyrics themselves are a `TimedLyrics` object: an ordered sequence
of `LyricsLine` ``(text, time)`` pairs where ``time`` is the offset in
milliseconds. Lines keep their on-disk order, so repeated time stamps
remain stable.
"""

__all__ = [
    "LyricsError", "LyricsLine", "TimedLyrics", "DEFAULT_LANGUAGE",
    "get_lyrics", "getall_lyrics", "set_lyrics", "delete_lyrics",
    "parse_lrc", "serialize_lrc",
]

import re

from ._util import MutagenError

#: Language assigned to lyrics that have no native language concept
#: (FLAC/LRC). It matches the "unknown language" placeholder used by
#: ID3 language fields.
DEFAULT_LANGUAGE = u"XXX"

# ID3v2 SYLT time stamp format byte: 1 = MPEG frames, 2 = milliseconds.
_SYLT_FORMAT_MILLISECONDS = 2

# LRC time stamp, e.g. "[1:02.50]", "[01:02.500]" or "[03:05.]"; the
# fractional part may have any number of digits (hundredths are typical
# for LRC) or be left empty after the separator.
_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d*))?\]")

# LRC metadata tags look like "[ar:Artist]"; they carry no time stamp.
_LRC_METADATA_RE = re.compile(r"^\[[^\[\]]*:[^\[\]]*\]$")


class LyricsError(MutagenError):
    """Raised when timed lyrics can't be parsed or validated."""


class LyricsLine(tuple):
    """LyricsLine(text, time)

    A single synchronised lyrics line.

    Attributes:
        text (`str`): text of the line (may be empty)
        time (`int`): start time of the line in milliseconds
    """

    def __new__(cls, text, time):
        return super(LyricsLine, cls).__new__(cls, (text, time))

    def __getnewargs__(self):
        return self.text, self.time

    text = property(lambda self: self[0])
    time = property(lambda self: self[1])

    def __repr__(self):
        return "LyricsLine(text=%r, time=%r)" % (self.text, self.time)


class TimedLyrics(list):
    """TimedLyrics(lines=None, language=DEFAULT_LANGUAGE)

    An ordered list of `LyricsLine` objects with an associated language.

    The sequence order is the on-disk order; lines sharing a time stamp
    keep a stable relative order.

    Attributes:
        language (`str`): three letter ISO 639-2 language code;
            :data:`DEFAULT_LANGUAGE` for formats without a language
    """

    def __init__(self, lines=None, language=DEFAULT_LANGUAGE):
        super(TimedLyrics, self).__init__()
        self.language = language
        if lines is not None:
            self.extend(lines)

    def __repr__(self):
        return "TimedLyrics(language=%r, lines=%s)" % (
            self.language, list.__repr__(self))

    def __eq__(self, other):
        if isinstance(other, TimedLyrics):
            return (self.language == other.language and
                    list.__eq__(self, other))
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None

    def append(self, line):
        super(TimedLyrics, self).append(_coerce_line(line))

    def extend(self, lines):
        super(TimedLyrics, self).extend(_coerce_line(line) for line in lines)

    def insert(self, index, line):
        super(TimedLyrics, self).insert(index, _coerce_line(line))


def _coerce_line(line):
    if isinstance(line, LyricsLine):
        text, time = line
    else:
        try:
            text, time = line
        except (TypeError, ValueError):
            raise LyricsError(
                "lyrics lines must be (text, time) pairs, got %r" % (line,))
    if not isinstance(text, str):
        raise LyricsError("lyrics text must be str, got %r" % (text,))
    if isinstance(time, bool) or not isinstance(time, int):
        raise LyricsError("lyrics time must be an int of milliseconds, "
                          "got %r" % (time,))
    if time < 0:
        raise LyricsError("lyrics time must not be negative, got %d" % time)
    if time > 0xFFFFFFFF:
        raise LyricsError(
            "lyrics time %d exceeds the 32 bit unsigned range" % time)
    return LyricsLine(text, time)


def _coerce_lyrics(lyrics):
    """Validate user input and return a TimedLyrics copy."""

    if isinstance(lyrics, TimedLyrics):
        language = lyrics.language
        lines = lyrics
    else:
        language = DEFAULT_LANGUAGE
        lines = lyrics
    if not isinstance(language, str) or len(language) != 3:
        raise LyricsError(
            "language must be a 3 character string, got %r" % (language,))
    try:
        language.encode("ascii")
    except (UnicodeEncodeError, AttributeError):
        raise LyricsError("language must be ASCII, got %r" % (language,))
    result = TimedLyrics(language=language)
    try:
        result.extend(lines)
    except TypeError:
        raise LyricsError("lyrics must be a sequence of (text, time) pairs")
    return result


def _format_lrc_time(time):
    minutes, milliseconds = divmod(time, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return u"[%02d:%02d.%03d]" % (minutes, seconds, milliseconds)


def parse_lrc(data):
    """Parse an LRC block into `TimedLyrics`.

    Handles ``[mm:ss.xx]`` (and sub-second variants), multiple time
    stamps on one line (each stamp gets the line's text) and empty text.
    Metadata lines (e.g. ``[ar:...]``) and blank lines are ignored.

    Args:
        data (str): LRC text

    Returns:
        TimedLyrics: parsed lines in file order

    Raises:
        LyricsError: if a bracketed line has no parseable time stamp
    """

    if not isinstance(data, str):
        raise LyricsError("LRC input must be str, got %r" % (type(data),))

    lyrics = TimedLyrics()
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        stamps = list(_LRC_TIME_RE.finditer(line))
        if not stamps:
            # Metadata lines such as [ar:Artist] carry no time stamp.
            if _LRC_METADATA_RE.match(line):
                continue
            raise LyricsError("LRC line has no valid time stamp: %r"
                              % raw_line)

        text = line[stamps[-1].end():].strip()
        for match in stamps:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3)
            if not fraction:
                milliseconds = 0
            else:
                # Any number of fractional digits is interpreted against
                # the millisecond position (LRC normally uses hundredths).
                milliseconds = int(fraction.ljust(3, "0")[:3])
            time = minutes * 60000 + seconds * 1000 + milliseconds
            lyrics.append(LyricsLine(text, time))
    return lyrics


def serialize_lrc(lyrics):
    """Serialize `TimedLyrics` (or a sequence of lines) to LRC text.

    Returns:
        str: LRC block with ``[mm:ss.mmm]`` stamps, one line per lyrics
        line; repeated time stamps are emitted in sequence
    """

    if not isinstance(lyrics, TimedLyrics):
        lyrics = _coerce_lyrics(lyrics)
    return u"".join(
        u"%s%s\n" % (_format_lrc_time(line.time), line.text)
        for line in lyrics)


def _sylt_to_lyrics(frame):
    lines = TimedLyrics(language=frame.lang)
    for text, time in frame.text:
        # SYLT stores unsigned 32 bit values, so no negative time can
        # occur here; out-of-range values are equally impossible. Still
        # route everything through the same validator so the contract
        # is identical on every code path.
        lines.append(LyricsLine(text, time))
    return lines


def _lyrics_to_sylt(lyrics):
    from .id3 import SYLT, Encoding

    return SYLT(
        encoding=Encoding.UTF8,
        lang=lyrics.language,
        format=_SYLT_FORMAT_MILLISECONDS,
        type=1,
        desc=u"",
        text=[(line.text, line.time) for line in lyrics],
    )


def _is_id3_tags(tags):
    # Duck typing keeps the import graph free of hard dependencies.
    return hasattr(tags, "getall") and hasattr(tags, "setall") and \
        hasattr(tags, "delall")


def _is_vorbis_tags(tags):
    return hasattr(tags, "append") and hasattr(tags, "as_dict") and \
        hasattr(tags, "keys")


def getall_lyrics(tags):
    """Return all timed lyrics stored in a tag object.

    Args:
        tags: an ID3 tag object (e.g. ``MP3.tags``), a Vorbis comment
            (e.g. ``FLAC.tags``), or ``None`` for a file without tags

    Returns:
        list[TimedLyrics]: one `TimedLyrics` per language for ID3, or a
        single element for the FLAC ``LYRICS`` field; empty if none
    """

    if tags is None:
        return []
    if _is_id3_tags(tags):
        result = []
        for frame in tags.getall("SYLT"):
            if frame.format != _SYLT_FORMAT_MILLISECONDS:
                # MPEG-frame units are not millisecond timed lyrics.
                continue
            result.append(_sylt_to_lyrics(frame))
        return result
    elif _is_vorbis_tags(tags):
        if "LYRICS" not in tags:
            return []
        result = []
        for value in tags["LYRICS"]:
            result.append(parse_lrc(value))
        return result
    else:
        raise LyricsError(
            "unsupported tag object %r; expected ID3 tags or a Vorbis "
            "comment" % (type(tags),))


def get_lyrics(tags, language=DEFAULT_LANGUAGE):
    """Return timed lyrics for one language, or ``None`` if absent.

    Args:
        tags: an ID3 tag object or a Vorbis comment
        language (str): three letter language code; ignored for FLAC,
            whose LRC lyrics are always the default language
    """

    for lyrics in getall_lyrics(tags):
        if lyrics.language == language:
            return lyrics
    return None


def set_lyrics(tags, lyrics, language=DEFAULT_LANGUAGE):
    """Replace the timed lyrics of one language while keeping the rest.

    For ID3 only the matching-language ``SYLT`` frames are replaced;
    other languages, other frame types and unknown frames are left
    untouched. For FLAC only the ``LYRICS`` comment is replaced; other
    Vorbis comments are left untouched.

    Args:
        tags: an ID3 tag object or a Vorbis comment
        lyrics (TimedLyrics or list[(str, int)]): lines to store; if a
            plain list is given, ``language`` is used
        language (str): three letter language code for a plain line list

    Raises:
        LyricsError: on invalid lines, negative or out of range times,
            or an unsupported tag object
        ValueError: if ``lyrics`` contains no lines
    """

    lyrics = _coerce_lyrics(
        lyrics if isinstance(lyrics, TimedLyrics)
        else TimedLyrics(lyrics, language=language))
    if not lyrics:
        raise ValueError("refusing to store empty timed lyrics; use "
                         "delete_lyrics() to remove them")

    if tags is None:
        raise LyricsError(
            "the file has no tags; call add_tags() before storing lyrics")
    if _is_id3_tags(tags):
        frames = [frame for frame in tags.getall("SYLT")
                  if frame.format != _SYLT_FORMAT_MILLISECONDS
                  or frame.lang != lyrics.language]
        frames.append(_lyrics_to_sylt(lyrics))
        tags.setall("SYLT", frames)
    elif _is_vorbis_tags(tags):
        tags["LYRICS"] = serialize_lrc(lyrics)
    else:
        raise LyricsError(
            "unsupported tag object %r; expected ID3 tags or a Vorbis "
            "comment" % (type(tags),))


def delete_lyrics(tags, language=None):
    """Remove timed lyrics.

    Args:
        tags: an ID3 tag object or a Vorbis comment
        language (str): if given for ID3, only ``SYLT`` frames of that
            language are removed; otherwise all millisecond ``SYLT``
            frames are removed. Always removes the FLAC ``LYRICS`` field.
    """

    if tags is None:
        return
    if _is_id3_tags(tags):
        frames = []
        for frame in tags.getall("SYLT"):
            if frame.format != _SYLT_FORMAT_MILLISECONDS:
                frames.append(frame)
            elif language is not None and frame.lang != language:
                frames.append(frame)
        tags.setall("SYLT", frames)
    elif _is_vorbis_tags(tags):
        if "LYRICS" in tags:
            del tags["LYRICS"]
    else:
        raise LyricsError(
            "unsupported tag object %r; expected ID3 tags or a Vorbis "
            "comment" % (type(tags),))
