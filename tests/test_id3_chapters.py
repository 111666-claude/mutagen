import os

from mutagen import Chapter
from mutagen.id3 import ID3, ChapterError, CHAP, CTOC, TIT2, APIC
from mutagen.id3._chapters import (
    get_chapters, set_chapters, delete_chapters, validate_chapters,
    MAX_CHAPTER_START_MS, MAX_CHAPTERS, TOC_ELEMENT_ID, CHAPTER_ELEMENT_ID)
from mutagen.id3._specs import CTOCFlags
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import EasyMP3

from tests import TestCase, DATA_DIR, get_temp_copy


UNICODE_TITLE = u"Chapter 序章 ♪ \U0001F3B5"
CHAPTERS = [
    Chapter(0, UNICODE_TITLE),
    Chapter(1500, u"Second"),
    Chapter(42000, u"Third"),
]


class TChapter(TestCase):

    def test_eq_and_ordering(self):
        self.assertEqual(Chapter(0, u"a"), Chapter(0, u"a"))
        self.assertNotEqual(Chapter(0, u"a"), Chapter(1, u"a"))
        self.assertNotEqual(Chapter(0, u"a"), Chapter(0, u"b"))
        self.assertLess(Chapter(0, u"b"), Chapter(1, u"a"))
        self.assertEqual(hash(Chapter(0, u"a")), hash(Chapter(0, u"a")))
        self.assertNotEqual(Chapter(0, u"a"), object())
        self.assertEqual(repr(Chapter(0, u"a")), "Chapter(0, 'a')")


class TID3ChapterValidation(TestCase):

    def check_invalid(self, chapters):
        self.assertRaises(ChapterError, validate_chapters, chapters)

    def test_accepts_empty(self):
        validate_chapters([])

    def test_accepts_valid(self):
        validate_chapters(CHAPTERS)

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
        self.check_invalid([Chapter(MAX_CHAPTER_START_MS + 1, u"a")])

    def test_accepts_start_at_limit(self):
        validate_chapters([Chapter(MAX_CHAPTER_START_MS, u"a")])

    def test_rejects_non_str_title(self):
        self.check_invalid([Chapter(0, b"bytes")])

    def test_rejects_too_many_chapters(self):
        self.check_invalid(
            [Chapter(i, u"t") for i in range(MAX_CHAPTERS + 1)])

    def test_duplicate_titles_are_allowed(self):
        validate_chapters([Chapter(0, u"same"), Chapter(10, u"same")])


class TID3ChaptersInMemory(TestCase):

    def setUp(self):
        self.id3 = ID3()

    def test_empty_tag_has_no_chapters(self):
        self.assertEqual(self.id3.get_chapters(), [])

    def test_add_chapters_creates_frames(self):
        self.id3.set_chapters(CHAPTERS)

        chap_frames = self.id3.getall("CHAP")
        self.assertEqual(len(chap_frames), 3)
        ctoc_frames = self.id3.getall("CTOC")
        self.assertEqual(len(ctoc_frames), 1)

        ctoc = ctoc_frames[0]
        self.assertEqual(ctoc.element_id, TOC_ELEMENT_ID)
        self.assertEqual(int(ctoc.flags),
                         CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED)
        self.assertEqual(ctoc.child_element_ids,
                         ["%s%d" % (CHAPTER_ELEMENT_ID, i)
                          for i in range(1, 4)])

    def test_chapter_frame_contents(self):
        self.id3.set_chapters(CHAPTERS)
        first = self.id3.getall("CHAP:" + CHAPTER_ELEMENT_ID + "1")[0]
        self.assertEqual(first.start_time, 0)
        self.assertEqual(first.end_time, 1500)
        self.assertEqual(first.start_offset, 0xFFFFFFFF)
        self.assertEqual(first.end_offset, 0xFFFFFFFF)
        self.assertEqual(first.sub_frames.getall("TIT2")[0].text,
                         [UNICODE_TITLE])

        last = self.id3.getall("CHAP:" + CHAPTER_ELEMENT_ID + "3")[0]
        self.assertEqual(last.start_time, 42000)
        self.assertEqual(last.end_time, MAX_CHAPTER_START_MS)

    def test_round_trip_in_order(self):
        self.id3.set_chapters(CHAPTERS)
        self.assertEqual(self.id3.get_chapters(), CHAPTERS)

    def test_replace_removes_old_frames(self):
        self.id3.set_chapters(CHAPTERS)
        replacement = [Chapter(5, u"only")]
        self.id3.set_chapters(replacement)

        self.assertEqual(len(self.id3.getall("CHAP")), 1)
        self.assertEqual(len(self.id3.getall("CTOC")), 1)
        self.assertEqual(self.id3.get_chapters(), replacement)

    def test_set_empty_clears_frames(self):
        self.id3.set_chapters(CHAPTERS)
        self.id3.set_chapters([])
        self.assertEqual(self.id3.getall("CHAP"), [])
        self.assertEqual(self.id3.getall("CTOC"), [])
        self.assertEqual(self.id3.get_chapters(), [])

    def test_clear_chapters(self):
        self.id3.set_chapters(CHAPTERS)
        self.id3.clear_chapters()
        self.assertEqual(self.id3.getall("CHAP"), [])
        self.assertEqual(self.id3.getall("CTOC"), [])

    def test_other_frames_are_preserved(self):
        self.id3.add(TIT2(encoding=3, text=u"keep me"))
        self.id3.set_chapters(CHAPTERS)
        self.id3.set_chapters([Chapter(1, u"x")])
        self.id3.clear_chapters()
        self.assertEqual(self.id3["TIT2"].text, [u"keep me"])

    def test_invalid_input_does_not_modify_the_tag(self):
        self.id3.set_chapters(CHAPTERS)
        keys_before = sorted(self.id3.keys())
        with self.assertRaises(ChapterError):
            self.id3.set_chapters([Chapter(-1, u"bad")])
        self.assertEqual(sorted(self.id3.keys()), keys_before)
        self.assertEqual(self.id3.get_chapters(), CHAPTERS)

    def test_helper_functions(self):
        set_chapters(self.id3, CHAPTERS)
        self.assertEqual(get_chapters(self.id3), CHAPTERS)
        delete_chapters(self.id3)
        self.assertEqual(get_chapters(self.id3), [])

    def test_reads_chapters_without_ctoc_sorted_by_id(self):
        self.id3.add(CHAP(element_id=u"b", start_time=200, end_time=0,
                          sub_frames=[TIT2(encoding=3, text=u"b")]))
        self.id3.add(CHAP(element_id=u"a", start_time=100, end_time=0,
                          sub_frames=[TIT2(encoding=3, text=u"a")]))
        self.assertEqual(
            self.id3.get_chapters(),
            [Chapter(100, u"a"), Chapter(200, u"b")])

    def test_on_disk_frame_order_follows_ctoc(self):
        self.id3.set_chapters(CHAPTERS)
        from mutagen.id3._util import ID3SaveConfig
        data = bytes(self.id3._write(ID3SaveConfig()))
        positions = [data.find(("CHAP%s%d" % (
            CHAPTER_ELEMENT_ID, i)).encode("ascii")) for i in range(1, 4)]
        self.assertEqual(positions, sorted(positions))

    def test_duplicate_element_ids_are_cleaned_up(self):
        self.id3.add(CTOC(
            element_id=u"toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=[u"dup", u"dup"], sub_frames=[]))
        self.id3.add(CHAP(
            element_id=u"dup", start_time=0, end_time=0,
            sub_frames=[TIT2(encoding=3, text=u"old")]))

        self.id3.set_chapters([Chapter(0, u"A"), Chapter(10, u"B")])
        element_ids = [
            frame.element_id for frame in self.id3.getall("CHAP")]
        self.assertEqual(len(element_ids), 2)
        self.assertEqual(len(set(element_ids)), 2)
        self.assertEqual(
            self.id3.get_chapters(),
            [Chapter(0, u"A"), Chapter(10, u"B")])


class TID3ChapterFileRoundTrip(TestCase):

    def setUp(self):
        self.filename = get_temp_copy(
            os.path.join(DATA_DIR, "silence-44-s.mp3"))

    def tearDown(self):
        os.unlink(self.filename)

    def test_add_replace_clear_round_trip(self):
        audio = MP3(self.filename)
        self.assertEqual(audio.get_chapters(), [])

        audio.set_chapters(CHAPTERS)
        audio.save()
        reopened = MP3(self.filename)
        self.assertEqual(reopened.get_chapters(), CHAPTERS)
        self.assertEqual(reopened.tags["TIT2"].text, [u"Silence"])

        replacement = [Chapter(100, u"A"), Chapter(200, u"B")]
        reopened.set_chapters(replacement)
        reopened.save()
        again = MP3(self.filename)
        self.assertEqual(again.get_chapters(), replacement)
        self.assertEqual(len(again.tags.getall("CHAP")), 2)
        self.assertEqual(again.tags["TIT2"].text, [u"Silence"])

        again.clear_chapters()
        again.save()
        cleared = MP3(self.filename)
        self.assertEqual(cleared.get_chapters(), [])
        self.assertEqual(cleared.tags.getall("CHAP"), [])
        self.assertEqual(cleared.tags.getall("CTOC"), [])
        self.assertEqual(cleared.tags["TIT2"].text, [u"Silence"])

    def test_cover_art_is_preserved(self):
        audio = MP3(self.filename)
        cover = b"\x89PNG fake cover"
        audio.tags.add(APIC(encoding=3, mime="image/png", type=3,
                            desc="Cover", data=cover))
        audio.save()

        audio = MP3(self.filename)
        audio.set_chapters(CHAPTERS)
        audio.save()

        reopened = MP3(self.filename)
        pictures = reopened.tags.getall("APIC")
        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0].data, cover)
        self.assertEqual(reopened.get_chapters(), CHAPTERS)

    def test_tagless_file_gets_an_id3_tag(self):
        filename = get_temp_copy(os.path.join(DATA_DIR, "no-tags.mp3"))
        try:
            audio = MP3(filename)
            self.assertIs(audio.tags, None)
            audio.set_chapters([Chapter(0, u"Solo")])
            audio.save()

            reopened = MP3(filename)
            self.assertEqual(reopened.get_chapters(),
                             [Chapter(0, u"Solo")])
            self.assertIsNotNone(reopened.tags)
        finally:
            os.unlink(filename)

    def test_save_as_id3v23(self):
        audio = MP3(self.filename)
        audio.set_chapters(CHAPTERS)
        audio.save(v2_version=3)

        reopened = MP3(self.filename)
        self.assertEqual(reopened.tags.version, (2, 3, 0))
        self.assertEqual(reopened.get_chapters(), CHAPTERS)

    def test_invalid_chapters_leave_file_untouched(self):
        audio = MP3(self.filename)
        audio.set_chapters(CHAPTERS)
        audio.save()
        good_state = open(self.filename, "rb").read()

        with self.assertRaises(ChapterError):
            audio.set_chapters([Chapter(-1, u"bad")])
        audio.save()

        self.assertEqual(open(self.filename, "rb").read(), good_state)
        self.assertEqual(MP3(self.filename).get_chapters(), CHAPTERS)

    def test_easy_id3_and_easy_mp3(self):
        easy = EasyMP3(self.filename)
        easy.set_chapters(CHAPTERS)
        easy.save()

        reopened = EasyMP3(self.filename)
        self.assertEqual(reopened.get_chapters(), CHAPTERS)
        self.assertEqual(reopened["title"], [u"Silence"])

        # EasyID3 directly
        tags = EasyID3(self.filename)
        tags.clear_chapters()
        tags.save()
        self.assertEqual(EasyID3(self.filename).get_chapters(), [])
