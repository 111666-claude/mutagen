# Copyright (C) 2026  Mutagen Authors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Reading and writing chapter lists on top of ID3v2 CHAP/CTOC frames.

The ID3v2 table of contents frame (``CTOC``) references a list of chapter
frames (``CHAP``), one per chapter. Each chapter frame carries its start
time in milliseconds and a ``TIT2`` sub frame holding the title.
"""

from mutagen._chapters import Chapter as Chapter

from ._frames import CHAP, CTOC, TIT2
from ._specs import CTOCFlags
from ._util import error

__all__ = ["Chapter", "ChapterError", "get_chapters", "set_chapters",
           "delete_chapters", "validate_chapters", "MAX_CHAPTERS",
           "MAX_CHAPTER_START_MS"]

#: ID of the CTOC frame that owns the chapter list managed here.
TOC_ELEMENT_ID = "toc"

#: Prefix of the generated CHAP element ids.
CHAPTER_ELEMENT_ID = "chp"

#: A CHAP/CTOC element id is a latin-1 terminated string, so it can hold at
#: most 255 bytes.
MAX_ELEMENT_ID_BYTES = 255

#: Start and end times of a CHAP frame are unsigned 32 bit values measured
#: in milliseconds.
MAX_CHAPTER_START_MS = 0xFFFFFFFF

#: With generated element ids this many chapters keep every element id
#: encodable as latin-1 and every CHAP frame below the 32 bit frame size
#: limit for any reasonable title.
MAX_CHAPTERS = 10 ** 6 - 1


class ChapterError(error, ValueError):
    """Raised when a chapter list can't be represented in an ID3 tag."""


def validate_chapters(chapters):
    """Validate a chapter list.

    Args:
        chapters (list[Chapter]): chapters in playback order
    Raises:
        ChapterError: if the list can't be written
    """

    if not isinstance(chapters, (list, tuple)):
        raise ChapterError("chapters must be a list of Chapter")

    previous = None
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, Chapter):
            raise ChapterError(
                "chapter %d is not a Chapter instance" % index)

        start = chapter.start
        if isinstance(start, bool) or not isinstance(start, int):
            raise ChapterError(
                "chapter %d start must be an int number of milliseconds"
                % index)
        if start < 0:
            raise ChapterError(
                "chapter %d has a negative start time" % index)
        if start > MAX_CHAPTER_START_MS:
            raise ChapterError(
                "chapter %d start time %d exceeds the %d ms limit of "
                "ID3 chapter frames" %
                (index, start, MAX_CHAPTER_START_MS))
        if previous is not None and start <= previous:
            raise ChapterError(
                "chapter %d starts at %d ms, which is not after the "
                "previous chapter (%d ms)" % (index, start, previous))
        previous = start

        if not isinstance(chapter.title, str):
            raise ChapterError(
                "chapter %d title must be str" % index)
        try:
            chapter.title.encode("utf-8")
        except UnicodeEncodeError as e:
            raise ChapterError(
                "chapter %d title can't be encoded: %s" % (index, e))

    if len(chapters) > MAX_CHAPTERS:
        raise ChapterError(
            "at most %d chapters are supported, got %d" %
            (MAX_CHAPTERS, len(chapters)))


def _element_id(index):
    element_id = "%s%d" % (CHAPTER_ELEMENT_ID, index + 1)
    if len(element_id.encode("latin-1")) > MAX_ELEMENT_ID_BYTES:
        raise ChapterError(
            "chapter element id %r exceeds %d bytes" %
            (element_id, MAX_ELEMENT_ID_BYTES))
    return element_id


def get_chapters(id3):
    """Return the chapters of an ID3 tag as a list of Chapter.

    Chapters are returned in the order given by the top level CTOC frame.
    CHAP frames not referenced by such a CTOC are returned afterwards
    sorted by their element id. Returns an empty list if the tag has no
    chapters.
    """

    ordered_ids = []
    for ctoc in id3.getall("CTOC"):
        if int(ctoc.flags) & CTOCFlags.TOP_LEVEL:
            ordered_ids = list(ctoc.child_element_ids)
            break

    result = []
    seen = set()
    for element_id in ordered_ids:
        frames = id3.getall("CHAP:" + element_id)
        if frames:
            result.append(_frame_to_chapter(frames[0]))
            seen.add(element_id)

    leftovers = sorted(
        (f for f in id3.getall("CHAP") if f.element_id not in seen),
        key=lambda f: f.element_id)
    result.extend(_frame_to_chapter(f) for f in leftovers)
    return result


def _frame_to_chapter(frame):
    title = u""
    tit2 = frame.sub_frames.getall("TIT2")
    if tit2:
        title = u"\x00".join(tit2[0].text)
    return Chapter(int(frame.start_time), title)


def set_chapters(id3, chapters):
    """Replace all chapters in an ID3 tag.

    Only CHAP and CTOC frames are touched; all other frames (including
    cover art) and the audio payload remain unchanged.

    Args:
        id3 (mutagen.id3.ID3): the tag to modify
        chapters (list[Chapter]): new chapters in playback order
    Raises:
        ChapterError: if the chapter list can't be written
    """

    chapters = list(chapters)
    validate_chapters(chapters)

    delete_chapters(id3)

    if not chapters:
        return

    element_ids = []
    last_index = len(chapters) - 1
    for index, chapter in enumerate(chapters):
        element_id = _element_id(index)
        element_ids.append(element_id)
        if index == last_index:
            # No following chapter, so the end time is unknown.
            end_time = MAX_CHAPTER_START_MS
        else:
            end_time = chapters[index + 1].start
        id3.add(CHAP(
            element_id=element_id,
            start_time=chapter.start,
            end_time=end_time,
            start_offset=0xFFFFFFFF,
            end_offset=0xFFFFFFFF,
            sub_frames=[TIT2(encoding=3, text=chapter.title)]))

    id3.add(CTOC(
        element_id=TOC_ELEMENT_ID,
        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids=element_ids,
        sub_frames=[]))


def delete_chapters(id3):
    """Remove every CHAP and CTOC frame from an ID3 tag."""

    id3.delall("CHAP")
    id3.delall("CTOC")
