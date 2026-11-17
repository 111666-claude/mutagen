import os

import pytest

from mutagen.id3 import ID3, SYLT, USLT, TIT2, Encoding, ID3Tags
from mutagen.flac import FLAC
from mutagen._vorbis import VCommentDict
from mutagen.lyrics import (
    LyricsError, LyricsLine, TimedLyrics, DEFAULT_LANGUAGE,
    get_lyrics, getall_lyrics, set_lyrics, delete_lyrics,
    parse_lrc, serialize_lrc,
)
from tests import TestCase, DATA_DIR, get_temp_copy


MP3_FIXTURE = os.path.join(DATA_DIR, "lyrics-dual-language.mp3")
FLAC_FIXTURE = os.path.join(DATA_DIR, "lyrics-duplicate-timestamps.flac")


class TLyricsLine(TestCase):

    def test_tuple(self):
        line = LyricsLine(u"text", 100)
        self.assertEqual(line.text, u"text")
        self.assertEqual(line.time, 100)
        self.assertEqual(tuple(line), (u"text", 100))
        self.assertEqual(line, (u"text", 100))
        self.assertEqual(
            line.__getnewargs__(), (u"text", 100))

    def test_repr(self):
        self.assertIn("text", repr(LyricsLine(u"text", 1)))


class TTimedLyrics(TestCase):

    def test_default_language(self):
        lyrics = TimedLyrics()
        self.assertEqual(lyrics.language, DEFAULT_LANGUAGE)
        self.assertEqual(len(lyrics), 0)

    def test_append_validates(self):
        lyrics = TimedLyrics()
        lyrics.append((u"a", 0))
        lyrics.append(LyricsLine(u"b", 1))
        self.assertIsInstance(lyrics[0], LyricsLine)
        self.assertEqual(len(lyrics), 2)

    def test_negative_time(self):
        lyrics = TimedLyrics()
        self.assertRaises(LyricsError, lyrics.append, (u"a", -1))

    def test_bool_time_rejected(self):
        lyrics = TimedLyrics()
        self.assertRaises(LyricsError, lyrics.append, (u"a", True))

    def test_bad_text_type(self):
        lyrics = TimedLyrics()
        self.assertRaises(LyricsError, lyrics.append, (b"a", 0))

    def test_bad_pair(self):
        lyrics = TimedLyrics()
        self.assertRaises(LyricsError, lyrics.append, 42)
        self.assertRaises(LyricsError, lyrics.append, (u"only one",))

    def test_out_of_range(self):
        lyrics = TimedLyrics()
        self.assertRaises(
            LyricsError, lyrics.append, (u"a", 0x100000000))

    def test_extend_insert(self):
        lyrics = TimedLyrics([(u"a", 1)], language=u"eng")
        lyrics.insert(0, (u"b", 0))
        lyrics.extend([(u"c", 2)])
        self.assertEqual(
            [line.time for line in lyrics], [0, 1, 2])
        self.assertEqual(lyrics.language, u"eng")

    def test_equality(self):
        a = TimedLyrics([(u"a", 0)], language=u"eng")
        b = TimedLyrics([(u"a", 0)], language=u"eng")
        c = TimedLyrics([(u"a", 0)], language=u"ger")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, [(u"a", 0)])


class TLrcParser(TestCase):

    def test_basic(self):
        lyrics = parse_lrc(u"[00:01.00]a\n[01:02.50]b\n")
        self.assertEqual(
            list(lyrics),
            [LyricsLine(u"a", 1000), LyricsLine(u"b", 62500)])
        self.assertEqual(lyrics.language, DEFAULT_LANGUAGE)

    def test_fraction_variants(self):
        # 2-digit (LRC hundredths), 3-digit and 1-digit fractions.
        lyrics = parse_lrc(
            u"[00:00.5]a\n[00:00.50]b\n[00:00.500]c\n[00:00.]d\n")
        self.assertEqual(
            [line.time for line in lyrics], [500, 500, 500, 0])

    def test_colon_fraction_separator(self):
        lyrics = parse_lrc(u"[00:01:500]a\n")
        self.assertEqual(lyrics[0].time, 1500)

    def test_no_fraction(self):
        lyrics = parse_lrc(u"[1:2]a\n")
        self.assertEqual(lyrics[0], LyricsLine(u"a", 62000))

    def test_empty_text(self):
        lyrics = parse_lrc(u"[00:01.00]\n")
        self.assertEqual(lyrics[0], LyricsLine(u"", 1000))

    def test_duplicate_timestamps_stable(self):
        lyrics = parse_lrc(
            u"[00:01.00]one\n[00:01.00]two\n[00:01.00]three\n")
        self.assertEqual(
            [line.text for line in lyrics], [u"one", u"two", u"three"])
        self.assertEqual([line.time for line in lyrics], [1000] * 3)

    def test_multiple_timestamps_one_line(self):
        lyrics = parse_lrc(u"[00:01.00][00:02.00]shared text\n")
        self.assertEqual(
            list(lyrics),
            [LyricsLine(u"shared text", 1000),
             LyricsLine(u"shared text", 2000)])

    def test_metadata_lines_ignored(self):
        lyrics = parse_lrc(
            u"[ar:Artist]\n[ti:Title]\n[offset:250]\n[00:01.00]a\n")
        self.assertEqual(len(lyrics), 1)
        self.assertEqual(lyrics[0], LyricsLine(u"a", 1000))

    def test_blank_lines_ignored(self):
        lyrics = parse_lrc(u"\n  \n[00:01.00]a\n")
        self.assertEqual(len(lyrics), 1)

    def test_bad_timestamp_raises(self):
        self.assertRaises(LyricsError, parse_lrc, u"[not a stamp]a\n")
        self.assertRaises(LyricsError, parse_lrc, u"[99]a\n")

    def test_bad_input_type(self):
        self.assertRaises(LyricsError, parse_lrc, b"[00:01.00]a")


class TLrcSerializer(TestCase):

    def test_roundtrip(self):
        text = (
            u"[ar:keep out of the data model]\n"
            u"[00:01.00]first\n"
            u"[01:02.50]second\n"
            u"[01:02.50]again\n"
            u"[02:00.00]\n")
        lyrics = parse_lrc(text)
        rebuilt = parse_lrc(serialize_lrc(lyrics))
        self.assertEqual(rebuilt, lyrics)

    def test_format(self):
        lyrics = TimedLyrics([
            (u"a", 62500), (u"", 3600000), (u"b", 25)])
        self.assertEqual(
            serialize_lrc(lyrics),
            u"[01:02.500]a\n[60:00.000]\n[00:00.025]b\n")

    def test_plain_list_input(self):
        out = serialize_lrc([(u"a", 0)])
        self.assertEqual(out, u"[00:00.000]a\n")

    def test_rejects_negative(self):
        self.assertRaises(
            LyricsError, serialize_lrc, [(u"a", -1)])


class TID3InMemory(TestCase):

    def setUp(self):
        self.tags = ID3Tags()

    def _add_sylt(self, lang, text):
        self.tags.add(SYLT(
            encoding=Encoding.UTF8, lang=lang, format=2, type=1,
            desc=u"", text=list(text)))

    def test_getall_empty(self):
        self.assertEqual(getall_lyrics(self.tags), [])
        self.assertIsNone(get_lyrics(self.tags, u"eng"))

    def test_set_and_get_by_language(self):
        set_lyrics(self.tags, [
            (u"one", 100), (u"", 200), (u"two", 100)], u"eng")
        lyrics = get_lyrics(self.tags, u"eng")
        self.assertEqual(lyrics.language, u"eng")
        self.assertEqual(lyrics[0], LyricsLine(u"one", 100))
        self.assertEqual(lyrics[1], LyricsLine(u"", 200))
        # duplicate time stamp keeps stable order
        self.assertEqual(lyrics[2], LyricsLine(u"two", 100))

    def test_update_keeps_other_languages(self):
        self._add_sylt(u"eng", [(u"old", 0)])
        self._add_sylt(u"ger", [(u"alt", 0)])
        set_lyrics(self.tags, [(u"new", 5)], u"eng")

        self.assertEqual(
            [line.text for line in get_lyrics(self.tags, u"eng")],
            [u"new"])
        self.assertEqual(
            [line.text for line in get_lyrics(self.tags, u"ger")],
            [u"alt"])
        # exactly one SYLT per language
        langs = sorted(f.lang for f in self.tags.getall("SYLT"))
        self.assertEqual(langs, [u"eng", u"ger"])

    def test_update_keeps_other_frames_and_unknown(self):
        self.tags.add(TIT2(encoding=Encoding.UTF8, text=u"Title"))
        self.tags.add(USLT(
            encoding=Encoding.UTF8, lang=u"eng", desc=u"",
            text=u"unsync lyrics"))
        self.tags.unknown_frames = [b"XFME" + b"\x00" * 20]
        set_lyrics(self.tags, [(u"a", 0)], u"eng")

        self.assertEqual(self.tags["TIT2"].text, [u"Title"])
        self.assertEqual(self.tags.getall("USLT")[0].text,
                         u"unsync lyrics")
        self.assertEqual(len(self.tags.unknown_frames), 1)

    def test_duplicate_language_frames_merged_on_set(self):
        # Multiple frames for the same language (distinct descriptions,
        # so distinct HashKeys) simulate what a lenient reader keeps.
        # set_lyrics must replace them all with a single canonical frame.
        first = SYLT(
            encoding=Encoding.UTF8, lang=u"eng", format=2, type=1,
            desc=u"first", text=[(u"first", 0)])
        second = SYLT(
            encoding=Encoding.UTF8, lang=u"eng", format=2, type=1,
            desc=u"second", text=[(u"second", 1)])
        self.tags[first.HashKey] = first
        self.tags[second.HashKey] = second
        set_lyrics(self.tags, [(u"canonical", 9)], u"eng")

        frames = [f for f in self.tags.getall("SYLT")
                  if f.lang == u"eng"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].text, [(u"canonical", 9)])
        self.assertEqual(frames[0].format, 2)

    def test_frame_unit_sylt_ignored_and_preserved(self):
        frame_unit = SYLT(
            encoding=Encoding.UTF8, lang=u"eng", format=1, type=1,
            desc=u"frame-unit", text=[(u"frame based", 0)])
        self.tags.add(frame_unit)
        self.assertEqual(getall_lyrics(self.tags), [])
        self.assertIsNone(get_lyrics(self.tags, u"eng"))

        set_lyrics(self.tags, [(u"ms based", 0)], u"eng")
        formats = sorted(f.format for f in self.tags.getall("SYLT"))
        self.assertEqual(formats, [1, 2])
        delete_lyrics(self.tags)
        remaining = self.tags.getall("SYLT")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].format, 1)

    def test_written_frame_is_millisecond(self):
        set_lyrics(self.tags, [(u"a", 1234)], u"eng")
        frame = self.tags.getall("SYLT")[0]
        self.assertEqual(frame.format, 2)
        self.assertEqual(frame.text, [(u"a", 1234)])

    def test_negative_time_rejected(self):
        self.assertRaises(
            LyricsError, set_lyrics, self.tags,
            [(u"a", -1)], u"eng")

    def test_empty_lyrics_rejected(self):
        self.assertRaises(
            ValueError, set_lyrics, self.tags, [], u"eng")

    def test_bad_language(self):
        self.assertRaises(
            LyricsError, set_lyrics, self.tags,
            [(u"a", 0)], u"english")
        self.assertRaises(
            LyricsError, set_lyrics, self.tags,
            TimedLyrics([(u"a", 0)], language=u"eng\x00"))

    def test_delete_one_language(self):
        self._add_sylt(u"eng", [(u"a", 0)])
        self._add_sylt(u"ger", [(u"b", 0)])
        delete_lyrics(self.tags, u"eng")
        self.assertIsNone(get_lyrics(self.tags, u"eng"))
        self.assertIsNotNone(get_lyrics(self.tags, u"ger"))

    def test_delete_all(self):
        self._add_sylt(u"eng", [(u"a", 0)])
        self._add_sylt(u"ger", [(u"b", 0)])
        delete_lyrics(self.tags)
        self.assertEqual(getall_lyrics(self.tags), [])

    def test_timed_lyrics_object_carries_language(self):
        lyrics = TimedLyrics([(u"a", 0)], language=u"fra")
        set_lyrics(self.tags, lyrics)
        self.assertEqual(get_lyrics(self.tags, u"fra").language, u"fra")


class TVorbisInMemory(TestCase):

    def setUp(self):
        self.tags = VCommentDict()

    def test_empty(self):
        self.assertEqual(getall_lyrics(self.tags), [])
        self.assertIsNone(get_lyrics(self.tags))

    def test_set_get_roundtrip(self):
        lyrics = TimedLyrics([
            (u"one", 1000), (u"two", 1000), (u"", 2000)])
        set_lyrics(self.tags, lyrics)
        self.assertIn("LYRICS", self.tags)
        got = get_lyrics(self.tags)
        self.assertEqual(got.language, DEFAULT_LANGUAGE)
        self.assertEqual(got, lyrics)

    def test_update_keeps_other_comments(self):
        self.tags["ARTIST"] = u"Someone"
        self.tags["LYRICS"] = u"[00:01.00]old\n"
        set_lyrics(self.tags, [(u"new", 500)])
        self.assertEqual(self.tags["ARTIST"], [u"Someone"])
        self.assertEqual(
            get_lyrics(self.tags),
            TimedLyrics([(u"new", 500)]))

    def test_bad_lrc_raises(self):
        self.tags["LYRICS"] = u"garbage without stamps"
        self.assertRaises(LyricsError, getall_lyrics, self.tags)

    def test_delete(self):
        set_lyrics(self.tags, [(u"a", 0)])
        delete_lyrics(self.tags)
        self.assertNotIn("LYRICS", self.tags)
        # deleting again is a no-op
        delete_lyrics(self.tags)

    def test_negative_time_rejected(self):
        self.assertRaises(
            LyricsError, set_lyrics, self.tags, [(u"a", -1)])


class TUnsupportedTags(TestCase):

    def test_everything_raises(self):
        for func in (getall_lyrics, delete_lyrics):
            self.assertRaises(LyricsError, func, object())
        self.assertRaises(
            LyricsError, set_lyrics, object(), [(u"a", 0)])

    def test_none_tags(self):
        self.assertEqual(getall_lyrics(None), [])
        self.assertIsNone(get_lyrics(None))
        delete_lyrics(None)
        self.assertRaises(
            LyricsError, set_lyrics, None, [(u"a", 0)])


class TMP3FileRoundtrip(TestCase):

    def setUp(self):
        self.filename = get_temp_copy(MP3_FIXTURE)
        self.addCleanup(os.remove, self.filename)

    def test_read_fixture(self):
        tags = ID3(self.filename)
        all_lyrics = getall_lyrics(tags)
        self.assertEqual(
            sorted(ly.language for ly in all_lyrics),
            [u"eng", u"ger"])

        eng = get_lyrics(tags, u"eng")
        self.assertEqual(eng[0], LyricsLine(u"First line", 1000))
        self.assertEqual(eng[2], LyricsLine(u"", 4000))
        # duplicate time stamps, stable order
        self.assertEqual(eng[3], LyricsLine(u"Repeated time one", 5000))
        self.assertEqual(eng[4], LyricsLine(u"Repeated time two", 5000))

        ger = get_lyrics(tags, u"ger")
        self.assertEqual(ger[0], LyricsLine(u"Erste Zeile", 1000))

    def test_save_reload_preserves_all_languages(self):
        tags = ID3(self.filename)
        set_lyrics(tags, [
            (u"Updated first", 1100),
            (u"Updated second", 2600),
            (u"", 4100),
            (u"dup a", 6000),
            (u"dup b", 6000),
        ], u"eng")
        tags.save()

        reloaded = ID3(self.filename)
        eng = get_lyrics(reloaded, u"eng")
        self.assertEqual(eng[0], LyricsLine(u"Updated first", 1100))
        self.assertEqual(eng[2], LyricsLine(u"", 4100))
        self.assertEqual(
            [line.text for line in eng if line.time == 6000],
            [u"dup a", u"dup b"])
        # the other language is untouched
        ger = get_lyrics(reloaded, u"ger")
        self.assertEqual(ger[0], LyricsLine(u"Erste Zeile", 1000))
        # unrelated frame is untouched
        self.assertEqual(reloaded["TIT2"].text, [u"Lyrics title"])

    def test_native_sylt_values_roundtrip(self):
        # The SYLT frame on disk must remain a millisecond frame whose
        # (text, time) pairs survive the save untouched.
        tags = ID3(self.filename)
        before = [(f.lang, f.format, list(f.text))
                  for f in tags.getall("SYLT")]
        tags.save()
        after = ID3(self.filename)
        after_values = [(f.lang, f.format, list(f.text))
                        for f in after.getall("SYLT")]
        self.assertEqual(before, after_values)
        self.assertTrue(all(fmt == 2 for _, fmt, _ in after_values))

    def test_save_v23(self):
        # UTF-8 SYLT has to be downgraded when saving as ID3v2.3.
        tags = ID3(self.filename)
        tags.save(self.filename, v2_version=3)
        reloaded = ID3(self.filename)
        self.assertEqual(reloaded.version[:2], (2, 3))
        lyrics = get_lyrics(reloaded, u"eng")
        self.assertEqual(lyrics[0], LyricsLine(u"First line", 1000))
        self.assertEqual(
            reloaded.getall("SYLT")[0].encoding, Encoding.UTF16)

    def test_delete_and_reload(self):
        tags = ID3(self.filename)
        delete_lyrics(tags, u"eng")
        tags.save()
        reloaded = ID3(self.filename)
        self.assertIsNone(get_lyrics(reloaded, u"eng"))
        self.assertIsNotNone(get_lyrics(reloaded, u"ger"))

        delete_lyrics(reloaded)
        reloaded.save()
        self.assertEqual(
            getall_lyrics(ID3(self.filename)), [])


class TFLACFileRoundtrip(TestCase):

    def setUp(self):
        self.filename = get_temp_copy(FLAC_FIXTURE)
        self.addCleanup(os.remove, self.filename)

    def test_read_fixture(self):
        audio = FLAC(self.filename)
        lyrics = get_lyrics(audio.tags)
        self.assertEqual(lyrics.language, DEFAULT_LANGUAGE)
        # LRC hundredths -> milliseconds
        self.assertEqual(lyrics[0], LyricsLine(u"first line", 1000))
        self.assertEqual(lyrics[1], LyricsLine(u"second line", 62500))
        # duplicate time stamp with stable order
        self.assertEqual(
            [line.text for line in lyrics if line.time == 62500],
            [u"second line", u"repeated time stamp"])
        # empty text line
        self.assertIn(LyricsLine(u"", 120000), lyrics)
        # two stamps on one line, including the "[03:05.]" edge case
        self.assertEqual(
            [line.time for line in lyrics
             if line.text == u"two stamps one line"],
            [185000, 186250])

    def test_save_reload(self):
        audio = FLAC(self.filename)
        new_lyrics = TimedLyrics([
            (u"new line", 1500),
            (u"same time", 3000),
            (u"same time", 3000),
            (u"", 4500),
        ])
        set_lyrics(audio.tags, new_lyrics)
        audio.save()

        reloaded = FLAC(self.filename)
        self.assertEqual(get_lyrics(reloaded.tags), new_lyrics)
        # unknown/unrelated tags survive
        self.assertEqual(reloaded.tags["TITLE"], [u"Lyrics title"])
        # the stored value is real LRC text
        self.assertTrue(
            reloaded.tags["LYRICS"][0].startswith(u"[00:01.500]"))

    def test_native_lrc_roundtrip(self):
        audio = FLAC(self.filename)
        before = audio.tags["LYRICS"][:]
        audio.save()
        after = FLAC(self.filename).tags["LYRICS"]
        # re-parsing both sides gives identical timed lines
        self.assertEqual(
            parse_lrc(before[0]), parse_lrc(after[0]))

    def test_delete_and_reload(self):
        audio = FLAC(self.filename)
        delete_lyrics(audio.tags)
        audio.save()
        reloaded = FLAC(self.filename)
        self.assertNotIn("LYRICS", reloaded.tags)
        self.assertEqual(reloaded.tags["TITLE"], [u"Lyrics title"])

    def test_no_tags_file(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.flac"))
        self.addCleanup(os.remove, filename)
        audio = FLAC(filename)
        self.assertIsNone(audio.tags)
        # reading/deleting absent tags is a safe no-op
        self.assertEqual(getall_lyrics(audio.tags), [])
        self.assertIsNone(get_lyrics(audio.tags))
        delete_lyrics(audio.tags)
        # writing needs a comment block
        self.assertRaises(
            LyricsError, set_lyrics, audio.tags, [(u"a", 0)])

    def test_add_tags_then_set(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.flac"))
        self.addCleanup(os.remove, filename)
        audio = FLAC(filename)
        audio.add_tags()
        set_lyrics(audio.tags, [(u"a", 1000)])
        audio.save()
        reloaded = FLAC(filename)
        self.assertEqual(
            get_lyrics(reloaded.tags),
            TimedLyrics([(u"a", 1000)]))
