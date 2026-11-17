import os

from tests import TestCase, DATA_DIR, get_temp_copy, get_temp_empty

from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3, POPM
from mutagen.rating import (
    RatingError, DEFAULT_OWNER,
    stars_to_rating, rating_to_stars,
    get_rating, set_rating, get_play_count, set_play_count,
    delete_rating,
)

ALICE = u"alice@example.com"
BOB = u"bob@example.com"

MP3_FIXTURE = os.path.join(DATA_DIR, "rating-two-owners.mp3")
FLAC_FIXTURE = os.path.join(DATA_DIR, "rating-default-user.flac")


class TMapping(TestCase):

    def test_stars_to_rating_exact_values(self):
        self.assertEqual(
            [stars_to_rating(s) for s in range(6)],
            [0, 51, 102, 153, 204, 255])

    def test_round_trip_all_stars(self):
        for stars in range(6):
            self.assertEqual(rating_to_stars(stars_to_rating(stars)), stars)

    def test_quantization_all_bytes_in_range(self):
        # Every possible wire value must map to a valid star rating.
        mapped = [rating_to_stars(value) for value in range(256)]
        self.assertTrue(all(0 <= value <= 5 for value in mapped))
        self.assertEqual(min(mapped), 0)
        self.assertEqual(max(mapped), 5)

    def test_quantization_tolerance(self):
        # Half values round up (127 -> 2, 128 -> 3); boundaries sit at the
        # midpoints of the 51-wide buckets.
        self.assertEqual(rating_to_stars(0), 0)
        self.assertEqual(rating_to_stars(25), 0)
        self.assertEqual(rating_to_stars(26), 1)
        self.assertEqual(rating_to_stars(51), 1)
        self.assertEqual(rating_to_stars(127), 2)
        self.assertEqual(rating_to_stars(128), 3)
        self.assertEqual(rating_to_stars(229), 4)
        self.assertEqual(rating_to_stars(230), 5)
        self.assertEqual(rating_to_stars(255), 5)

    def test_out_of_range_stars(self):
        self.assertRaises(ValueError, stars_to_rating, -1)
        self.assertRaises(ValueError, stars_to_rating, 6)
        self.assertRaises(ValueError, rating_to_stars, -1)
        self.assertRaises(ValueError, rating_to_stars, 256)

    def test_wrong_type_stars(self):
        for bad in (1.0, "3", None, True):
            self.assertRaises(TypeError, stars_to_rating, bad)
            self.assertRaises(TypeError, rating_to_stars, bad)


class TMP3Ratings(TestCase):

    def setUp(self):
        self.filename = get_temp_copy(MP3_FIXTURE)
        self.audio = MP3(self.filename)

    def tearDown(self):
        os.unlink(self.filename)

    def test_read_fixture_owners(self):
        # Fixture: alice 204/255 = 4 stars, 7 plays;
        # bob 102/255 = 2 stars, 42 plays.
        self.assertEqual(get_rating(self.audio, ALICE), 4)
        self.assertEqual(get_play_count(self.audio, ALICE), 7)
        self.assertEqual(get_rating(self.audio, BOB), 2)
        self.assertEqual(get_play_count(self.audio, BOB), 42)

    def test_missing_owner_returns_none(self):
        self.assertTrue(get_rating(self.audio, u"nobody@example.com") is None)
        self.assertTrue(
            get_play_count(self.audio, u"nobody@example.com") is None)

    def test_default_owner_is_empty_string(self):
        self.assertEqual(DEFAULT_OWNER, u"")
        self.assertTrue(get_rating(self.audio) is None)
        set_rating(self.audio, 3)
        self.assertEqual(get_rating(self.audio), 3)
        self.assertEqual(
            get_rating(self.audio, DEFAULT_OWNER), 3)

    def test_owners_do_not_overwrite(self):
        set_rating(self.audio, 5, ALICE)
        set_play_count(self.audio, 100, ALICE)
        # bob's data is untouched
        self.assertEqual(get_rating(self.audio, BOB), 2)
        self.assertEqual(get_play_count(self.audio, BOB), 42)
        # and the file still holds two distinct POPM frames
        self.assertEqual(len(self.audio.tags.getall("POPM")), 2)

    def test_wire_value_on_save(self):
        set_rating(self.audio, 5, ALICE)
        frame = self.audio.tags["POPM:" + ALICE]
        self.assertEqual(frame.rating, 255)
        set_rating(self.audio, 0, BOB)
        self.assertEqual(self.audio.tags["POPM:" + BOB].rating, 0)

    def test_save_and_reread(self):
        set_rating(self.audio, 3, ALICE)
        set_play_count(self.audio, 11, ALICE)
        self.audio.save()

        reread = MP3(self.filename)
        self.assertEqual(get_rating(reread, ALICE), 3)
        self.assertEqual(get_play_count(reread, ALICE), 11)
        self.assertEqual(reread.tags["POPM:" + ALICE].rating, 153)
        # other owner preserved on disk
        self.assertEqual(get_rating(reread, BOB), 2)
        self.assertEqual(get_play_count(reread, BOB), 42)

    def test_repeated_saves_are_stable(self):
        set_rating(self.audio, 4, ALICE)
        set_play_count(self.audio, 9, ALICE)
        self.audio.save()
        first = open(self.filename, "rb").read()

        for _ in range(3):
            again = MP3(self.filename)
            set_rating(again, 4, ALICE)
            set_play_count(again, 9, ALICE)
            again.save()
        second = open(self.filename, "rb").read()
        self.assertEqual(first, second)

        # and the values still read back correctly
        final = MP3(self.filename)
        self.assertEqual(get_rating(final, ALICE), 4)
        self.assertEqual(get_play_count(final, ALICE), 9)

    def test_cover_chapter_and_unknown_frames_survive(self):
        set_rating(self.audio, 1, ALICE)
        self.audio.save()
        reread = ID3(self.filename)

        self.assertEqual(len(reread.getall("APIC")), 1)
        self.assertEqual(reread.getall("APIC")[0].data,
                         b"\x89PNG\r\n\x1a\ncover-bytes")
        self.assertEqual(len(reread.getall("CHAP")), 1)
        chap = reread.getall("CHAP")[0]
        self.assertEqual(chap.element_id, "chapter-1")
        self.assertTrue("TIT3" in chap.sub_frames)
        self.assertEqual(
            [raw[:4] for raw in reread.unknown_frames], [b"XENO"])

    def test_other_text_frames_survive(self):
        set_rating(self.audio, 2, ALICE)
        self.audio.save()
        reread = MP3(self.filename)
        self.assertEqual(reread.tags["TIT2"], u"Rated Track")
        self.assertEqual(reread.tags["TPE1"], u"Rated Artist")

    def test_set_creates_popm_for_new_owner(self):
        owner = u"new@example.com"
        self.assertTrue(get_rating(self.audio, owner) is None)
        set_rating(self.audio, 2, owner)
        self.assertEqual(get_rating(self.audio, owner), 2)
        # no counter has been written yet
        self.assertTrue(get_play_count(self.audio, owner) is None)
        self.audio.save()
        reread = MP3(self.filename)
        self.assertEqual(get_rating(reread, owner), 2)
        self.assertTrue(get_play_count(reread, owner) is None)

    def test_play_count_creates_frame_with_zero_rating_byte(self):
        owner = u"counter@example.com"
        set_play_count(self.audio, 3, owner)
        self.assertEqual(get_play_count(self.audio, owner), 3)
        # the frame's rating byte defaults to 0, i.e. 0 stars
        self.assertEqual(self.audio.tags["POPM:" + owner].rating, 0)
        self.assertEqual(get_rating(self.audio, owner), 0)

    def test_popm_without_counter_reads_none(self):
        self.audio.tags.add(POPM(email=u"nocount@example.com", rating=128))
        self.assertTrue(
            get_play_count(self.audio, u"nocount@example.com") is None)
        self.assertEqual(
            get_rating(self.audio, u"nocount@example.com"), 3)

    def test_delete_single_owner(self):
        self.assertTrue(delete_rating(self.audio, ALICE))
        self.assertTrue(get_rating(self.audio, ALICE) is None)
        # bob survives
        self.assertEqual(get_rating(self.audio, BOB), 2)
        self.assertEqual(len(self.audio.tags.getall("POPM")), 1)
        self.assertFalse(delete_rating(self.audio, ALICE))

    def test_invalid_rating_values(self):
        self.assertRaises(
            ValueError, set_rating, self.audio, -1, ALICE)
        self.assertRaises(
            ValueError, set_rating, self.audio, 6, ALICE)
        self.assertRaises(
            TypeError, set_rating, self.audio, 2.5, ALICE)
        self.assertRaises(
            TypeError, set_rating, self.audio, True, ALICE)

    def test_negative_play_count_rejected(self):
        self.assertRaises(
            ValueError, set_play_count, self.audio, -1, ALICE)
        self.assertRaises(
            TypeError, set_play_count, self.audio, 1.5, ALICE)
        self.assertRaises(
            TypeError, set_play_count, self.audio, False, ALICE)

    def test_large_play_count_round_trips(self):
        big = 2 ** 32 + 1234
        set_play_count(self.audio, big, ALICE)
        self.audio.save()
        reread = MP3(self.filename)
        self.assertEqual(get_play_count(reread, ALICE), big)

    def test_bad_owner_type(self):
        self.assertRaises(TypeError, get_rating, self.audio, 123)
        self.assertRaises(TypeError, set_rating, self.audio, 3, b"x@y.z")

    def test_bare_id3_tag_object(self):
        tags = ID3(self.filename)
        self.assertEqual(get_rating(tags, ALICE), 4)
        set_rating(tags, 5, ALICE)
        tags.save()
        self.assertEqual(get_rating(ID3(self.filename), ALICE), 5)


class TFLACRatings(TestCase):

    def setUp(self):
        self.filename = get_temp_copy(FLAC_FIXTURE)
        self.audio = FLAC(self.filename)

    def tearDown(self):
        os.unlink(self.filename)

    def test_read_fixture_default_user(self):
        # 204 -> 4 stars, 7 plays
        self.assertEqual(get_rating(self.audio), 4)
        self.assertEqual(get_play_count(self.audio), 7)
        # explicit default owner is accepted
        self.assertEqual(get_rating(self.audio, DEFAULT_OWNER), 4)

    def test_write_and_reread(self):
        set_rating(self.audio, 5)
        set_play_count(self.audio, 50)
        self.assertEqual(self.audio.tags["RATING"], ["255"])
        self.assertEqual(self.audio.tags["PLAYCOUNT"], ["50"])
        self.audio.save()

        reread = FLAC(self.filename)
        self.assertEqual(get_rating(reread), 5)
        self.assertEqual(get_play_count(reread), 50)

    def test_repeated_saves_are_stable(self):
        set_rating(self.audio, 3)
        set_play_count(self.audio, 8)
        self.audio.save()
        first = open(self.filename, "rb").read()

        for _ in range(3):
            again = FLAC(self.filename)
            set_rating(again, 3)
            set_play_count(again, 8)
            again.save()
        self.assertEqual(first, open(self.filename, "rb").read())

        final = FLAC(self.filename)
        self.assertEqual(get_rating(final), 3)
        self.assertEqual(get_play_count(final), 8)

    def test_pictures_cuesheet_seektable_unknown_block_survive(self):
        set_rating(self.audio, 2)
        self.audio.save()
        reread = FLAC(self.filename)

        self.assertEqual(len(reread.pictures), 2)
        self.assertEqual(
            [p.mime for p in reread.pictures], ["image/png", "image/png"])
        self.assertEqual(len(reread.cuesheet.tracks), 4)
        self.assertEqual(len(reread.seektable.seekpoints), 6)
        unknown = [b for b in reread.metadata_blocks if b.code == 7]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].data, b"custom-application-block")
        # ordinary comments survive too
        self.assertEqual(reread.tags["album"], ["Quod Libet Test Data"])

    def test_non_default_owner_rejected(self):
        self.assertRaises(
            RatingError, get_rating, self.audio, u"someone@example.com")
        self.assertRaises(
            RatingError, set_rating, self.audio, 3, u"someone@example.com")
        self.assertRaises(
            RatingError, set_play_count, self.audio, 1,
            u"someone@example.com")
        self.assertRaises(
            RatingError, delete_rating, self.audio, u"someone@example.com")

    def test_conflicting_comments_raise_on_read(self):
        self.audio.tags["RATING"] = ["100", "200"]
        self.assertRaises(RatingError, get_rating, self.audio)
        self.audio.tags["PLAYCOUNT"] = ["1", "2"]
        self.assertRaises(RatingError, get_play_count, self.audio)

    def test_conflicting_comments_normalized_on_write(self):
        self.audio.tags["RATING"] = ["100", "200"]
        set_rating(self.audio, 1)
        self.assertEqual(self.audio.tags["RATING"], ["51"])
        self.assertEqual(get_rating(self.audio), 1)

    def test_out_of_range_rating_comment(self):
        self.audio.tags["RATING"] = ["256"]
        self.assertRaises(RatingError, get_rating, self.audio)
        self.audio.tags["RATING"] = ["99999"]
        self.assertRaises(RatingError, get_rating, self.audio)

    def test_malformed_rating_text(self):
        for bad in [u"", u" ", u"0x10", u"1.5", u"-1", u" 5", u"5 ",
                    u"+5", u"ff", u"1,000", u"²³", u"１２"]:
            self.audio.tags["RATING"] = [bad]
            self.assertRaises(RatingError, get_rating, self.audio)

    def test_malformed_playcount_text(self):
        for bad in [u"", u"1.0", u"-1", u"0x10", u" 3", u"3 "]:
            self.audio.tags["PLAYCOUNT"] = [bad]
            self.assertRaises(RatingError, get_play_count, self.audio)

    def test_zero_rating_and_count_are_present(self):
        set_rating(self.audio, 0)
        set_play_count(self.audio, 0)
        self.assertEqual(get_rating(self.audio), 0)
        self.assertEqual(get_play_count(self.audio), 0)
        self.assertEqual(self.audio.tags["RATING"], ["0"])
        self.assertEqual(self.audio.tags["PLAYCOUNT"], ["0"])

    def test_missing_comments_return_none(self):
        del self.audio.tags["RATING"]
        del self.audio.tags["PLAYCOUNT"]
        self.assertTrue(get_rating(self.audio) is None)
        self.assertTrue(get_play_count(self.audio) is None)

    def test_delete(self):
        self.assertTrue(delete_rating(self.audio))
        self.assertFalse("RATING" in self.audio.tags)
        self.assertFalse("PLAYCOUNT" in self.audio.tags)
        self.assertFalse(delete_rating(self.audio))

    def test_set_validation(self):
        self.assertRaises(ValueError, set_rating, self.audio, -1)
        self.assertRaises(ValueError, set_rating, self.audio, 6)
        self.assertRaises(TypeError, set_rating, self.audio, 2.0)
        self.assertRaises(ValueError, set_play_count, self.audio, -5)
        self.assertRaises(TypeError, set_play_count, self.audio, 1.2)

    def test_bare_vcomment_object(self):
        tags = self.audio.tags
        set_rating(tags, 2)
        self.assertEqual(get_rating(tags), 2)
        set_play_count(tags, 4)
        self.assertEqual(get_play_count(tags), 4)


class TNoTags(TestCase):

    def test_mp3_without_tags(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.mp3"))
        try:
            audio = MP3(filename)
            self.assertTrue(audio.tags is None)
            self.assertRaises(
                RatingError, get_rating, audio)
            self.assertRaises(
                RatingError, set_rating, audio, 3)
            self.assertRaises(
                RatingError, set_play_count, audio, 1)
        finally:
            os.unlink(filename)

    def test_flac_without_comment_block(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.flac"))
        try:
            audio = FLAC(filename)
            self.assertTrue(audio.tags is None)
            self.assertRaises(RatingError, get_rating, audio)
            self.assertRaises(RatingError, set_rating, audio, 3)
        finally:
            os.unlink(filename)

    def test_unsupported_object(self):
        self.assertRaises(RatingError, get_rating, object())
        self.assertRaises(RatingError, set_rating, object(), 3)

    def test_empty_file(self):
        filename = get_temp_empty(".mp3")
        try:
            self.assertRaises(RatingError, get_rating, filename)
        finally:
            os.unlink(filename)

    def test_mp3_add_tags_workflow(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.mp3"))
        try:
            audio = MP3(filename)
            audio.add_tags()
            set_rating(audio, 3, ALICE)
            set_play_count(audio, 5, ALICE)
            audio.save()
            reread = MP3(filename)
            self.assertEqual(get_rating(reread, ALICE), 3)
            self.assertEqual(get_play_count(reread, ALICE), 5)
        finally:
            os.unlink(filename)

    def test_flac_add_tags_workflow(self):
        filename = get_temp_copy(
            os.path.join(DATA_DIR, "no-tags.flac"))
        try:
            audio = FLAC(filename)
            audio.add_tags()
            set_rating(audio, 4)
            set_play_count(audio, 9)
            audio.save()
            reread = FLAC(filename)
            self.assertEqual(get_rating(reread), 4)
            self.assertEqual(get_play_count(reread), 9)
        finally:
            os.unlink(filename)


class TID3v23Compat(TestCase):

    def test_popm_survives_v23_save(self):
        filename = get_temp_copy(MP3_FIXTURE)
        try:
            tags = ID3(filename)
            set_rating(tags, 5, ALICE)
            set_play_count(tags, 1_000_000, ALICE)
            tags.update_to_v23()
            tags.save(v2_version=3)

            reread = ID3(filename)
            self.assertEqual(reread.version[:2], (2, 3))
            self.assertEqual(get_rating(reread, ALICE), 5)
            self.assertEqual(get_play_count(reread, ALICE), 1_000_000)
            # the second owner survived the version conversion
            self.assertEqual(get_rating(reread, BOB), 2)
        finally:
            os.unlink(filename)


class TCrossFormatEquivalence(TestCase):
    """The same stars/counts must survive an MP3 -> FLAC style sync."""

    def _mp3_copy(self):
        filename = get_temp_copy(MP3_FIXTURE)
        self.addCleanup(os.unlink, filename)
        return MP3(filename)

    def _flac_copy(self):
        filename = get_temp_copy(FLAC_FIXTURE)
        self.addCleanup(os.unlink, filename)
        return FLAC(filename)

    def test_same_wire_values(self):
        mp3 = self._mp3_copy()
        flac = self._flac_copy()
        for stars in range(6):
            set_rating(mp3, stars, ALICE)
            set_rating(flac, stars)
            self.assertEqual(
                mp3.tags["POPM:" + ALICE].rating,
                int(flac.tags["RATING"][0]))

    def test_sync_round_trip(self):
        mp3 = self._mp3_copy()
        flac = self._flac_copy()
        # simulate a player copying alice's data to the FLAC default user
        stars = get_rating(mp3, ALICE)
        count = get_play_count(mp3, ALICE)
        set_rating(flac, stars)
        set_play_count(flac, count)
        flac.save()

        reread = FLAC(flac.filename)
        self.assertEqual(get_rating(reread), get_rating(mp3, ALICE))
        self.assertEqual(get_play_count(reread),
                         get_play_count(mp3, ALICE))
