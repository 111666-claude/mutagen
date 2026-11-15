===
MP4
===

There is no MPEG-4 iTunes metadata standard. Mutagen's features are
known to lead to problems in other implementations. For example, FAAD
will crash when reading a file with multiple "tmpo" atoms. iTunes
itself is our main compatibility target.


Compatibility / Bugs
^^^^^^^^^^^^^^^^^^^^

* Prior to 1.16, the MP4 cover atom used a .format attribute to indicate
  the image format (JPEG/PNG). Python 2.6 added a str.format method which
  conflicts with this. 1.17 provides .imageformat when running on any version,
  and still provides .format when running on a version before 2.6.


Chapters
^^^^^^^^

M4A/M4B files store chapters in the ``moov.udta.chpl`` atom. The same
:class:`mutagen.Chapter` based API as for MP3 files is available::

    from mutagen import Chapter
    from mutagen.mp4 import MP4

    audio = MP4("example.m4a")
    audio.set_chapters([
        Chapter(0, u"Intro"),
        Chapter(42000, u"Second chapter"),
    ])
    audio.save()

Each chapter start is given in milliseconds and has to be non negative and
strictly increasing. ``get_chapters`` returns the current list and
``clear_chapters`` removes the chapter atom. Editing chapters never touches
the iTunes tags (including cover art) or the audio payload.

The legacy ``audio.chapters`` sequence remains available and keeps using
seconds for the start times.
