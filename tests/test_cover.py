# Copyright (C) 2026  Mutagen Authors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import struct
import zlib

from tests import TestCase, DATA_DIR, get_temp_copy

import mutagen
from mutagen import File
from mutagen.cover import (
    CoverArt, CoverError, InvalidImageError,
    UnsupportedCoverFormatError, get_front_cover, set_front_cover,
    remove_front_cover)
from mutagen.id3 import ID3, APIC, PictureType
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover, AtomDataType
from mutagen.oggvorbis import OggVorbis


def _png_bytes():
    """A minimal valid 1x1 RGB PNG."""

    def chunk(typ, data):
        body = typ + data
        return (struct.pack(">I", len(data)) + body +
                struct.pack(">I", zlib.crc32(body)))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b""))


JPEG_DATA = open(os.path.join(DATA_DIR, "image.jpg"), "rb").read()
PNG_DATA = _png_bytes()
# Distinct payloads so surviving pictures can be told apart from the
# removed front cover after a round trip.
BACK_PNG_DATA = PNG_DATA + b"back-cover-marker"
LEAFLET_JPEG_DATA = JPEG_DATA + b"leaflet-marker"
GIF_DATA = b"GIF89a\x01\x00\x01\x00\x00\x00\x00," + b"\x00" * 10
GARBAGE = b"\x00\x01\x02not an image"


class TCoverArt(TestCase):

    def test_attributes_and_mime(self):
        art = CoverArt(JPEG_DATA, CoverArt.JPEG)
        self.assertEqual(art.data, JPEG_DATA)
        self.assertEqual(art.image_type, "jpeg")
        self.assertEqual(art.mime, "image/jpeg")

        art = CoverArt(PNG_DATA, CoverArt.PNG)
        self.assertEqual(art.mime, "image/png")

    def test_equality_and_hash(self):
        self.assertEqual(CoverArt(JPEG_DATA, "jpeg"),
                         CoverArt(JPEG_DATA, "jpeg"))
        self.assertNotEqual(CoverArt(JPEG_DATA, "jpeg"),
                            CoverArt(PNG_DATA, "png"))
        self.assertEqual(
            hash(CoverArt(JPEG_DATA, "jpeg")),
            hash(CoverArt(JPEG_DATA, "jpeg")))

    def test_invalid_construction(self):
        self.assertRaises(TypeError, CoverArt, u"not bytes", "jpeg")
        self.assertRaises(ValueError, CoverArt, JPEG_DATA, "gif")

    def test_repr(self):
        self.assertTrue("jpeg" in repr(CoverArt(JPEG_DATA, "jpeg")))


class _CoverRoundTripMixin(object):
    """Shared behavior exercised on real MP3, FLAC and M4A samples."""

    def setUp(self):
        self.tagged = get_temp_copy(
            os.path.join(DATA_DIR, self.TAGGED_SAMPLE))
        self.untagged = get_temp_copy(
            os.path.join(DATA_DIR, self.UNTAGGED_SAMPLE))

    def open(self, path):
        return File(path)

    def test_tagged_sample_starts_without_front_cover(self):
        # The shared round-trip tests assume the "tagged" sample carries
        # text tags but no front cover of its own.
        self.assertIsNone(get_front_cover(self.open(self.tagged)))

    # -- requirement 1: read type/bytes and replace round-trip -------------

    def test_set_then_get_roundtrip_jpeg(self):
        audio = self.open(self.tagged)
        self.assertIsNone(get_front_cover(audio))
        set_front_cover(audio, JPEG_DATA)
        audio.save()

        reopened = self.open(self.tagged)
        cover = get_front_cover(reopened)
        self.assertIsInstance(cover, CoverArt)
        self.assertEqual(cover.data, JPEG_DATA)
        self.assertEqual(cover.image_type, CoverArt.JPEG)
        self.assertEqual(cover.mime, "image/jpeg")

    def test_set_then_get_roundtrip_png(self):
        audio = self.open(self.untagged)
        self.assertIsNone(get_front_cover(audio))
        set_front_cover(audio, PNG_DATA, CoverArt.PNG)
        audio.save()

        reopened = self.open(self.untagged)
        cover = get_front_cover(reopened)
        self.assertEqual(cover.data, PNG_DATA)
        self.assertEqual(cover.image_type, CoverArt.PNG)
        self.assertEqual(cover.mime, "image/png")

    def test_type_is_sniffed_not_trusted(self):
        audio = self.open(self.untagged)
        # No image_type given: magic bytes decide.
        set_front_cover(audio, PNG_DATA)
        audio.save()
        self.assertEqual(
            get_front_cover(self.open(self.untagged)).image_type, "png")

    def test_replace_keeps_single_front_cover(self):
        audio = self.open(self.untagged)
        set_front_cover(audio, JPEG_DATA)
        audio.save()
        audio = self.open(self.untagged)
        set_front_cover(audio, PNG_DATA)
        audio.save()

        cover = get_front_cover(self.open(self.untagged))
        self.assertEqual(cover.data, PNG_DATA)
        self.assertEqual(cover.image_type, "png")
        self.assertEqual(self.front_cover_count(self.untagged), 1)

    # -- requirement 2: removal preserves everything else -----------------

    def test_remove_keeps_back_cover_other_pictures_and_tags(self):
        audio = self.open(self.tagged)
        tags_before = self.snapshot_other_tags(audio)
        set_front_cover(audio, JPEG_DATA)
        self.add_back_cover(audio, BACK_PNG_DATA)
        self.add_other_picture(audio, LEAFLET_JPEG_DATA)
        audio.save()

        audio = self.open(self.tagged)
        self.assertTrue(remove_front_cover(audio))
        audio.save()

        reopened = self.open(self.tagged)
        self.assertIsNone(get_front_cover(reopened))
        self.assert_back_cover_intact(reopened, BACK_PNG_DATA)
        self.assert_other_picture_intact(reopened, LEAFLET_JPEG_DATA)
        # Every pre-existing, unrelated tag survives the cover removal.
        after_tags = self.snapshot_other_tags(reopened)
        for key, value in tags_before.items():
            self.assertEqual(after_tags[key], value)

    def test_remove_without_cover_returns_false_and_changes_nothing(self):
        audio = self.open(self.tagged)
        tags_before = self.snapshot_other_tags(audio)
        self.assertFalse(remove_front_cover(audio))
        audio.save()

        reopened = self.open(self.tagged)
        self.assertIsNone(get_front_cover(reopened))
        self.assertEqual(self.snapshot_other_tags(reopened), tags_before)

    def test_remove_on_tagless_file_creates_no_tags(self):
        audio = self.open(self.untagged)
        self.assertIsNone(audio.tags)
        self.assertFalse(remove_front_cover(audio))
        self.assertIsNone(audio.tags)

    # -- requirement 3: explicit error/result cases ------------------------

    def test_missing_cover_returns_none(self):
        self.assertIsNone(get_front_cover(self.open(self.tagged)))
        self.assertIsNone(get_front_cover(self.open(self.untagged)))

    def test_tagless_set_then_read(self):
        audio = self.open(self.untagged)
        set_front_cover(audio, JPEG_DATA)
        audio.save()
        cover = get_front_cover(self.open(self.untagged))
        self.assertEqual(cover.data, JPEG_DATA)

    def test_invalid_images_rejected(self):
        audio = self.open(self.untagged)
        for bad in (b"", GARBAGE, GIF_DATA):
            self.assertRaises(
                InvalidImageError, set_front_cover, audio, bad)

    def test_non_bytes_rejected(self):
        audio = self.open(self.untagged)
        self.assertRaises(
            InvalidImageError, set_front_cover, audio, u"x" * 10)

    def test_explicit_image_type_mismatch_rejected(self):
        audio = self.open(self.untagged)
        self.assertRaises(
            InvalidImageError, set_front_cover, audio, JPEG_DATA, "png")
        self.assertRaises(
            InvalidImageError, set_front_cover, audio, PNG_DATA, "jpeg")

    def test_unsupported_image_type_rejected(self):
        audio = self.open(self.untagged)
        self.assertRaises(
            InvalidImageError, set_front_cover, audio, JPEG_DATA, "gif")

    # -- helpers, overridden per format ------------------------------------

    def front_cover_count(self, path):
        raise NotImplementedError

    def snapshot_other_tags(self, audio):
        raise NotImplementedError

    def add_back_cover(self, audio, data):
        raise NotImplementedError

    def add_other_picture(self, audio, data):
        raise NotImplementedError

    def assert_back_cover_intact(self, audio, data):
        raise NotImplementedError

    def assert_other_picture_intact(self, audio, data):
        raise NotImplementedError


class TMp3Cover(_CoverRoundTripMixin, TestCase):

    TAGGED_SAMPLE = "silence-44-s.mp3"
    UNTAGGED_SAMPLE = "no-tags.mp3"

    def front_cover_count(self, path):
        return sum(
            1 for frame in ID3(path).getall("APIC")
            if int(frame.type) == PictureType.COVER_FRONT)

    def snapshot_other_tags(self, audio):
        # Frames are re-rendered/reordered on save; compare the text
        # payload per frame ID rather than frame objects. APIC frames use
        # "APIC:desc" dictionary keys, so filter on the FrameID.
        result = {}
        for key in audio.tags.keys():
            if key.startswith("APIC"):
                continue
            values = []
            for frame in audio.tags.getall(key):
                text = getattr(frame, "text", None)
                values.append(
                    tuple(text) if text is not None else str(frame))
            result[key] = sorted(values)
        return result

    def add_back_cover(self, audio, data):
        audio.tags.add(APIC(
            encoding=3, mime="image/png",
            type=PictureType.COVER_BACK, desc=u"back", data=data))

    def add_other_picture(self, audio, data):
        audio.tags.add(APIC(
            encoding=3, mime="image/gif",
            type=PictureType.LEAFLET_PAGE, desc=u"leaflet", data=data))
        # An unrelated, non-picture frame as well.
        audio.tags.add(mutagen.id3.TCOM(encoding=3, text=[u"Composer X"]))

    def assert_back_cover_intact(self, audio, data):
        backs = [f for f in audio.tags.getall("APIC")
                 if int(f.type) == PictureType.COVER_BACK]
        self.assertEqual(len(backs), 1)
        self.assertEqual(backs[0].data, data)

    def assert_other_picture_intact(self, audio, data):
        leaflets = [f for f in audio.tags.getall("APIC")
                    if int(f.type) == PictureType.LEAFLET_PAGE]
        self.assertEqual(len(leaflets), 1)
        self.assertEqual(leaflets[0].data, data)
        self.assertEqual(audio.tags["TCOM"].text, [u"Composer X"])

    def test_native_apic_frame_is_well_formed(self):
        # Requirement 4: native format-specific API compatibility.
        audio = self.open(self.untagged)
        set_front_cover(audio, JPEG_DATA)
        audio.save()

        tags = ID3(self.untagged)
        apics = tags.getall("APIC")
        self.assertEqual(len(apics), 1)
        frame = apics[0]
        self.assertEqual(int(frame.type), PictureType.COVER_FRONT)
        self.assertEqual(frame.mime, "image/jpeg")
        self.assertEqual(frame.data, JPEG_DATA)

        # The native API can still read and delete it directly.
        self.assertEqual(get_front_cover(File(self.untagged)).data,
                         JPEG_DATA)
        tags.delall("APIC")
        tags.save()
        self.assertIsNone(get_front_cover(File(self.untagged)))

    def test_native_apic_added_first_is_discovered(self):
        tags = ID3()
        tags.add(APIC(encoding=3, mime="image/jpeg",
                      type=PictureType.COVER_FRONT, desc=u"",
                      data=JPEG_DATA))
        tags.save(self.untagged)
        self.assertEqual(
            get_front_cover(File(self.untagged)).data, JPEG_DATA)


class TFlacCover(_CoverRoundTripMixin, TestCase):

    TAGGED_SAMPLE = "silence-44-s.flac"
    UNTAGGED_SAMPLE = "no-tags.flac"

    def setUp(self):
        super(TFlacCover, self).setUp()
        # The shipped tagged FLAC already contains a front PNG cover;
        # remove it so the shared tests start from a cover-free baseline.
        flac = FLAC(self.tagged)
        flac.metadata_blocks[:] = [
            block for block in flac.metadata_blocks
            if not (block.code == Picture.code and
                    int(block.type) == PictureType.COVER_FRONT)
        ]
        flac.save()

    def front_cover_count(self, path):
        return sum(
            1 for picture in FLAC(path).pictures
            if int(picture.type) == PictureType.COVER_FRONT)

    def snapshot_other_tags(self, audio):
        return dict(audio.tags) if audio.tags is not None else {}

    def _picture(self, picture_type, mime, data, desc=u""):
        picture = Picture()
        picture.type = picture_type
        picture.mime = mime
        picture.desc = desc
        picture.data = data
        return picture

    def add_back_cover(self, audio, data):
        audio.add_picture(self._picture(
            PictureType.COVER_BACK, "image/png", data, u"back"))

    def add_other_picture(self, audio, data):
        audio.add_picture(self._picture(
            PictureType.LEAFLET_PAGE, "image/gif", data, u"leaflet"))
        audio.tags["composer"] = u"Composer X"

    def assert_back_cover_intact(self, audio, data):
        backs = [p for p in audio.pictures
                 if int(p.type) == PictureType.COVER_BACK]
        self.assertEqual(len(backs), 1)
        self.assertEqual(backs[0].data, data)

    def assert_other_picture_intact(self, audio, data):
        leaflets = [p for p in audio.pictures
                    if int(p.type) == PictureType.LEAFLET_PAGE]
        self.assertEqual(len(leaflets), 1)
        self.assertEqual(leaflets[0].data, data)
        self.assertEqual(audio.tags["composer"], [u"Composer X"])

    def test_native_picture_block_is_well_formed(self):
        audio = self.open(self.untagged)
        set_front_cover(audio, PNG_DATA)
        audio.save()

        flac = FLAC(self.untagged)
        self.assertEqual(len(flac.pictures), 1)
        picture = flac.pictures[0]
        self.assertEqual(int(picture.type), PictureType.COVER_FRONT)
        self.assertEqual(picture.mime, "image/png")
        self.assertEqual(picture.data, PNG_DATA)

        # Native API round trip: clear_pictures / add_picture still work.
        flac.clear_pictures()
        flac.save()
        self.assertIsNone(get_front_cover(FLAC(self.untagged)))

    def test_native_picture_added_first_is_discovered(self):
        flac = FLAC(self.untagged)
        flac.add_picture(self._picture(
            PictureType.COVER_FRONT, "image/jpeg", JPEG_DATA))
        flac.save()
        self.assertEqual(
            get_front_cover(FLAC(self.untagged)).data, JPEG_DATA)


class TM4aCover(_CoverRoundTripMixin, TestCase):

    TAGGED_SAMPLE = "has-tags.m4a"
    UNTAGGED_SAMPLE = "no-tags.m4a"

    def setUp(self):
        super(TM4aCover, self).setUp()
        # The shipped tagged M4A already contains two covr entries; drop
        # them so the shared tests start from a cover-free baseline while
        # keeping the text tags in place.
        mp4 = MP4(self.tagged)
        del mp4.tags["covr"]
        mp4.save()

    def test_remove_keeps_back_cover_other_pictures_and_tags(self):
        # M4A covr entries carry no picture type: removing the main entry
        # promotes the next one, so "back" and "other" are verified by
        # payload preservation and count rather than a None main cover.
        audio = self.open(self.tagged)
        tags_before = self.snapshot_other_tags(audio)
        set_front_cover(audio, JPEG_DATA)
        self.add_back_cover(audio, BACK_PNG_DATA)
        self.add_other_picture(audio, LEAFLET_JPEG_DATA)
        audio.save()

        audio = self.open(self.tagged)
        self.assertEqual(len(audio.tags["covr"]), 3)
        self.assertTrue(remove_front_cover(audio))
        audio.save()

        reopened = self.open(self.tagged)
        remaining = [bytes(c) for c in MP4(self.tagged).tags["covr"]]
        self.assertEqual(len(remaining), 2)
        self.assertNotIn(JPEG_DATA, remaining)
        self.assertIn(BACK_PNG_DATA, remaining)
        self.assertIn(LEAFLET_JPEG_DATA, remaining)
        # The surviving first entry is now the main cover.
        self.assertEqual(get_front_cover(reopened).data, BACK_PNG_DATA)
        after_tags = self.snapshot_other_tags(reopened)
        for key, value in tags_before.items():
            self.assertEqual(after_tags[key], value)

    def front_cover_count(self, path):
        # The first covr entry is the main cover; at most one is replaced.
        return 1 if MP4(path).tags.get("covr") else 0

    def snapshot_other_tags(self, audio):
        return {key: list(value) for key, value in audio.tags.items()
                if key != "covr"}

    def add_back_cover(self, audio, data):
        # A second covr entry stands in for another embedded picture;
        # M4A has no picture-type field.
        existing = list(audio.tags.get("covr", []))
        existing.append(MP4Cover(data, AtomDataType.PNG))
        audio.tags["covr"] = existing

    def add_other_picture(self, audio, data):
        existing = list(audio.tags.get("covr", []))
        existing.append(MP4Cover(data, AtomDataType.JPEG))
        audio.tags["covr"] = existing
        audio.tags["\xa9wrt"] = u"Composer X"

    def test_native_covr_atom_is_well_formed(self):
        audio = self.open(self.untagged)
        set_front_cover(audio, JPEG_DATA)
        audio.save()

        mp4 = MP4(self.untagged)
        covers = mp4.tags["covr"]
        self.assertEqual(len(covers), 1)
        self.assertEqual(bytes(covers[0]), JPEG_DATA)
        self.assertEqual(covers[0].imageformat, AtomDataType.JPEG)

        # Native API can still manipulate covr directly.
        mp4.tags["covr"] = [MP4Cover(PNG_DATA, AtomDataType.PNG)]
        mp4.save()
        cover = get_front_cover(MP4(self.untagged))
        self.assertEqual(cover.data, PNG_DATA)
        self.assertEqual(cover.image_type, "png")

    def test_replace_only_touches_first_covr_entry(self):
        mp4 = MP4(self.untagged)
        mp4.tags = mp4.MP4Tags()
        mp4.tags["covr"] = [
            MP4Cover(JPEG_DATA, AtomDataType.JPEG),
            MP4Cover(PNG_DATA, AtomDataType.PNG),
        ]
        mp4.save()

        audio = self.open(self.untagged)
        replacement = PNG_DATA + b"tail"
        set_front_cover(audio, replacement)
        audio.save()

        covers = MP4(self.untagged).tags["covr"]
        self.assertEqual(len(covers), 2)
        self.assertEqual(bytes(covers[0]), replacement)
        self.assertEqual(bytes(covers[1]), PNG_DATA)

    def test_shipped_multi_cover_sample(self):
        # covr-with-name.m4a ships two real covers (PNG then JPEG).
        path = get_temp_copy(os.path.join(DATA_DIR, "covr-with-name.m4a"))
        audio = File(path)
        cover = get_front_cover(audio)
        self.assertEqual(cover.image_type, "png")

        self.assertTrue(remove_front_cover(audio))
        audio.save()
        remaining = MP4(path).tags["covr"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].imageformat, AtomDataType.JPEG)


class TUnsupportedAndEdgeCases(TestCase):

    def test_unsupported_format_raises_on_all_operations(self):
        ogg = OggVorbis(os.path.join(DATA_DIR, "empty.ogg"))
        for operation in (get_front_cover, remove_front_cover):
            self.assertRaises(
                UnsupportedCoverFormatError, operation, ogg)
        self.assertRaises(
            UnsupportedCoverFormatError,
            set_front_cover, ogg, JPEG_DATA)

    def test_error_hierarchy(self):
        self.assertTrue(issubclass(UnsupportedCoverFormatError, CoverError))
        self.assertTrue(issubclass(InvalidImageError, CoverError))
        self.assertTrue(issubclass(CoverError, mutagen.MutagenError))

    def test_sniffed_type_beats_lying_declaration(self):
        # An MP3 whose APIC claims PNG but actually holds JPEG must report
        # the real type from the byte content.
        path = get_temp_copy(os.path.join(DATA_DIR, "no-tags.mp3"))
        tags = ID3()
        tags.add(APIC(encoding=3, mime="image/png",
                      type=PictureType.COVER_FRONT, desc=u"",
                      data=JPEG_DATA))
        tags.save(path)
        cover = get_front_cover(File(path))
        self.assertEqual(cover.data, JPEG_DATA)
        self.assertEqual(cover.image_type, "jpeg")

    def test_illegal_embedded_cover_raises_explicit_error(self):
        path = get_temp_copy(os.path.join(DATA_DIR, "no-tags.mp3"))
        tags = ID3()
        tags.add(APIC(encoding=3, mime="image/gif",
                      type=PictureType.COVER_FRONT, desc=u"",
                      data=GIF_DATA))
        tags.save(path)
        self.assertRaises(InvalidImageError, get_front_cover, File(path))

    def test_non_audio_object_raises(self):
        self.assertRaises(
            UnsupportedCoverFormatError, get_front_cover, object())
