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


Microsoft Xtra metadata
^^^^^^^^^^^^^^^^^^^^^^^

Windows (Windows Media Player, Explorer) stores some metadata, for example
the director of a video or a user rating, in the ``moov.udta.Xtra`` atom
rather than in the iTunes ``ilst`` tags. Mutagen reads this atom and
exposes it read-only through :attr:`MP4.xtra`::

    from mutagen.mp4 import MP4

    audio = MP4("example.m4a")
    if audio.xtra is not None:
        print(audio.xtra["WM/Director"])
        print(audio.xtra["WM/SharedUserRating"])

The keys are the Microsoft attribute names exactly as they are stored in
the file, so they are kept separate from the regular :attr:`MP4.tags`
keys. Each value is a list, because attributes can have multiple values.
Text values are returned as `str`, integer values as `int`.

The Xtra view is read-only and is never written back when saving the
regular tags, so both kinds of metadata can coexist in a file. Values
parsed before a malformed record are still available and
:attr:`MP4Xtra.error` describes the problem; a broken or missing Xtra
atom never hides the regular tags.
