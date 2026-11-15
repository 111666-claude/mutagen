"""Tests for the unified synchronised lyrics API (mutagen.lyrics)."""

import os

from tests import TestCase, DATA_DIR, get_temp_copy

from mutagen.id3 import ID3, SYLT, USLT, TIT2, APIC, Encoding
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from mutagen.lyrics import (
    LyricsError, LyricLine, Lyrics,
    get_lyrics, set_lyrics, remove_lyrics,
    lyrics_to_lrc, lrc_to_lyrics, LRC_LANGUAGE_PREFIX, UNKNOWN_LANGUAGE,
)


MP3_FILE = os.path.join(DATA_DIR, "silence-44-s.mp3")
MP3_NOTAGS = os.path.join(DATA_DIR, "no-tags.mp3")
FLAC_FILE = os.path.join(DATA_DIR, "silence-44-s.flac")
FLAC_NOTAGS = os.path.join(DATA_DIR, "no-tags.flac")
M4A_FILE = os.path.join(DATA_DIR, "has-tags.m4a")
M4A_COVER = os.path.join(DATA_DIR, "covr-with-name.m4a")
M4A_NOTAGS = os.path.join(DATA_DIR, "no-tags.m4a")


def make_lyrics(language):
    lyrics = Lyrics(language=language)
    lyrics.add(0, u"first line %s" % language)
    lyrics.add(1250, u"Unicode Wörld 你好 \U0001F30D")
    lyrics.add(1250, u"second row at the same timestamp")
    lyrics.add(98765, u"")  # timing mark with empty text
    return lyrics


class TLyricLine(TestCase):

    def test_construction(self):
        line = LyricLine(1500, u"hello")
        self.assertEqual(line.time, 1500)
        self.assertEqual(line.text, u"hello")

    def test_default_text(self):
        self.assertEqual(LyricLine(0).text, u"")

    def test_equality_and_order(self):
        self.assertEqual(LyricLine(1, u"a"), LyricLine(1, u"a"))
        self.assertNotEqual(LyricLine(1, u"a"), LyricLine(2, u"a"))
        self.assertNotEqual(LyricLine(1, u"a"), LyricLine(1, u"b"))
        self.assertTrue(LyricLine(1, u"a") < LyricLine(1, u"b"))
        self.assertEqual(
            sorted([LyricLine(2, u"x"), LyricLine(1, u"y")]),
            [LyricLine(1, u"y"), LyricLine(2, u"x")])
        self.assertEqual(hash(LyricLine(1, u"a")), hash(LyricLine(1, u"a")))
        self.assertEqual(repr(LyricLine(1, u"a")), "LyricLine(1, 'a')")

    def test_bad_time(self):
        self.failUnlessRaises(LyricsError, LyricLine, -1, u"x")
        self.failUnlessRaises(LyricsError, LyricLine, 2 ** 32, u"x")
        self.failUnlessRaises(LyricsError, LyricLine, 1.5, u"x")
        self.failUnlessRaises(LyricsError, LyricLine, True, u"x")
        self.failUnlessRaises(LyricsError, LyricLine, "1", u"x")

    def test_boundary_times(self):
        LyricLine(0, u"start")
        LyricLine(0xFFFFFFFF, u"end")

    def test_bad_text(self):
        self.failUnlessRaises(LyricsError, LyricLine, 0, u"a\nb")
        self.failUnlessRaises(LyricsError, LyricLine, 0, u"a\rb")
        self.failUnlessRaises(LyricsError, LyricLine, 0, u"a\x00b")
        self.failUnlessRaises(LyricsError, LyricLine, 0, 123)


class TLyrics(TestCase):

    def test_default_language(self):
        self.assertEqual(Lyrics().language, UNKNOWN_LANGUAGE)

    def test_add_and_iterate(self):
        lyrics = Lyrics(language="eng")
        line = lyrics.add(100, u"x")
        self.assertEqual(line, LyricLine(100, u"x"))
        self.assertEqual(list(lyrics), [line])
        self.assertEqual(len(lyrics), 1)

    def test_bad_language(self):
        self.failUnlessRaises(LyricsError, Lyrics, language="en")
        self.failUnlessRaises(LyricsError, Lyrics, language="eng!")
        self.failUnlessRaises(LyricsError, Lyrics, language=123)

    def test_bad_lines(self):
        self.failUnlessRaises(
            LyricsError, Lyrics, [(1, u"x")], language="eng")

    def test_equality(self):
        a = make_lyrics("eng")
        b = make_lyrics("eng")
        self.assertEqual(a, b)
        b.lines[0].time = 1
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, Lyrics(language="deu"))


class TLRC(TestCase):

    def test_roundtrip(self):
        lyrics = make_lyrics("eng")
        block = lyrics_to_lrc(lyrics)
        self.assertTrue(block.startswith(u"[la:eng]\n"))
        self.assertIn(u"[00:01.250]Unicode", block)
        self.assertIn(u"[01:38.765]", block)
        self.assertEqual(lrc_to_lyrics(block), lyrics)

    def test_order_preserved(self):
        lyrics = Lyrics(language="eng")
        for time_ in (5000, 0, 2500, 2500):
            lyrics.add(time_, u"t%d" % time_)
        back = lrc_to_lyrics(lyrics_to_lrc(lyrics))
        self.assertEqual([l.time for l in back.lines],
                         [5000, 0, 2500, 2500])

    def test_multiple_timestamps_per_line(self):
        block = u"[la:eng]\n[00:01.000][00:02.500][00:03.25]shared\n"
        lyrics = lrc_to_lyrics(block)
        self.assertEqual(
            [l.time for l in lyrics.lines], [1000, 2500, 3250])
        self.assertTrue(
            all(l.text == u"shared" for l in lyrics.lines))

    def test_fraction_widths(self):
        lyrics = lrc_to_lyrics(
            u"[la:eng]\n[00:01.5][00:02.50][00:03.500]x\n")
        self.assertEqual(
            [l.time for l in lyrics.lines], [1500, 2500, 3500])

    def test_language_header(self):
        lyrics = lrc_to_lyrics(u"[00:01.000]no header\n")
        self.assertEqual(lyrics.language, UNKNOWN_LANGUAGE)
        lyrics = lrc_to_lyrics(u"[la:jpn]\n[00:01.000]ja\n")
        self.assertEqual(lyrics.language, "jpn")

    def test_unknown_metadata_ignored(self):
        block = u"[ar:Artist]\n[ti:Title]\n[la:eng]\n[00:01.000]sung\n"
        lyrics = lrc_to_lyrics(block)
        self.assertEqual(lyrics.lines, [LyricLine(1000, u"sung")])

    def test_plain_lyrics_return_none(self):
        self.assertIsNone(
            lrc_to_lyrics(u"just plain words\nsecond line\n"))
        self.assertIsNone(lrc_to_lyrics(u"[ar:Artist]\n[ti:Title]\n"))

    def test_bad_timestamps(self):
        bad_blocks = [
            u"[la:eng]\n[99:99.000]x",      # seconds out of range
            u"[la:eng]\n[01:60.000]x",      # seconds out of range
            u"[la:eng]\n[00:0a.000]x",      # non numeric
            u"[la:eng]\n[00:01.0000]x",     # four digit fraction
            u"[la:eng]\n[00:1.000]x",       # single digit seconds
            u"[la:eng]\n[00:01.00",         # unclosed tag
            u"[00:01.000]ok\n[00:0b.000]bad",
        ]
        for block in bad_blocks:
            self.failUnlessRaises(
                LyricsError, lrc_to_lyrics, block)

    def test_bad_language_header(self):
        self.failUnlessRaises(
            LyricsError, lrc_to_lyrics, u"[la:e]\n[00:01.000]x")

    def test_serialise_validates(self):
        lyrics = Lyrics(language="eng")
        lyrics.add(1, u"ok")
        lyrics.lines[0].time = -1
        self.failUnlessRaises(LyricsError, lyrics_to_lrc, lyrics)

    def test_language_prefix_constant(self):
        block = lyrics_to_lrc(make_lyrics("eng"))
        self.assertIn(u"[" + LRC_LANGUAGE_PREFIX + u"eng]", block)


class TID3SYLT(TestCase):

    def setUp(self):
        self.tags = ID3()

    def test_roundtrip(self):
        lyrics = make_lyrics("eng")
        set_lyrics(self.tags, lyrics)
        self.assertEqual(get_lyrics(self.tags), [lyrics])

    def test_native_frame(self):
        set_lyrics(self.tags, make_lyrics("eng"))
        frames = self.tags.getall("SYLT")
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertIsInstance(frame, SYLT)
        self.assertEqual(frame.lang, "eng")
        self.assertEqual(frame.format, 2)       # milliseconds
        self.assertEqual(frame.type, 1)         # lyrics
        self.assertEqual(frame.encoding, Encoding.UTF8)
        self.assertEqual(frame.text[0], (u"first line eng", 0))

    def test_foreign_encoding_read(self):
        self.tags.add(SYLT(
            encoding=Encoding.UTF16, lang="fra", format=2, type=1,
            desc=u"", text=[(u"Bonjour", 0), (u"monde", 2500)]))
        lyrics = get_lyrics(self.tags, "fra")
        self.assertEqual(len(lyrics), 1)
        self.assertEqual(
            lyrics[0].lines,
            [LyricLine(0, u"Bonjour"), LyricLine(2500, u"monde")])

    def test_mpeg_unit_frame_rejected(self):
        self.tags.add(SYLT(
            encoding=Encoding.UTF8, lang="eng", format=1, type=1,
            desc=u"", text=[(u"x", 10)]))
        self.failUnlessRaises(LyricsError, get_lyrics, self.tags)

    def test_multi_language_replace_and_remove(self):
        eng = make_lyrics("eng")
        jpn = make_lyrics("jpn")
        set_lyrics(self.tags, eng)
        set_lyrics(self.tags, jpn)
        self.assertEqual(
            sorted(l.language for l in get_lyrics(self.tags)),
            ["eng", "jpn"])

        replacement = Lyrics(language="eng")
        replacement.add(4000, u"new english")
        set_lyrics(self.tags, replacement)
        self.assertEqual(get_lyrics(self.tags, "eng"), [replacement])
        self.assertEqual(get_lyrics(self.tags, "jpn"), [jpn])

        self.assertEqual(remove_lyrics(self.tags, "jpn"), 1)
        self.assertEqual(get_lyrics(self.tags, "jpn"), [])
        self.assertEqual(len(get_lyrics(self.tags)), 1)
        self.assertEqual(remove_lyrics(self.tags), 1)
        self.assertEqual(self.tags.getall("SYLT"), [])

    def test_remove_missing_language(self):
        self.assertEqual(remove_lyrics(self.tags, "eng"), 0)
        self.assertEqual(remove_lyrics(self.tags), 0)

    def test_uslt_untouched(self):
        self.tags.add(USLT(
            encoding=Encoding.UTF8, lang="eng", desc=u"",
            text=u"unsynchronised text"))
        set_lyrics(self.tags, make_lyrics("eng"))
        self.assertEqual(
            self.tags.getall("USLT")[0].text, u"unsynchronised text")
        remove_lyrics(self.tags)
        self.assertEqual(len(self.tags.getall("USLT")), 1)

    def test_empty_lyrics_rejected(self):
        self.failUnlessRaises(
            LyricsError, set_lyrics, self.tags, Lyrics(language="eng"))

    def test_id3v23_and_v24_file_roundtrip(self):
        lyrics = make_lyrics("eng")
        for v2_version in (3, 4):
            path = get_temp_copy(MP3_FILE)
            audio = MP3(path)
            set_lyrics(audio.tags, lyrics)
            audio.save(v2_version=v2_version)
            with open(path, "rb") as fileobj:
                header = fileobj.read(10)
            self.assertEqual(header[:3], b"ID3")
            self.assertEqual(header[3], v2_version)
            reread = MP3(path)
            self.assertEqual(get_lyrics(reread.tags, "eng"), [lyrics])
            frame = reread.tags.getall("SYLT")[0]
            self.assertEqual(frame.format, 2)
            self.assertEqual(frame.lang, "eng")


class TVorbisLRC(TestCase):
    """FLAC Vorbis comment behaviour exercised through VCFLACDict."""

    def setUp(self):
        self.flac = FLAC(get_temp_copy(FLAC_FILE))
        self.tags = self.flac.tags

    def tearDown(self):
        self.flac.save()

    def test_roundtrip_and_native_comment(self):
        lyrics = make_lyrics("eng")
        set_lyrics(self.tags, lyrics)
        self.flac.save()
        reread = FLAC(self.flac.filename)
        self.assertEqual(get_lyrics(reread.tags, "eng"), [lyrics])
        blocks = reread.tags.get("LYRICS", [])
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].startswith(u"[la:eng]"))
        # The native comment parses back through the public LRC API.
        self.assertEqual(lrc_to_lyrics(blocks[0]), lyrics)

    def test_multi_language(self):
        eng = make_lyrics("eng")
        jpn = make_lyrics("jpn")
        set_lyrics(self.tags, eng)
        set_lyrics(self.tags, jpn)
        self.flac.save()
        reread = FLAC(self.flac.filename)
        self.assertEqual(
            sorted(l.language for l in get_lyrics(reread.tags)),
            ["eng", "jpn"])
        self.assertEqual(get_lyrics(reread.tags, "jpn"), [jpn])

    def test_replace_and_remove(self):
        set_lyrics(self.tags, make_lyrics("eng"))
        set_lyrics(self.tags, make_lyrics("jpn"))
        replacement = Lyrics(language="eng")
        replacement.add(1, u"replaced")
        set_lyrics(self.tags, replacement)
        self.assertEqual(get_lyrics(self.tags, "eng"), [replacement])
        self.assertEqual(len(get_lyrics(self.tags, "jpn")), 1)
        self.assertEqual(remove_lyrics(self.tags, "jpn"), 1)
        self.assertEqual(remove_lyrics(self.tags, "jpn"), 0)
        self.assertEqual(remove_lyrics(self.tags), 1)
        self.assertNotIn("LYRICS", self.tags)

    def test_other_comments_and_pictures_kept(self):
        self.tags["TITLE"] = u"keep me"
        picture = Picture()
        picture.type = 3
        picture.mime = "image/png"
        picture.data = b"\x89PNG cover"
        self.flac.add_picture(picture)
        set_lyrics(self.tags, make_lyrics("eng"))
        self.flac.save()
        reread = FLAC(self.flac.filename)
        self.assertEqual(reread.tags["TITLE"], [u"keep me"])
        self.assertIn(b"\x89PNG cover",
                      [bytes(p.data) for p in reread.pictures])
        remove_lyrics(reread.tags)
        reread.save()
        final = FLAC(self.flac.filename)
        self.assertNotIn("LYRICS", final.tags)
        self.assertEqual(final.tags["TITLE"], [u"keep me"])
        self.assertTrue(
            any(bytes(p.data) == b"\x89PNG cover" for p in final.pictures))

    def test_plain_lyrics_comment_preserved(self):
        self.tags["LYRICS"] = [u"plain unsynchronised words"]
        set_lyrics(self.tags, make_lyrics("eng"))
        values = self.tags["LYRICS"]
        self.assertIn(u"plain unsynchronised words", values)
        self.assertEqual(len(get_lyrics(self.tags)), 1)
        remove_lyrics(self.tags)
        self.assertEqual(self.tags["LYRICS"],
                         [u"plain unsynchronised words"])

    def test_external_lrc_without_language_header(self):
        self.tags["LYRICS"] = [
            u"[00:01.000]no language header\n[00:02.500]second"]
        lyrics = get_lyrics(self.tags)
        self.assertEqual(len(lyrics), 1)
        self.assertEqual(lyrics[0].language, UNKNOWN_LANGUAGE)
        self.assertEqual(
            lyrics[0].lines,
            [LyricLine(1000, u"no language header"),
             LyricLine(2500, u"second")])
        replacement = Lyrics(language=UNKNOWN_LANGUAGE)
        replacement.add(500, u"replaced")
        set_lyrics(self.tags, replacement)
        self.assertEqual(get_lyrics(self.tags), [replacement])


class TMP4LRC(TestCase):

    def setUp(self):
        self.mp4 = MP4(get_temp_copy(M4A_FILE))
        self.tags = self.mp4.tags

    def tearDown(self):
        self.mp4.save()

    def test_roundtrip_and_native_atom(self):
        lyrics = make_lyrics("eng")
        set_lyrics(self.tags, lyrics)
        self.mp4.save()
        reread = MP4(self.mp4.filename)
        self.assertEqual(get_lyrics(reread.tags, "eng"), [lyrics])
        blocks = reread.tags[u"\xa9lyr"]
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].startswith(u"[la:eng]"))
        self.assertEqual(lrc_to_lyrics(blocks[0]), lyrics)

    def test_multi_language(self):
        eng = make_lyrics("eng")
        jpn = make_lyrics("jpn")
        set_lyrics(self.tags, eng)
        set_lyrics(self.tags, jpn)
        self.mp4.save()
        reread = MP4(self.mp4.filename)
        self.assertEqual(
            sorted(l.language for l in get_lyrics(reread.tags)),
            ["eng", "jpn"])

    def test_replace_and_remove(self):
        set_lyrics(self.tags, make_lyrics("eng"))
        set_lyrics(self.tags, make_lyrics("jpn"))
        replacement = Lyrics(language="eng")
        replacement.add(1, u"replaced")
        set_lyrics(self.tags, replacement)
        self.assertEqual(get_lyrics(self.tags, "eng"), [replacement])
        self.assertEqual(remove_lyrics(self.tags, "jpn"), 1)
        self.assertEqual(remove_lyrics(self.tags), 1)
        self.assertNotIn(u"\xa9lyr", self.tags)

    def test_cover_kept(self):
        sample = MP4(get_temp_copy(M4A_COVER))
        before = [bytes(c) for c in sample.tags.get("covr", [])]
        self.assertTrue(before)
        set_lyrics(sample.tags, make_lyrics("eng"))
        sample.save()
        reread = MP4(sample.filename)
        self.assertEqual(
            [bytes(c) for c in reread.tags.get("covr", [])], before)
        self.assertEqual(len(get_lyrics(reread.tags)), 1)

    def test_external_lrc_without_language_header(self):
        self.tags[u"\xa9lyr"] = [u"[00:00.000]bare lrc"]
        lyrics = get_lyrics(self.tags)
        self.assertEqual(len(lyrics), 1)
        self.assertEqual(lyrics[0].language, UNKNOWN_LANGUAGE)
        self.assertEqual(lyrics[0].lines, [LyricLine(0, u"bare lrc")])


class TFileLevelIntegration(TestCase):
    """Real files: round trips, fresh tags and cross-format consistency."""

    def _roundtrip(self, path, loader, tags_attr):
        audio = loader(path)
        if audio.tags is None:
            audio.add_tags()
        eng = make_lyrics("eng")
        jpn = make_lyrics("jpn")
        set_lyrics(audio.tags, eng)
        set_lyrics(audio.tags, jpn)
        audio.save()

        reread = loader(path)
        got = sorted(get_lyrics(getattr(reread, tags_attr)),
                     key=lambda x: x.language)
        self.assertEqual(got, sorted([eng, jpn], key=lambda x: x.language))
        # order inside one language, including same-timestamp rows
        self.assertEqual(
            [l.time for l in get_lyrics(reread.tags, "eng")[0].lines],
            [l.time for l in eng.lines])
        self.assertEqual(
            [l.text for l in get_lyrics(reread.tags, "eng")[0].lines],
            [l.text for l in eng.lines])

    def test_mp3_roundtrip(self):
        self._roundtrip(get_temp_copy(MP3_FILE), MP3, "tags")

    def test_flac_roundtrip(self):
        self._roundtrip(get_temp_copy(FLAC_NOTAGS), FLAC, "tags")

    def test_m4a_roundtrip(self):
        self._roundtrip(get_temp_copy(M4A_NOTAGS), MP4, "tags")

    def test_cross_format_consistency(self):
        eng = make_lyrics("eng")
        jpn = make_lyrics("jpn")
        seen = []
        for path, loader in (
                (get_temp_copy(MP3_NOTAGS), MP3),
                (get_temp_copy(FLAC_NOTAGS), FLAC),
                (get_temp_copy(M4A_NOTAGS), MP4)):
            audio = loader(path)
            audio.add_tags()
            set_lyrics(audio.tags, eng)
            set_lyrics(audio.tags, jpn)
            audio.save()
            reread = loader(path)
            seen.append(sorted(
                get_lyrics(reread.tags), key=lambda x: x.language))
        for model in seen[1:]:
            self.assertEqual(model, seen[0])

    def test_mp3_cover_and_unrelated_tag_survive(self):
        path = get_temp_copy(MP3_NOTAGS)
        audio = MP3(path)
        audio.add_tags()
        audio.tags.add(TIT2(encoding=Encoding.UTF8, text=u"title"))
        audio.tags.add(APIC(
            encoding=Encoding.UTF8, mime="image/png", type=3,
            desc=u"cover", data=b"\x89PNG cover"))
        set_lyrics(audio.tags, make_lyrics("eng"))
        audio.save()
        reread = MP3(path)
        self.assertEqual(reread.tags["TIT2"].text, [u"title"])
        self.assertEqual(reread.tags.getall("APIC")[0].data,
                         b"\x89PNG cover")
        self.assertEqual(len(get_lyrics(reread.tags)), 1)
        remove_lyrics(reread.tags, "deu")  # nothing to remove
        self.assertEqual(len(get_lyrics(reread.tags)), 1)
        remove_lyrics(reread.tags)
        reread.save()
        final = MP3(path)
        self.assertEqual(get_lyrics(final.tags), [])
        self.assertEqual(final.tags.getall("APIC")[0].data,
                         b"\x89PNG cover")
        self.assertEqual(final.tags["TIT2"].text, [u"title"])

    def test_files_without_tags(self):
        for path, loader in (
                (MP3_NOTAGS, MP3),
                (FLAC_NOTAGS, FLAC),
                (M4A_NOTAGS, MP4)):
            audio = loader(get_temp_copy(path))
            self.assertIsNone(audio.tags)
            self.assertEqual(get_lyrics(audio.tags), [])

    def test_unsupported_tag_type(self):
        self.failUnlessRaises(TypeError, get_lyrics, object())
        self.failUnlessRaises(
            TypeError, set_lyrics, object(), make_lyrics("eng"))
        self.failUnlessRaises(TypeError, remove_lyrics, object())

    def test_set_rejects_wrong_type(self):
        self.failUnlessRaises(
            LyricsError, set_lyrics, ID3(), u"not a lyrics object")
