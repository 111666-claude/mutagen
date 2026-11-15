"""A unified, timed-lyrics model on top of the format specific tags.

Music players need line ("karaoke") lyrics that move with the playback
position, but every container stores them differently:

* MP3/ID3 uses synchronised text frames (``SYLT``), one frame per
  language, with millisecond timestamps.
* FLAC has no dedicated lyrics tag, so an LRC text block is stored in
  the ``LYRICS`` Vorbis comment (one comment per language).
* M4A/MP4 has no dedicated lyrics tag, so the same LRC text block is
  stored in the ``'\\xa9lyr'`` atom (one atom value per language).

This module exposes one common model -- :class:`LyricLine` lines grouped
in a :class:`Lyrics` object carrying a language identifier -- and
read/write helpers that translate between the model and those native
tags.  Nothing here touches unrelated tags or embedded pictures.

LRC blocks written by this module mark their language with a
``[la:CODE]`` metadata line so several languages can share one tag.
Time stamps use the ``[mm:ss.xxx]`` form; multiple time stamps on one
line are read as several lyric lines.
"""

import re

from mutagen._util import MutagenError
from mutagen.id3 import ID3, SYLT, Encoding


__all__ = [
    "LyricsError", "LyricLine", "Lyrics",
    "get_lyrics", "set_lyrics", "remove_lyrics",
    "LRC_LANGUAGE_PREFIX",
]


#: Header line used inside an LRC block to record its ISO-639-2 language
#: code (e.g. ``[la:eng]``).
LRC_LANGUAGE_PREFIX = "la:"

#: Placeholder language used when a tag carries no language identifier.
UNKNOWN_LANGUAGE = "XXX"

# Timestamps in ID3 SYLT frames and (by choice of this module) in LRC
# blocks are 32 bit millisecond values.
_MAX_TIME_MS = 0xFFFFFFFF

# "[la:eng]" style language metadata.
_LANG_RE = re.compile(r"^\[la:([^\]]*)\]$")

# One LRC time stamp: [minutes:seconds.fraction].  Minutes and seconds
# are two zero padded digits; the fraction is three digits on writing
# and one to three digits on reading.
_TIME_RE = re.compile(r"^\[(\d+):(\d{2})(?:\.(\d{1,3}))?\]$")


class LyricsError(MutagenError):
    """Raised when lyrics cannot be represented or parsed.

    A malformed time stamp, a negative or out of range timestamp, an
    invalid language code or text that cannot be stored in the target
    format all raise this instead of silently dropping data.
    """


def _validate_language(lang):
    if not isinstance(lang, str):
        raise LyricsError("language must be a string, not %r" % type(lang))
    if len(lang) != 3 or not all("a" <= c <= "z" or "A" <= c <= "Z"
                                 for c in lang):
        raise LyricsError(
            "language %r must be a three letter ISO-639-2 code" % lang)
    return lang


def _validate_time(time):
    # bool is a subclass of int, reject it together with other non-ints.
    if not isinstance(time, int) or isinstance(time, bool):
        raise LyricsError("time must be an integer number of milliseconds, "
                          "not %r" % type(time))
    if time < 0:
        raise LyricsError("time must not be negative, got %d" % time)
    if time > _MAX_TIME_MS:
        raise LyricsError(
            "time %d ms cannot be represented in 32 bits (maximum %d ms)"
            % (time, _MAX_TIME_MS))
    return time


def _validate_text(text):
    if not isinstance(text, str):
        raise LyricsError("lyric text must be a string, not %r"
                          % type(text))
    if "\x00" in text:
        raise LyricsError("lyric text must not contain NUL characters")
    if "\n" in text or "\r" in text:
        raise LyricsError("a single lyric line must not contain line breaks")
    return text


class LyricLine(object):
    """LyricLine(time, text)

    One synchronised lyric line.

    Attributes:
        time (int): presentation time stamp in milliseconds, from the
            start of the track.  Must be between ``0`` and
            ``0xFFFFFFFF``.
        text (str): the text shown at :attr:`time`.  May be empty (for
            pure timing marks) but must not contain line breaks or NUL.
    """

    __slots__ = ("time", "text")

    def __init__(self, time, text=u""):
        self.time = _validate_time(time)
        self.text = _validate_text(text)

    def __eq__(self, other):
        if not isinstance(other, LyricLine):
            return NotImplemented
        return self.time == other.time and self.text == other.text

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other):
        if not isinstance(other, LyricLine):
            return NotImplemented
        return (self.time, self.text) < (other.time, other.text)

    def __hash__(self):
        return hash((self.time, self.text))

    def __repr__(self):
        return "LyricLine(%d, %r)" % (self.time, self.text)


class Lyrics(object):
    """Lyrics(lines=None, language='XXX')

    A set of synchronised lines for one language.

    Attributes:
        language (str): three letter ISO-639-2 code (for example
            ``"eng"``); ``"XXX"`` marks an unknown language.
        lines (list[LyricLine]): lyric lines in playback order.  Lines
            sharing one timestamp represent several rows shown at the
            same moment and keep their insertion order.
    """

    def __init__(self, lines=None, language=UNKNOWN_LANGUAGE):
        self.language = _validate_language(language)
        self.lines = []
        if lines is not None:
            for line in lines:
                if not isinstance(line, LyricLine):
                    raise LyricsError(
                        "lines must contain LyricLine instances, got %r"
                        % type(line))
                self.lines.append(line)

    def add(self, time, text=u""):
        """add(time, text)

        Append a :class:`LyricLine`, returning it for convenience.
        """

        line = LyricLine(time, text)
        self.lines.append(line)
        return line

    def __eq__(self, other):
        if not isinstance(other, Lyrics):
            return NotImplemented
        return (self.language == other.language
                and self.lines == other.lines)

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __iter__(self):
        return iter(self.lines)

    def __len__(self):
        return len(self.lines)

    def __repr__(self):
        return "Lyrics(language=%r, lines=%r)" % (self.language, self.lines)


# ----------------------------------------------------------------------
# LRC (FLAC "LYRICS" comment and M4A "\xa9lyr" atom)
# ----------------------------------------------------------------------

def _format_lrc_time(time):
    minutes, milliseconds = divmod(time, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return u"[%02d:%02d.%03d]" % (minutes, seconds, milliseconds)


def _parse_lrc_time(stamp):
    match = _TIME_RE.match(stamp)
    if match is None:
        raise LyricsError("invalid LRC time stamp %r" % stamp)
    minutes, seconds, fraction = match.groups()
    if int(seconds) >= 60:
        raise LyricsError("seconds out of range in time stamp %r" % stamp)
    milliseconds = int((fraction or "0").ljust(3, "0"))
    time = int(minutes) * 60000 + int(seconds) * 1000 + milliseconds
    if time > _MAX_TIME_MS:
        raise LyricsError("time stamp %r is out of range" % stamp)
    return time


def lyrics_to_lrc(lyrics):
    """lyrics_to_lrc(lyrics) -> str

    Serialise a :class:`Lyrics` object to an LRC text block.  The first
    line records the language (``[la:CODE]``) and every following line
    is a ``[mm:ss.xxx]`` time stamp plus the lyric text.
    """

    if not isinstance(lyrics, Lyrics):
        raise LyricsError("expected a Lyrics object, got %r" % type(lyrics))
    lines = [u"[" + LRC_LANGUAGE_PREFIX + lyrics.language + u"]"]
    for line in lyrics.lines:
        # Re-validate in case the object was mutated after construction.
        time = _validate_time(line.time)
        text = _validate_text(line.text)
        lines.append(_format_lrc_time(time) + text)
    return u"\n".join(lines)


def lrc_to_lyrics(block, default_language=UNKNOWN_LANGUAGE):
    """lrc_to_lyrics(block, default_language='XXX') -> Lyrics or None

    Parse an LRC text block.  Blocks without any time stamps (for
    example plain, unsynchronised lyrics) return ``None``.

    A ``[la:CODE]`` line sets the language; :data:`UNKNOWN_LANGUAGE` is
    used when the block has no such line.  Lines with several time
    stamps expand to one :class:`LyricLine` per stamp.
    """

    if not isinstance(block, str):
        raise LyricsError("LRC block must be a string, got %r"
                          % type(block))

    language = _validate_language(default_language)
    lines = []
    saw_timestamp = False

    for raw in block.split("\n"):
        line = raw.rstrip("\r")
        if not line:
            continue

        lang_match = _LANG_RE.match(line)
        if lang_match is not None:
            language = _validate_language(lang_match.group(1))
            continue

        # Collect every leading "[...]" token; only real time stamps
        # consume the line.
        stamps = []
        rest = line
        while rest.startswith("["):
            end = rest.find("]")
            if end < 0:
                # A line that starts a tag but never closes it is broken.
                raise LyricsError("malformed LRC tag in line %r" % raw)
            token = rest[:end + 1]
            if _TIME_RE.match(token) is None:
                # A "[<digits>:<digits>...]" shaped token that did not
                # parse is a malformed time stamp; other bracketed tags
                # ([ar:...], [ti:...]) are plain metadata.
                inside = token[1:-1]
                head = inside.split(":", 1)[0]
                if head.isdigit() and ":" in inside and \
                        inside.split(":", 1)[1][:1].isdigit():
                    raise LyricsError(
                        "invalid LRC time stamp in line %r" % raw)
                # Unknown metadata tags stop time stamp collection; the
                # remainder is lyric text.
                break
            stamps.append(_parse_lrc_time(token))
            saw_timestamp = True
            rest = rest[end + 1:]

        if not stamps:
            # Metadata or plain, unsynchronised text lines are ignored.
            continue

        text = _validate_text(rest)
        for time in stamps:
            lines.append(LyricLine(time, text))

    if not saw_timestamp:
        return None
    return Lyrics(lines, language=language)


# ----------------------------------------------------------------------
# ID3 SYLT (MP3)
# ----------------------------------------------------------------------

def _sylt_to_lyrics(frame):
    if frame.format != 2:
        raise LyricsError(
            "SYLT frame uses time stamp format %d; only millisecond "
            "format (2) is supported" % frame.format)
    lines = []
    for text, time in frame.text:
        # The ID3 layer hands back (unicode, int) pairs; guard against
        # hand built frames with bad values.
        lines.append(LyricLine(_validate_time(int(time)),
                               _validate_text(text)))
    return Lyrics(lines, language=frame.lang or UNKNOWN_LANGUAGE)


def _lyrics_to_sylt(lyrics, desc=u""):
    if not isinstance(desc, str):
        raise LyricsError("SYLT description must be a string")
    if "\x00" in desc:
        raise LyricsError("SYLT description must not contain NUL characters")
    pairs = []
    for line in lyrics.lines:
        time = _validate_time(line.time)
        text = _validate_text(line.text)
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as err:
            raise LyricsError("text cannot be encoded as UTF-8: %s" % err)
        pairs.append((text, time))
    return SYLT(encoding=Encoding.UTF8, lang=lyrics.language,
                format=2, type=1, desc=desc, text=pairs)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def get_lyrics(tags, language=None):
    """get_lyrics(tags, language=None) -> list[Lyrics]

    Read synchronised lyrics from an :class:`~mutagen.id3.ID3`,
    :class:`~mutagen.flac.FLAC`/Vorbis comment or
    :class:`~mutagen.mp4.MP4Tags` tag object.

    If ``language`` is given only lyrics carrying that three letter code
    are returned; otherwise every language is returned.  Files without
    synchronised lyrics (including files without a tag block) return an
    empty list -- never an error.
    """

    if language is not None:
        language = _validate_language(language)

    if tags is None:
        # A file whose container carries no tag block at all.
        return []

    if isinstance(tags, ID3):
        result = []
        for frame in tags.getall("SYLT"):
            lyrics = _sylt_to_lyrics(frame)
            if language is None or lyrics.language == language:
                result.append(lyrics)
        return result

    # FLAC Vorbis comments and the generic VComment dict expose LYRICS.
    if _is_vorbis_comment(tags):
        result = []
        for block in tags.get("LYRICS", []):
            lyrics = lrc_to_lyrics(block)
            if lyrics is None:
                continue
            if language is None or lyrics.language == language:
                result.append(lyrics)
        return result

    # MP4 tags expose the '\xa9lyr' atom.
    if _is_mp4_tags(tags):
        result = []
        for block in tags.get("\xa9lyr", []):
            lyrics = lrc_to_lyrics(block)
            if lyrics is None:
                continue
            if language is None or lyrics.language == language:
                result.append(lyrics)
        return result

    raise TypeError("unsupported tag object %r" % type(tags))


def set_lyrics(tags, lyrics):
    """set_lyrics(tags, lyrics)

    Store one :class:`Lyrics` object, replacing any existing
    synchronised lyrics for the same language while leaving other
    languages, pictures and unrelated tags untouched.  The tag object is
    mutated in place; the caller is responsible for saving the file.
    """

    if not isinstance(lyrics, Lyrics):
        raise LyricsError("expected a Lyrics object, got %r" % type(lyrics))
    if not lyrics.lines:
        raise LyricsError(
            "cannot store lyrics for %r without any lines" % lyrics.language)
    # Validate every line up front so nothing is half written.
    for line in lyrics.lines:
        _validate_time(line.time)
        _validate_text(line.text)
    _validate_language(lyrics.language)

    if isinstance(tags, ID3):
        _set_id3_lyrics(tags, lyrics)
    elif _is_vorbis_comment(tags):
        _set_lrc_blocks(tags, "LYRICS", lyrics)
    elif _is_mp4_tags(tags):
        _set_lrc_blocks(tags, "\xa9lyr", lyrics)
    else:
        raise TypeError("unsupported tag object %r" % type(tags))


def remove_lyrics(tags, language=None):
    """remove_lyrics(tags, language=None) -> int

    Remove synchronised lyrics.  With ``language`` set only that
    language is removed; without it every synchronised lyric tag is
    removed.  Unrelated tags and pictures are never touched.  Returns
    the number of lyric blocks (languages) removed.
    """

    if language is not None:
        language = _validate_language(language)

    if isinstance(tags, ID3):
        return _remove_id3_lyrics(tags, language)
    if _is_vorbis_comment(tags):
        return _remove_lrc_blocks(tags, "LYRICS", language)
    if _is_mp4_tags(tags):
        return _remove_lrc_blocks(tags, "\xa9lyr", language)
    raise TypeError("unsupported tag object %r" % type(tags))


def _set_id3_lyrics(tags, lyrics):
    # Replace the SYLT frame for this language, keep every other one.
    kept = [frame for frame in tags.getall("SYLT")
            if (frame.lang or UNKNOWN_LANGUAGE) != lyrics.language]
    tags.delall("SYLT")
    for frame in kept:
        tags.add(frame)
    tags.add(_lyrics_to_sylt(lyrics))


def _remove_id3_lyrics(tags, language):
    frames = tags.getall("SYLT")
    if language is None:
        removed = len(frames)
        tags.delall("SYLT")
        return removed
    kept = [frame for frame in frames
            if (frame.lang or UNKNOWN_LANGUAGE) != language]
    removed = len(frames) - len(kept)
    if removed:
        tags.delall("SYLT")
        for frame in kept:
            tags.add(frame)
    return removed


def _set_lrc_blocks(tags, key, lyrics):
    # Both Vorbis comments (FLAC) and MP4 tags store a list of text
    # values per key; each value is one language's LRC block.
    block = lyrics_to_lrc(lyrics)
    kept = []
    replaced = False
    for value in tags.get(key, []):
        old = lrc_to_lyrics(value)
        if old is not None and old.language == lyrics.language:
            if not replaced:
                kept.append(block)
                replaced = True
            # further blocks of the same language collapse into one
        else:
            # Keep non-LRC values (e.g. plain unsynchronised lyrics).
            kept.append(value)
    if not replaced:
        kept.append(block)
    tags[key] = kept


def _remove_lrc_blocks(tags, key, language):
    kept = []
    removed = 0
    for value in tags.get(key, []):
        old = lrc_to_lyrics(value)
        if old is None:
            kept.append(value)
        elif language is None or old.language == language:
            removed += 1
        else:
            kept.append(value)
    if removed:
        if kept:
            tags[key] = kept
        else:
            del tags[key]
    return removed


def _is_vorbis_comment(tags):
    from mutagen._vorbis import VCommentDict
    return isinstance(tags, VCommentDict)


def _is_mp4_tags(tags):
    from mutagen.mp4 import MP4Tags
    return isinstance(tags, MP4Tags)
