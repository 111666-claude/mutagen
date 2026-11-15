import os
import struct

from mutagen import Chapter
from mutagen.mp4 import (
    MP4, MP4Chapters, MP4MetadataError, MP4MetadataValueError, MAX_CHAPTERS,
    MAX_CHAPTER_TITLE_BYTES, MAX_CHAPTER_START_MS)
from mutagen.mp4._atom import Atoms

from tests import TestCase, DATA_DIR, get_temp_copy


UNICODE_TITLE = u"Chapter 序章 ♪ \U0001F3B5"
CHAPTERS = [
    Chapter(0, UNICODE_TITLE),
    Chapter(1500, u"Second"),
    Chapter(42000, u"Third"),
]


class TMP4ChapterValidation(TestCase):

    def setUp(self):
        self.chapters = MP4Chapters()

    def check_invalid(self, chapters):
        self.assertRaises(
            MP4MetadataValueError, self.chapters._validate_chapters,
            chapters)

    def test_accepts_empty(self):
        self.chapters._validate_chapters([])
        self.chapters.set_chapters([])

    def test_accepts_valid(self):
        self.chapters.set_chapters(CHAPTERS)
        self.assertEqual(self.chapters.get_chapters(), CHAPTERS)

    def test_rejects_non_list(self):
        self.check_invalid(Chapter(0, u"a"))

    def test_rejects_wrong_element_type(self):
        self.check_invalid([(0, u"a")])

    def test_rejects_negative_start(self):
        self.check_invalid([Chapter(-1, u"a")])

    def test_rejects_float_start(self):
        self.check_invalid([Chapter(1.5, u"a")])

    def test_rejects_bool_start(self):
        self.check_invalid([Chapter(True, u"a")])

    def test_rejects_equal_starts(self):
        self.check_invalid([Chapter(1, u"a"), Chapter(1, u"b")])

    def test_rejects_decreasing_starts(self):
        self.check_invalid([Chapter(100, u"a"), Chapter(50, u"b")])

    def test_rejects_start_above_limit(self):
        self.check_invalid(
            [Chapter(MAX_CHAPTER_START_MS + 1, u"a")])

    def test_rejects_non_str_title(self):
        self.check_invalid([Chapter(0, b"bytes")])

    def test_rejects_overlong_title(self):
        title = u"x" * (MAX_CHAPTER_TITLE_BYTES + 1)
        self.check_invalid([Chapter(0, title)])

    def test_accepts_title_at_limit(self):
        title = u"x" * MAX_CHAPTER_TITLE_BYTES
        self.chapters.set_chapters([Chapter(0, title)])

    def test_rejects_too_many_chapters(self):
        self.check_invalid(
            [Chapter(i, u"t") for i in range(MAX_CHAPTERS + 1)])

    def test_invalid_input_does_not_replace_existing(self):
        self.chapters.set_chapters(CHAPTERS)
        with self.assertRaises(MP4MetadataValueError):
            self.chapters.set_chapters([Chapter(-5, u"bad")])
        self.assertEqual(self.chapters.get_chapters(), CHAPTERS)

    def test_rendered_box_uses_version_one(self):
        self.chapters.set_chapters(CHAPTERS)
        data = self.chapters.render()
        # box header
        self.assertEqual(data[4:8], b"chpl")
        # full atom version and flags, followed by reserved bytes
        self.assertEqual(data[8:12], b"\x01\x00\x00\x00")
        self.assertEqual(data[12:16], b"\x00\x00\x00\x00")
        self.assertEqual(data[16], len(CHAPTERS))

    def test_rendered_times_use_100_nanosecond_units(self):
        self.chapters.set_chapters([Chapter(1500, u"x")])
        data = self.chapters.render()
        # header(8) + version/flags(4) + reserved(4) + count(1)
        self.assertEqual(
            data[17:25], (1500 * 10000).to_bytes(8, "big"))


class TMP4ChaptersFileRoundTrip(TestCase):

    original = os.path.join(DATA_DIR, "has-tags.m4a")

    def setUp(self):
        self.filename = get_temp_copy(self.original)
        self.audio = MP4(self.filename)

    def tearDown(self):
        os.unlink(self.filename)

    def test_starts_without_chapters(self):
        self.assertIsNone(self.audio.chapters)
        self.assertEqual(self.audio.get_chapters(), [])

    def test_add_replace_clear_round_trip(self):
        tag_keys = set(self.audio.tags.keys())
        length = self.audio.info.length

        self.audio.set_chapters(CHAPTERS)
        self.audio.save()
        reopened = MP4(self.filename)
        self.assertEqual(reopened.get_chapters(), CHAPTERS)
        self.assertEqual(set(reopened.tags.keys()), tag_keys)
        self.assertAlmostEqual(reopened.info.length, length)

        # legacy seconds based API still works
        self.assertEqual(reopened.chapters[0].start, 0.0)
        self.assertEqual(reopened.chapters[1].start, 1.5)
        self.assertEqual(reopened.chapters[0].title, UNICODE_TITLE)

        replacement = [Chapter(100, u"A"), Chapter(200, u"B")]
        reopened.set_chapters(replacement)
        reopened.save()
        again = MP4(self.filename)
        self.assertEqual(again.get_chapters(), replacement)
        self.assertEqual(set(again.tags.keys()), tag_keys)
        self.assertAlmostEqual(again.info.length, length)

        again.clear_chapters()
        again.save()
        cleared = MP4(self.filename)
        self.assertIsNone(cleared.chapters)
        self.assertEqual(cleared.get_chapters(), [])
        self.assertEqual(set(cleared.tags.keys()), tag_keys)

    def test_cover_art_is_preserved(self):
        covers_before = [bytes(c) for c in self.audio["covr"]]
        self.assertTrue(covers_before)

        self.audio.set_chapters(CHAPTERS)
        self.audio.save()
        self.assertEqual(
            [bytes(c) for c in MP4(self.filename)["covr"]],
            covers_before)

        MP4(self.filename).clear_chapters()
        MP4(self.filename).save()
        self.assertEqual(
            [bytes(c) for c in MP4(self.filename)["covr"]],
            covers_before)

    def test_invalid_chapters_leave_file_untouched(self):
        self.audio.set_chapters(CHAPTERS)
        self.audio.save()
        good_state = open(self.filename, "rb").read()

        with self.assertRaises(MP4MetadataValueError):
            self.audio.set_chapters([Chapter(-1, u"bad")])
        self.audio.save()

        self.assertEqual(open(self.filename, "rb").read(), good_state)
        self.assertEqual(MP4(self.filename).get_chapters(), CHAPTERS)

    def test_save_without_chapter_changes_is_stable(self):
        self.audio.set_chapters(CHAPTERS)
        self.audio.save()
        before = open(self.filename, "rb").read()
        self.audio.save()
        after = open(self.filename, "rb").read()
        self.assertEqual(before, after)


class TMP4ExistingChpl(TestCase):

    original = os.path.join(DATA_DIR, "nero-chapters.m4b")

    def setUp(self):
        self.filename = get_temp_copy(self.original)
        self.audio = MP4(self.filename)

    def tearDown(self):
        os.unlink(self.filename)

    def test_reads_existing_chapters(self):
        chapters = self.audio.get_chapters()
        self.assertEqual(len(chapters), 112)
        self.assertEqual(chapters[0], Chapter(0, u"001"))
        self.assertEqual(chapters[1].start, 17507)

    def test_replace_existing_chpl(self):
        new_chapters = [Chapter(0, u"新第一章"), Chapter(5000, u"Second")]
        self.audio.set_chapters(new_chapters)
        self.audio.save()

        reopened = MP4(self.filename)
        self.assertEqual(reopened.get_chapters(), new_chapters)
        self.assertIsNotNone(reopened.tags.get("\xa9nam"))

    def test_remove_existing_chpl(self):
        self.audio.clear_chapters()
        self.audio.save()

        reopened = MP4(self.filename)
        self.assertIsNone(reopened.chapters)
        self.assertEqual(reopened.get_chapters(), [])
        self.assertIsNotNone(reopened.tags.get("\xa9nam"))

    def test_round_trip_preserves_all_chapters(self):
        original = self.audio.get_chapters()
        self.audio.set_chapters(original)
        self.audio.save()
        self.assertEqual(MP4(self.filename).get_chapters(), original)

    def test_truncated_chpl_raises_metadata_error(self):
        with open(self.filename, "rb+") as fileobj:
            atoms = Atoms(fileobj)
            chpl = atoms.path(b"moov", b"udta", b"chpl")[-1]
            fileobj.seek(chpl.offset)
            fileobj.write(struct.pack(">I", chpl.length - 200))

        self.assertRaises(MP4MetadataError, MP4, self.filename)


class TMP4ChaptersWithoutTags(TestCase):

    original = os.path.join(DATA_DIR, "no-tags.m4a")

    def setUp(self):
        self.filename = get_temp_copy(self.original)
        self.audio = MP4(self.filename)

    def tearDown(self):
        os.unlink(self.filename)

    def test_add_chapters_without_ilst(self):
        self.assertIsNone(self.audio.tags)
        self.assertIsNone(self.audio.chapters)
        length = self.audio.info.length

        self.audio.set_chapters([Chapter(0, u"Only Chapter")])
        self.audio.save()

        reopened = MP4(self.filename)
        self.assertEqual(
            reopened.get_chapters(), [Chapter(0, u"Only Chapter")])
        self.assertIsNone(reopened.tags)
        self.assertAlmostEqual(reopened.info.length, length)

    def test_clear_on_tagless_file_is_noop(self):
        before = open(self.filename, "rb").read()
        self.audio.clear_chapters()
        self.audio.save()
        self.assertEqual(open(self.filename, "rb").read(), before)
