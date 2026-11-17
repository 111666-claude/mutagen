.. _rating:

Unified Listener Ratings
========================

.. automodule:: mutagen.rating
    :noindex:

The 0-5 star rating and the 0-255 wire value map linearly. All six
integer star values round trip exactly::

    0, 1, 2, 3, 4, 5 stars -> 0, 51, 102, 153, 204, 255 -> same stars

Rating edits only touch the POPM frame (ID3) or the two comment keys
(FLAC) they own; cover art, chapters, cue sheets, seek tables, other
comments and unknown frames are all preserved. Repeatedly saving the
same values produces a byte-identical tag. Changes are made to the
in-memory object, so call :meth:`save` on the file afterwards.

Example
-------

.. code-block:: python

    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.rating import get_rating, set_rating, get_play_count, \
        set_play_count

    mp3 = MP3("album/01-song.mp3")
    flac = FLAC("album-flac/01-song.flac")

    # Copy a personal rating from the MP3 (owner "alice@example.com") to
    # the FLAC default user and save both.
    set_rating(flac, get_rating(mp3, "alice@example.com"))
    set_play_count(flac, get_play_count(mp3, "alice@example.com"))
    flac.save()

Reference
---------

.. autoclass:: mutagen.rating.RatingError
    :show-inheritance:

.. autodata:: mutagen.rating.DEFAULT_OWNER

.. autodata:: mutagen.rating.MIN_RATING
.. autodata:: mutagen.rating.MAX_RATING
.. autodata:: mutagen.rating.MIN_WIRE_RATING
.. autodata:: mutagen.rating.MAX_WIRE_RATING

.. autofunction:: mutagen.rating.stars_to_rating
.. autofunction:: mutagen.rating.rating_to_stars
.. autofunction:: mutagen.rating.get_rating
.. autofunction:: mutagen.rating.set_rating
.. autofunction:: mutagen.rating.get_play_count
.. autofunction:: mutagen.rating.set_play_count
.. autofunction:: mutagen.rating.delete_rating
