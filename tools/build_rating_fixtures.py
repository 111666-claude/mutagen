#!/usr/bin/env python3
"""Build the rating test fixtures.

These fixtures back the unified listener-rating tests in
``tests/test_rating.py``.  The script is kept (rather than only the
binary output) so the fixtures can be rebuilt and inspected::

    python3 tools/build_rating_fixtures.py

It writes:

* ``tests/data/rating-two-owners.mp3`` -- an MP3 whose ID3 tag carries
  POPM frames for two different owners plus a cover (APIC), a chapter
  (CHAP) and an unknown frame, all of which must survive rating edits.
* ``tests/data/rating-default-user.flac`` -- a FLAC whose Vorbis comment
  carries the default-user RATING/PLAYCOUNT alongside a cover picture,
  a seek table and an unknown metadata block.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture, MetadataBlock
from mutagen.id3 import ID3, TIT2, TPE1, POPM, APIC, CHAP, TIT3

DATA = os.path.join(ROOT, "tests", "data")

OWNER_A = u"alice@example.com"
OWNER_B = u"bob@example.com"

# 4 stars -> 204/255, 2 stars -> 102/255; play counts stay distinct.
RATING_A = 204
COUNT_A = 7
RATING_B = 102
COUNT_B = 42


def build_mp3(dest):
    src = os.path.join(DATA, "silence-44-s.mp3")
    shutil.copy(src, dest)
    audio = MP3(dest)

    audio.tags.add(TIT2(encoding=3, text=u"Rated Track"))
    audio.tags.add(TPE1(encoding=3, text=u"Rated Artist"))

    # Two POPM owners that must not overwrite each other.
    audio.tags.add(POPM(email=OWNER_A, rating=RATING_A, count=COUNT_A))
    audio.tags.add(POPM(email=OWNER_B, rating=RATING_B, count=COUNT_B))

    # Cover art that must survive a rating edit and re-save.
    audio.tags.add(APIC(
        encoding=3, mime=u"image/png", type=3, desc=u"Cover",
        data=b"\x89PNG\r\n\x1a\n" + b"cover-bytes"))

    # Chapter with a sub-frame.
    audio.tags.add(CHAP(
        element_id=u"chapter-1", start_time=0, end_time=1000,
        start_offset=0, end_offset=0,
        sub_frames=[TIT3(encoding=3, text=u"Chapter One")]))

    audio.save()

    # Inject a frame Mutagen doesn't know about, as raw bytes, to prove
    # unknown frames round trip.  XENO is not a registered ID3v2 frame.
    tags = ID3(dest)
    body = b"unknown-frame-payload"
    raw = b"XENO" + (len(body)).to_bytes(4, "big") + b"\x00\x00" + body
    tags.unknown_frames.append(raw)
    tags.save()


def build_flac(dest):
    src = os.path.join(DATA, "silence-44-s.flac")
    shutil.copy(src, dest)
    audio = FLAC(dest)
    if audio.tags is None:
        audio.add_tags()

    audio.tags[u"title"] = u"Rated Track"
    audio.tags[u"RATING"] = str(RATING_A)
    audio.tags[u"PLAYCOUNT"] = str(COUNT_A)

    # The source fixture already carries a seek table, a cue sheet and a
    # picture; add one more cover plus an unknown metadata block (code 7 is
    # not in FLAC.METADATA_BLOCKS) so both pictures and unknown blocks can
    # be checked for survival.
    picture = Picture()
    picture.type = 3
    picture.mime = u"image/png"
    picture.desc = u"Cover"
    picture.data = b"\x89PNG\r\n\x1a\n" + b"cover-bytes"
    audio.add_picture(picture)

    # Unknown metadata block (code 7 is not in FLAC.METADATA_BLOCKS).
    unknown = MetadataBlock(b"custom-application-block")
    unknown.code = 7
    audio.metadata_blocks.append(unknown)

    audio.save()


def main():
    mp3_dest = os.path.join(DATA, "rating-two-owners.mp3")
    flac_dest = os.path.join(DATA, "rating-default-user.flac")
    build_mp3(mp3_dest)
    build_flac(flac_dest)
    print("wrote", mp3_dest)
    print("wrote", flac_dest)


if __name__ == "__main__":
    main()
