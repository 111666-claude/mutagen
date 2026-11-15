Synchronised Lyrics
===================

:mod:`mutagen.lyrics` provides one model for timestamped ("karaoke")
lyrics no matter whether the file is MP3, FLAC or M4A.  A lyric line
has a millisecond time stamp and text, and a set of lines carries a
three letter ISO-639-2 language identifier.

Building lyrics
---------------

.. code-block:: python

    from mutagen.lyrics import Lyrics

    lyrics = Lyrics(language="eng")
    lyrics.add(0, "First line")
    lyrics.add(1500, "Second line")
    lyrics.add(1500, "Another row shown at the same moment")
    lyrics.add(42000, "")  # a timing mark without text

Timestamps are integer milliseconds between ``0`` and ``0xFFFFFFFF``.
Negative, fractional or out of range values raise
:class:`mutagen.lyrics.LyricsError` immediately; nothing is silently
dropped.

Writing and reading back
------------------------

The same calls work for every supported format; only the native tag
differs (``SYLT`` for MP3, a ``LYRICS`` LRC comment for FLAC and a
``\xa9lyr`` LRC atom for M4A).

.. code-block:: python

    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.lyrics import get_lyrics, set_lyrics

    audio = MP3("song.mp3")          # or FLAC(...), MP4(...)
    if audio.tags is None:
        audio.add_tags()
    set_lyrics(audio.tags, lyrics)
    audio.save()

    reread = MP3("song.mp3")
    assert get_lyrics(reread.tags, "eng") == [lyrics]

``get_lyrics`` always returns a list -- an empty list means the file
has no synchronised lyrics (or no tag block at all).

Several languages
-----------------

Store one :class:`~mutagen.lyrics.Lyrics` object per language.
Replacing or removing one language never touches the others, embedded
pictures or unrelated tags.

.. code-block:: python

    from mutagen.lyrics import remove_lyrics

    set_lyrics(audio.tags, english)
    set_lyrics(audio.tags, japanese)

    all_languages = get_lyrics(audio.tags)
    only_english = get_lyrics(audio.tags, language="eng")

    remove_lyrics(audio.tags, language="jpn")  # one language
    remove_lyrics(audio.tags)                  # every language
    audio.save()

LRC text
--------

FLAC and M4A store lyrics as LRC text.  The conversion helpers are
public so blocks can be inspected or exchanged with other software:

.. code-block:: python

    from mutagen.lyrics import lyrics_to_lrc, lrc_to_lyrics

    block = lyrics_to_lrc(lyrics)
    # [la:eng]
    # [00:00.000]First line
    # [00:01.500]Second line

    assert lrc_to_lyrics(block) == lyrics

Plain, unsynchronised text in the same tag is left untouched and simply
not returned by ``get_lyrics``.
