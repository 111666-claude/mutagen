Synchronised Lyrics
===================

The :mod:`mutagen.lyrics` module gives one common model for line by
line, timestamped lyrics across MP3, FLAC and M4A files.  The native
tags differ:

* MP3/ID3 stores one ``SYLT`` frame per language, using millisecond
  time stamps.
* FLAC stores an LRC text block in the ``LYRICS`` Vorbis comment.
* M4A/MP4 stores an LRC text block in the ``\xa9lyr`` atom.

LRC blocks carry their language in a ``[la:CODE]`` metadata line, so a
single tag can hold several languages.

.. automodule:: mutagen.lyrics

Data model
----------

.. autoclass:: mutagen.lyrics.LyricLine()

.. autoclass:: mutagen.lyrics.Lyrics()

.. autoclass:: mutagen.lyrics.LyricsError

Reading and writing
-------------------

.. autofunction:: mutagen.lyrics.get_lyrics

.. autofunction:: mutagen.lyrics.set_lyrics

.. autofunction:: mutagen.lyrics.remove_lyrics

LRC text blocks
---------------

.. autofunction:: mutagen.lyrics.lyrics_to_lrc

.. autofunction:: mutagen.lyrics.lrc_to_lyrics

.. autodata:: mutagen.lyrics.LRC_LANGUAGE_PREFIX

.. autodata:: mutagen.lyrics.UNKNOWN_LANGUAGE
