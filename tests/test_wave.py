
import os
import hashlib
import struct
from io import BytesIO
from unittest import mock

import mutagen
import mutagen.wave

from mutagen.wave import WAVE, RiffInfo, InfoTags, InfoError, INFO_TAG_NAMES
from mutagen._iff import InvalidChunk
from tests import TestCase, DATA_DIR, get_temp_copy


class TWave(TestCase):
    def test_score_requires_wave_form(self):
        for form, filename in [(b"WEBP", "cover.webp"), (b"AVI ", "video.avi")]:
            header = b"RIFF\x08\x00\x00\x00" + form
            with self.subTest(form=form):
                self.assertEqual(WAVE.score(filename, BytesIO(header), header), 0)
                self.assertIsNone(mutagen.File(BytesIO(header)))

    def test_score_wave_header_and_extensions(self):
        header = b"RIFF\x08\x00\x00\x00WAVE"
        self.assertEqual(WAVE.score("audio", BytesIO(header), header), 2)
        for filename in ("audio.wav", "audio.WAVE"):
            with self.subTest(filename=filename):
                self.assertEqual(WAVE.score(filename, BytesIO(header), header), 3)
                self.assertEqual(WAVE.score(filename, BytesIO(), b""), 1)
        for header in (b"", b"RIFF", b"RIFF\x08\x00\x00\x00WA",
                       b"xxxx\x00\x00\x00\x00WAVE"):
            with self.subTest(header=header):
                self.assertEqual(WAVE.score("audio", BytesIO(header), header), 0)

    def setUp(self):
        fn_wav_pcm_2s_16000_08_id3v23 = \
            os.path.join(DATA_DIR, "silence-2s-PCM-16000-08-ID3v23.wav")
        self.wav_pcm_2s_16000_08_ID3v23 = \
            WAVE(fn_wav_pcm_2s_16000_08_id3v23)

        self.tmp_fn_pcm_2s_16000_08_ID3v23 = \
            get_temp_copy(fn_wav_pcm_2s_16000_08_id3v23)
        self.tmp_wav_pcm_2s_16000_08_ID3v23 = \
            WAVE(self.tmp_fn_pcm_2s_16000_08_ID3v23)

        self.fn_wav_pcm_2s_16000_08_notags = \
            os.path.join(DATA_DIR, "silence-2s-PCM-16000-08-notags.wav")
        self.wav_pcm_2s_16000_08_notags = \
            WAVE(self.fn_wav_pcm_2s_16000_08_notags)

        self.tmp_fn_pcm_2s_16000_08_notag = \
            get_temp_copy(self.fn_wav_pcm_2s_16000_08_notags)
        self.tmp_wav_pcm_2s_16000_08_notag = \
            WAVE(self.tmp_fn_pcm_2s_16000_08_notag)

        fn_wav_pcm_2s_44100_16_id3v23 = \
            os.path.join(DATA_DIR, "silence-2s-PCM-44100-16-ID3v23.wav")
        self.wav_pcm_2s_44100_16_ID3v23 = WAVE(fn_wav_pcm_2s_44100_16_id3v23)

    def test_channels(self):
        self.failUnlessEqual(self.wav_pcm_2s_16000_08_ID3v23.info.channels, 2)
        self.failUnlessEqual(self.wav_pcm_2s_44100_16_ID3v23.info.channels, 2)

    def test_sample_rate(self):
        self.failUnlessEqual(self.wav_pcm_2s_16000_08_ID3v23.info.sample_rate,
                             16000)
        self.failUnlessEqual(self.wav_pcm_2s_44100_16_ID3v23.info.sample_rate,
                             44100)

    def test_number_of_samples(self):
        self.failUnlessEqual(self.wav_pcm_2s_16000_08_ID3v23.
                             info._number_of_samples, 32000)
        self.failUnlessEqual(self.wav_pcm_2s_44100_16_ID3v23.
                             info._number_of_samples, 88200)

    def test_bits_per_sample(self):
        self.failUnlessEqual(self.wav_pcm_2s_16000_08_ID3v23.
                             info.bits_per_sample, 8)
        self.failUnlessEqual(self.wav_pcm_2s_44100_16_ID3v23.
                             info.bits_per_sample, 16)

    def test_bitrate(self):
        self.failUnlessEqual(self.wav_pcm_2s_16000_08_ID3v23.
                             info.bitrate, 256000)
        self.failUnlessEqual(self.wav_pcm_2s_44100_16_ID3v23.
                             info.bitrate, 1411200)

    def test_length(self):
        self.failUnlessAlmostEqual(self.wav_pcm_2s_16000_08_ID3v23.info.length,
                                   2.0, 2)
        self.failUnlessAlmostEqual(self.wav_pcm_2s_44100_16_ID3v23.info.length,
                                   2.0, 2)

    def test_not_my_file(self):
        self.failUnlessRaises(
            InvalidChunk, WAVE, os.path.join(DATA_DIR, "empty.ogg"))

    def test_pprint(self):
        self.wav_pcm_2s_44100_16_ID3v23.pprint()

    def test_mime(self):
        self.failUnless("audio/wav" in self.wav_pcm_2s_44100_16_ID3v23.mime)
        self.failUnless("audio/wave" in self.wav_pcm_2s_44100_16_ID3v23.mime)

    def test_id3_tags(self):
        id3 = self.wav_pcm_2s_44100_16_ID3v23.tags
        self.assertEquals(id3["TALB"], "Quod Libet Test Data")
        self.assertEquals(id3["TCON"], "Silence")
        self.assertEquals(id3["TIT2"], "Silence")
        self.assertEquals(id3["TPE1"], ["piman / jzig"])

    def test_id3_tags_uppercase_chunk(self):
        id3 = self.wav_pcm_2s_16000_08_ID3v23
        self.assertEquals(id3["TALB"], "Quod Libet Test Data")
        self.assertEquals(id3["TCON"], "Silence")
        self.assertEquals(id3["TIT2"], "Silence")
        self.assertEquals(id3["TPE1"], ["piman / jzig"])

    def test_delete(self):
        self.tmp_wav_pcm_2s_16000_08_ID3v23.delete()

        self.failIf(self.tmp_wav_pcm_2s_16000_08_ID3v23.tags)
        self.failUnless(WAVE(self.tmp_fn_pcm_2s_16000_08_ID3v23).tags is None)

    def test_save_no_tags(self):
        self.tmp_wav_pcm_2s_16000_08_ID3v23.tags = None
        self.tmp_wav_pcm_2s_16000_08_ID3v23.save()
        self.assertTrue(self.tmp_wav_pcm_2s_16000_08_ID3v23.tags is None)

    def test_add_tags_already_there(self):
        self.failUnless(self.tmp_wav_pcm_2s_16000_08_ID3v23.tags)
        self.failUnlessRaises(Exception,
                              self.tmp_wav_pcm_2s_16000_08_ID3v23.add_tags)

    def test_roundtrip(self):
        self.failUnlessEqual(self.tmp_wav_pcm_2s_16000_08_ID3v23["TIT2"],
                             ["Silence"])
        self.tmp_wav_pcm_2s_16000_08_ID3v23.save()
        new = WAVE(self.tmp_wav_pcm_2s_16000_08_ID3v23.filename)
        self.failUnlessEqual(new["TIT2"], ["Silence"])

    def test_save_tags(self):
        from mutagen.id3 import TIT1
        tags = self.tmp_wav_pcm_2s_16000_08_ID3v23.tags
        tags.add(TIT1(encoding=3, text="foobar"))
        tags.save()

        new = WAVE(self.tmp_wav_pcm_2s_16000_08_ID3v23.filename)
        self.failUnlessEqual(new["TIT1"], ["foobar"])

    """" Simulate the way Picard writes and update tags """
    def test_picard_lifecycle(self):
        path_tmp_wav_file = \
            get_temp_copy(self.fn_wav_pcm_2s_16000_08_notags)
        from mutagen.id3 import ID3
        wav = WAVE(path_tmp_wav_file)
        id3 = wav.tags
        """" Picard WaveFile._get_tags: """
        self.assertIsNone(id3, "Ensure ID3-tag-header does not exist")
        """" Picard WaveFile._get_tags: initialize tags """
        wav.add_tags()
        id3 = wav.tags
        self.assertIsInstance(id3, ID3)
        """ ID3v2.3 separator """
        separator = '/'
        """ Initialize Picard like metadata tags """
        self.__init_id3_tags(id3, major=3)
        """ Write the Picard like metadata to the empty WAVE-file """
        id3.save(path_tmp_wav_file, v23_sep=separator)
        """ Tags (metadata) have been added; now load the file again """
        wav = WAVE(path_tmp_wav_file)
        id3 = wav.tags
        self.assertIsInstance(id3, ID3)
        self.assertEquals(id3["TRCK"], "1/10")
        self.assertEquals(id3["TPOS"], "1/1")
        self.assertEquals(id3["TXXX:MusicBrainz Release Group Id"],
                          "e00305af-1c72-469b-9a7c-6dc665ca9adc")
        self.assertEquals(id3["TXXX:MusicBrainz Album Artist Id"], [
                          "3fe817fc-966e-4ece-b00a-76be43e7e73c",
                          "984f8239-8fe1-4683-9c54-10ffb14439e9"])
        self.assertEquals(id3["TXXX:CATALOGNUMBER"], ["PRAR931391"])
        self.assertEquals(id3["TSRC"], ["NLB931100460", "USMH51100098"])

    @staticmethod
    def __init_id3_tags(id3, major=3):
        """
        Attributes:
            id3 ID3 Tag object
            major ID3 major version, e.g.: 3 for ID3v2.3
        """
        from mutagen.id3 import TRCK, TPOS, TXXX, TPUB, TALB, UFID, TPE2, \
            TSO2, TMED, TIT2, TPE1, TSRC, IPLS, TORY, TDAT, TYER
        id3.add(TRCK(encoding=major, text="1/10"))
        id3.add(TPOS(encoding=major, text="1/1"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Release Group Id",
                     text="e00305af-1c72-469b-9a7c-6dc665ca9adc"))
        id3.add(TXXX(encoding=major, desc="originalyear", text="2011"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Album Type",
                     text="album"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Album Id",
                     text="e7050302-74e6-42e4-aba0-09efd5d431d8"))
        id3.add(TPUB(encoding=major, text="J&R Adventures"))
        id3.add(TXXX(encoding=major, desc="CATALOGNUMBER", text="PRAR931391"))
        id3.add(TALB(encoding=major, text="Don\'t Explain"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Album Status",
                     text="official"))
        id3.add(TXXX(encoding=major, desc="SCRIPT", text="Latn"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Album Release Country",
                     text="US"))
        id3.add(TXXX(encoding=major, desc="BARCODE", text="804879313915"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Album Artist Id",
                     text=[
                        "3fe817fc-966e-4ece-b00a-76be43e7e73c",
                        "984f8239-8fe1-4683-9c54-10ffb14439e9"]))
        id3.add(TPE2(encoding=major, text="Beth Hart & Joe Bonamassa"))
        id3.add(TSO2(encoding=major, text="Hart, Beth & Bonamassa, Joe"))
        id3.add(TXXX(encoding=major, desc="ASIN", text="B005NPEUB2"))
        id3.add(TMED(encoding=major, text="CD"))
        id3.add(UFID(encoding=major, owner="http://musicbrainz.org",
                     data=b"f151cb94-c909-46a8-ad99-fb77391abfb8"))
        id3.add(TIT2(encoding=major, text="Sinner's Prayer"))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Artist Id",
                     text=[
                        "3fe817fc-966e-4ece-b00a-76be43e7e73c",
                        "984f8239-8fe1-4683-9c54-10ffb14439e9"]))
        id3.add(TPE1(encoding=major, text=["Beth Hart & Joe Bonamassa"]))
        id3.add(TXXX(encoding=major, desc="Artists",
                     text=["Beth Hart", "Joe Bonamassa"]))
        id3.add(TSRC(encoding=major, text=["NLB931100460", "USMH51100098"]))
        id3.add(TXXX(encoding=major, desc="MusicBrainz Release Track Id",
                     text="d062f484-253c-374b-85f7-89aab45551c7"))
        id3.add(IPLS(encoding=major, people=[
            ["engineer", "James McCullagh"],
            ["engineer", "Jared Kvitka"],
            ["arranger", "Jeff Bova"],
            ["producer", "Roy Weisman"],
            ["piano", "Beth Hart"],
            ["guitar", "Blondie Chaplin"],
            ["guitar", "Joe Bonamassa"],
            ["percussion", "Anton Fig"],
            ["drums", "Anton Fig"],
            ["keyboard", "Arlan Schierbaum"],
            ["bass guitar", "Carmine Rojas"],
            ["orchestra", "The Bovaland Orchestra"],
            ["vocals", "Beth Hart"],
            ["vocals", "Joe Bonamassa"]])),
        id3.add(TORY(encoding=major, text="2011"))
        id3.add(TYER(encoding=major, text="2011"))
        id3.add(TDAT(encoding=major, text="2709"))


# --- RIFF LIST/INFO tags ---------------------------------------------------

INFO_FIXTURE = os.path.join(
    DATA_DIR, "pattern-2s-PCM-16000-08-INFO-ID3.wav")
# SHA-256 of the PCM audio payload (the "data" chunk) of INFO_FIXTURE.
INFO_FIXTURE_PCM_SHA256 = (
    "70bb26dddde70aa2297818caf8d7527c2a794c2b9ab40bb977af7ec71bbb1638")
INFO_FIXTURE_PCM_SIZE = 64000

_FMT_PCM = struct.pack("<HHLLHH", 1, 1, 8000, 8000, 1, 8)


def _riff_chunk(cid, payload):
    data = cid + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        data += b"\x00"
    return data


def make_wav(chunks):
    """Build a RIFF/WAVE file from ``(id, payload)`` chunks."""

    body = b"WAVE" + b"".join(_riff_chunk(cid, data) for cid, data in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def make_info(entries):
    """Build a LIST/INFO payload from ``(id, raw value)`` pairs."""

    body = bytearray(b"INFO")
    for cid, value in entries:
        body += cid + struct.pack("<I", len(value)) + value
        if len(value) & 1:
            body += b"\x00"
    return bytes(body)


def iter_top_chunks(data):
    """Yield ``(id, data, offset)`` for the top level RIFF chunks."""

    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        payload = data[pos + 8:pos + 8 + size]
        yield cid, payload, pos
        pos += 8 + size + (size & 1)


def get_chunk(data, cid):
    for chunk_id, payload, offset in iter_top_chunks(data):
        if chunk_id == cid:
            return payload, offset
    raise AssertionError("no %r chunk in %r" % (cid, data[:16]))


def pcm_sha256(data):
    payload, _ = get_chunk(data, b"data")
    return hashlib.sha256(payload).hexdigest()


class TInfoTags(TestCase):
    """RIFF LIST/INFO read/write support for WAVE files."""

    def setUp(self):
        self.fn = get_temp_copy(INFO_FIXTURE)

    def tearDown(self):
        os.unlink(self.fn)

    def reload(self):
        return WAVE(self.fn)

    def read_bytes(self):
        with open(self.fn, "rb") as h:
            return h.read()

    def write_bytes(self, data):
        with open(self.fn, "wb") as h:
            h.write(data)

    def test_fixture_pcm_hash(self):
        data = self.read_bytes()
        self.assertEqual(pcm_sha256(data), INFO_FIXTURE_PCM_SHA256)
        self.assertEqual(len(get_chunk(data, b"data")[0]),
                         INFO_FIXTURE_PCM_SIZE)

    def test_read_common_keys(self):
        tags = self.reload().info_tags
        self.assertEqual(tags["INAM"], "Fixture Title")
        self.assertEqual(tags["IART"], "Fixture Artist")
        self.assertEqual(tags["IPRD"], "Fixture Album")
        self.assertEqual(tags["IGNR"], "Test Tone")
        self.assertEqual(tags["ITRK"], "07")
        self.assertEqual(tags["ICRD"], "2024")
        self.assertFalse(tags.truncated)

    def test_read_unknown_keys(self):
        tags = self.reload().info_tags
        # Unknown text key is exposed by its raw four character code.
        self.assertEqual(tags["XCMT"], "Custom note")
        self.assertIn("XCMT", tags)
        self.assertNotIn("XCMT", INFO_TAG_NAMES)
        # Non-text bytes are kept verbatim and are still addressable.
        self.assertEqual(tags.get_raw("XRAW"), b"\x00\x01\xfe\xff\x10")
        self.assertIn("XRAW", tags.keys())

    def test_read_raw_items(self):
        tags = self.reload().info_tags
        raw = dict(tags.raw_items())
        self.assertEqual(raw["INAM"], b"Fixture Title\x00")
        self.assertEqual(raw["XRAW"], b"\x00\x01\xfe\xff\x10")
        # Keys are in file order.
        self.assertEqual(tags.keys(),
                         ["IPRD", "IART", "IGNR", "INAM", "ITRK", "ICRD",
                          "XCMT", "XRAW"])

    def test_info_and_id3_coexist(self):
        wave_file = self.reload()
        self.assertEqual(wave_file.tags["TIT2"], "ID3 Title")
        self.assertEqual(wave_file.tags["TPE1"], ["ID3 Artist"])
        self.assertEqual(wave_file.info_tags["INAM"], "Fixture Title")
        # Distinct values, so neither tag shadows the other.
        self.assertNotEqual(wave_file.tags["TIT2"],
                            wave_file.info_tags["INAM"])

    def test_standalone_riff_info(self):
        tags = RiffInfo(INFO_FIXTURE)
        self.assertEqual(tags["INAM"], "Fixture Title")
        self.assertEqual(len(tags), 8)
        self.assertEqual(tags.filename, INFO_FIXTURE)
        self.assertIs(InfoTags, RiffInfo)
        self.assertEqual(tags.getall("INAM"), ["Fixture Title"])

    def test_add_replace_delete_roundtrip(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "Edited Title"
        wave_file.info_tags["ICMT"] = "A new comment"
        del wave_file.info_tags["IGNR"]
        wave_file.info_tags.save()

        reloaded = self.reload().info_tags
        self.assertEqual(reloaded["INAM"], "Edited Title")
        self.assertEqual(reloaded["ICMT"], "A new comment")
        self.assertNotIn("IGNR", reloaded)
        # Untouched values and the non-text key survive.
        self.assertEqual(reloaded["IART"], "Fixture Artist")
        self.assertEqual(reloaded["XRAW"], "\x00\x01þÿ\x10")
        self.assertEqual(reloaded.get_raw("XRAW"), b"\x00\x01\xfe\xff\x10")

    def test_save_through_wave(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "Title via WAVE.save"
        wave_file.save()
        self.assertEqual(self.reload().info_tags["INAM"],
                         "Title via WAVE.save")

    def test_id3_not_overwritten_by_info_save(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "New INFO"
        wave_file.info_tags.save()

        reloaded = self.reload()
        self.assertEqual(reloaded.tags["TIT2"], "ID3 Title")
        self.assertEqual(reloaded.tags["TPE1"], ["ID3 Artist"])
        self.assertEqual(reloaded.info_tags["INAM"], "New INFO")

    def test_info_not_overwritten_by_id3_save(self):
        from mutagen.id3 import TIT2

        wave_file = self.reload()
        wave_file.tags.add(TIT2(encoding=3, text="Changed ID3"))
        wave_file.tags.save()

        reloaded = self.reload()
        self.assertEqual(reloaded.tags["TIT2"], "Changed ID3")
        self.assertEqual(reloaded.info_tags["INAM"], "Fixture Title")
        self.assertEqual(reloaded.info_tags["XCMT"], "Custom note")

    def test_save_preserves_audio_and_id3(self):
        original = self.read_bytes()
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "Preserved audio"
        wave_file.info_tags.save()
        after = self.read_bytes()

        self.assertEqual(pcm_sha256(after), INFO_FIXTURE_PCM_SHA256)
        self.assertEqual(get_chunk(after, b"data")[0],
                         get_chunk(original, b"data")[0])
        self.assertEqual(get_chunk(after, b"ID3 ")[0],
                         get_chunk(original, b"ID3 ")[0])

    def test_save_recomputes_sizes_and_padding(self):
        wave_file = self.reload()
        # "odd length" is 10 bytes + NUL, so the sub chunk is even; use a
        # value with an odd raw length to force sub chunk padding, and the
        # total LIST size is forced odd by adding an odd length entry.
        wave_file.info_tags["ICMT"] = "odd length"
        wave_file.info_tags["IKEY"] = "k"
        wave_file.info_tags.save()
        data = self.read_bytes()

        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

        list_payload, list_offset = get_chunk(data, b"LIST")
        list_size = struct.unpack(
            "<I", data[list_offset + 4:list_offset + 8])[0]
        self.assertEqual(list_size, len(list_payload))
        # The INFO type and every sub chunk are even, so the LIST data is
        # always even and needs no padding of its own.
        self.assertEqual(list_size & 1, 0)
        self.assertEqual(
            data[list_offset + 8 + list_size:
                 list_offset + 12 + list_size], b"ID3 ")
        # Locate the edited sub chunks and verify sizes and padding.
        pos = list_payload.index(b"ICMT")
        sub_size = struct.unpack("<I", list_payload[pos + 4:pos + 8])[0]
        self.assertEqual(sub_size, len("odd length") + 1)
        self.assertEqual(
            list_payload[pos + 8 + sub_size:pos + 9 + sub_size], b"\x00")
        pos = list_payload.index(b"IKEY")
        sub_size = struct.unpack("<I", list_payload[pos + 4:pos + 8])[0]
        # "k" plus its NUL terminator is even and needs no padding.
        self.assertEqual(sub_size, 2)
        self.assertEqual(
            list_payload[pos + 8 + sub_size:pos + 9 + sub_size], b"")

    def test_chunk_order_is_kept(self):
        before = [cid for cid, _, _ in iter_top_chunks(self.read_bytes())]
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "reordered?"
        wave_file.info_tags.save()
        after = [cid for cid, _, _ in iter_top_chunks(self.read_bytes())]
        self.assertEqual(before, after)

    def test_add_info_to_file_without_list(self):
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
        ]))
        wave_file = self.reload()
        self.assertEqual(wave_file.info_tags.keys(), [])
        wave_file.info_tags["INAM"] = "Created"
        wave_file.info_tags.save()

        reloaded = self.reload()
        self.assertEqual(reloaded.info_tags["INAM"], "Created")
        self.assertEqual(pcm_sha256(self.read_bytes()),
                         hashlib.sha256(b"\x80" * 64).hexdigest())

    def test_remove_empty_info_chunk(self):
        wave_file = self.reload()
        wave_file.info_tags.clear()
        wave_file.info_tags.save()

        data = self.read_bytes()
        self.assertNotIn(b"INFO", [cid for cid in
                                   (c for c, _, _ in iter_top_chunks(data))])
        self.assertNotIn(b"LIST", data)
        self.assertEqual(self.reload().info_tags.keys(), [])
        # The ID3 chunk is still there.
        self.assertEqual(self.reload().tags["TIT2"], "ID3 Title")

    def test_duplicate_keys(self):
        payload = make_info([
            (b"INAM", b"first\x00"),
            (b"ICMT", b"keep\x00"),
            (b"INAM", b"second\x00"),
        ])
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))
        tags = self.reload().info_tags
        # Mapping access returns the last value; getall keeps file order.
        self.assertEqual(tags["INAM"], "second")
        self.assertEqual(tags.getall("INAM"), ["first", "second"])
        self.assertEqual([key for key, _ in tags.raw_items()],
                         ["INAM", "ICMT", "INAM"])
        self.assertEqual(tags.keys(), ["INAM", "ICMT"])

        # Replacing collapses the duplicates into one entry.
        tags["INAM"] = "merged"
        tags.save()
        reloaded = self.reload().info_tags
        self.assertEqual(reloaded.getall("INAM"), ["merged"])
        self.assertEqual(reloaded["ICMT"], "keep")
        self.assertEqual(reloaded.raw_items(),
                         [("INAM", b"merged\x00"), ("ICMT", b"keep\x00")])

    def test_delete_removes_all_duplicates(self):
        payload = make_info([
            (b"INAM", b"one\x00"),
            (b"INAM", b"two\x00"),
        ])
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))
        tags = self.reload().info_tags
        del tags["INAM"]
        tags.save()
        self.assertNotIn("INAM", self.reload().info_tags)

    def test_missing_key_raises(self):
        tags = self.reload().info_tags
        for method in ("getall", "get_raw", "getall_raw"):
            with self.subTest(method=method):
                with self.assertRaises(KeyError):
                    getattr(tags, method)("ZZZZ")
        with self.assertRaises(KeyError):
            tags["ZZZZ"]
        with self.assertRaises(KeyError):
            del tags["ZZZZ"]

    def test_getall_raw(self):
        tags = self.reload().info_tags
        self.assertEqual(tags.getall_raw("INAM"), [b"Fixture Title\x00"])
        self.assertEqual(tags.getall_raw("XRAW"), [b"\x00\x01\xfe\xff\x10"])

    def test_bytes_key(self):
        tags = self.reload().info_tags
        self.assertEqual(tags[b"INAM"], "Fixture Title")
        tags[b"ICMT"] = b"raw bytes"
        self.assertEqual(tags["ICMT"], "raw bytes")
        del tags[b"ICMT"]
        self.assertNotIn("ICMT", tags)

    def test_bytearray_value(self):
        tags = self.reload().info_tags
        tags["ICMT"] = bytearray(b"mutable\x00")
        self.assertEqual(tags.get_raw("ICMT"), b"mutable\x00")

    def test_invalid_key_rejected(self):
        tags = self.reload().info_tags
        for key in ("TOOLONG", "abc", "", "IN\x01M", "éééé"):
            with self.subTest(key=key):
                with self.assertRaises((ValueError, KeyError)):
                    tags[key] = "value"
                with self.assertRaises((ValueError, KeyError)):
                    tags[key]
        with self.assertRaises(TypeError):
            tags[42] = "value"

    def test_invalid_value_rejected(self):
        tags = self.reload().info_tags
        with self.assertRaises(TypeError):
            tags["INAM"] = 42
        with self.assertRaises(TypeError):
            tags["INAM"] = ["a", "b"]

    def test_oversized_value_rejected_before_write(self):
        wave_file = self.reload()
        before = self.read_bytes()
        # Simulate a 32 bit size overflow without allocating the data.
        with mock.patch.object(mutagen.wave, "_MAX_CHUNK_SIZE", 16):
            with self.assertRaises(InfoError):
                wave_file.info_tags["INAM"] = "x" * 64
        # Validation happens on assignment, so the file is untouched.
        self.assertEqual(self.read_bytes(), before)

    def test_oversize_is_reported_by_save(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "x" * 64
        before = self.read_bytes()
        # Values added behind the mapping's back are still validated by
        # save, which must refuse without modifying the file.
        with mock.patch.object(mutagen.wave, "_MAX_CHUNK_SIZE", 16):
            with self.assertRaises(InfoError):
                wave_file.info_tags.save()
        self.assertEqual(self.read_bytes(), before)

    def test_non_ascii_key_preserved(self):
        # Chunk codes in the wild are not always ASCII. They can be read
        # and written back, but not created through the mapping.
        key = "\xff\x01AB"
        payload = (b"INFO" + key.encode("latin-1")
                   + struct.pack("<I", 4) + b"data"
                   + b"INAM" + struct.pack("<I", 2) + b"ok")
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))
        tags = self.reload().info_tags
        self.assertEqual(tags.keys(), [key, "INAM"])
        self.assertEqual(tags.get_raw(key), b"data")

        tags["IART"] = "new"
        tags.save()
        reloaded = self.reload().info_tags
        self.assertEqual(reloaded.get_raw(key), b"data")
        self.assertEqual(reloaded["IART"], "new")
        # Existing unknown keys can be replaced, but new non printable
        # codes can not be created.
        reloaded[key] = "replaced"
        self.assertEqual(reloaded.get_raw(key), b"replaced\x00")
        with self.assertRaises(ValueError):
            reloaded["\xff\x01ZZ"] = "cannot create"

    def test_non_text_bytes_roundtrip(self):
        wave_file = self.reload()
        self.assertEqual(wave_file.info_tags.get_raw("XRAW"),
                         b"\x00\x01\xfe\xff\x10")
        wave_file.info_tags.save()
        self.assertEqual(self.reload().info_tags.get_raw("XRAW"),
                         b"\x00\x01\xfe\xff\x10")

    def test_invalid_utf8_value_roundtrip(self):
        payload = make_info([(b"ICMT", b"caf\xe9\x00")])
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))
        tags = self.reload().info_tags
        # Latin-1 decoding keeps every byte addressable.
        self.assertEqual(tags["ICMT"], "café")
        tags.save()
        self.assertEqual(self.reload().info_tags.get_raw("ICMT"),
                         b"caf\xe9\x00")

    def test_truncated_list_declared_size(self):
        payload = b"INFO" + b"INAM" + struct.pack("<I", 100) + b"short"
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))

        wave_file = self.reload()
        self.assertTrue(wave_file.info_tags.truncated)
        # Whatever bytes are present are kept.
        self.assertEqual(wave_file.info_tags["INAM"], "short")
        # Saving repairs the sizes; the file is readable afterwards.
        wave_file.info_tags.save()
        reloaded = self.reload()
        self.assertFalse(reloaded.info_tags.truncated)
        self.assertEqual(reloaded.info_tags["INAM"], "short")
        data = self.read_bytes()
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

    def test_truncated_last_subchunk_header(self):
        # The last sub chunk header is cut off inside an intact LIST chunk.
        payload = b"INFO" + make_info([(b"INAM", b"one\x00")])[4:] + b"ICM"
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ]))
        tags = self.reload().info_tags
        self.assertTrue(tags.truncated)
        self.assertEqual(tags["INAM"], "one")
        tags.save()
        self.assertFalse(self.reload().info_tags.truncated)
        self.assertEqual(self.reload().info_tags["INAM"], "one")

    def test_truncated_subchunk_header(self):
        # A LIST/INFO chunk whose declared size extends past the end of the
        # file, with only a partial sub chunk present. The RIFF size matches
        # the actual file length, so only the LIST chunk is inconsistent.
        payload = b"INFO" + b"INAM" + struct.pack("<I", 100)
        body = (b"WAVE" + _riff_chunk(b"fmt ", _FMT_PCM)
                + _riff_chunk(b"data", b"\x80" * 64)
                + b"LIST" + struct.pack("<I", 200) + payload)
        self.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

        tags = self.reload().info_tags
        self.assertTrue(tags.truncated)
        # Only the truncated entry survives, with the bytes that are there.
        self.assertEqual(tags.keys(), ["INAM"])
        self.assertEqual(tags["INAM"], "")
        # Saving repairs the bogus size.
        tags.save()
        self.assertFalse(self.reload().info_tags.truncated)
        data = self.read_bytes()
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

    def test_riff_size_beyond_file(self):
        # A complete INFO chunk, but the RIFF size claims more data than
        # the file holds.
        data = make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", make_info([(b"INAM", b"complete\x00")])),
        ])
        data = bytearray(data)
        data[4:8] = struct.pack("<I", len(data) + 100)
        self.write_bytes(bytes(data))

        tags = self.reload().info_tags
        self.assertTrue(tags.truncated)
        self.assertEqual(tags["INAM"], "complete")
        tags.save()
        data = self.read_bytes()
        self.assertFalse(self.reload().info_tags.truncated)
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

    def test_missing_final_padding(self):
        # An odd sized LIST payload without the required padding byte at the
        # very end of the file.
        info = b"INFO" + b"INAM" + struct.pack("<I", 3) + b"abc"
        body = (b"WAVE" + _riff_chunk(b"fmt ", _FMT_PCM)
                + _riff_chunk(b"data", b"\x80" * 64)
                + b"LIST" + struct.pack("<I", len(info)) + info)
        self.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

        tags = self.reload().info_tags
        self.assertTrue(tags.truncated)
        self.assertEqual(tags["INAM"], "abc")
        tags.save()
        data = self.read_bytes()
        self.assertFalse(self.reload().info_tags.truncated)
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

    def test_truncated_file(self):
        payload = make_info([(b"INAM", b"partial title\x00")])
        data = make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", payload),
        ])
        # Cut the file in the middle of the INFO value.
        self.write_bytes(data[:-6])
        tags = self.reload().info_tags
        self.assertTrue(tags.truncated)
        self.assertEqual(tags["INAM"], "partial ")
        tags.save()
        reloaded = self.reload()
        self.assertFalse(reloaded.info_tags.truncated)
        self.assertEqual(reloaded.info_tags["INAM"], "partial ")
        data = self.read_bytes()
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)

    def test_not_a_riff_file(self):
        self.write_bytes(b"JUNKJUNK")
        with self.assertRaises(Exception):
            RiffInfo(self.fn)

    def test_save_to_readonly_fileobj(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "x"
        with open(self.fn, "rb") as readonly:
            with self.assertRaises(ValueError):
                wave_file.info_tags.save(readonly)

    def test_write_failure_is_reported(self):
        class FailingWrite(BytesIO):
            """A file object whose writes fail after the probe write."""

            def write(self, data):
                if data:
                    raise IOError("disk full")
                return super().write(data)

        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "x"
        with self.assertRaises(InfoError):
            wave_file.info_tags.save(FailingWrite(self.read_bytes()))
        # The original file is untouched.
        self.assertEqual(self.reload().info_tags["INAM"], "Fixture Title")

    def test_fileobj_roundtrip(self):
        buffer = BytesIO(self.read_bytes())
        wave_file = WAVE(buffer)
        wave_file.info_tags["INAM"] = "In memory"
        wave_file.info_tags.save(buffer)

        buffer.seek(0)
        reloaded = WAVE(buffer)
        self.assertEqual(reloaded.info_tags["INAM"], "In memory")
        self.assertEqual(reloaded.info_tags["XRAW"], "\x00\x01þÿ\x10")
        self.assertEqual(pcm_sha256(buffer.getvalue()),
                         INFO_FIXTURE_PCM_SHA256)

    def test_info_tags_present_without_id3(self):
        self.write_bytes(make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", make_info([(b"INAM", b"Only INFO\x00")])),
        ]))
        wave_file = self.reload()
        self.assertIsNone(wave_file.tags)
        self.assertEqual(wave_file.info_tags["INAM"], "Only INFO")

    def test_wave_delete_removes_both(self):
        wave_file = self.reload()
        wave_file.delete()
        reloaded = self.reload()
        self.assertIsNone(reloaded.tags)
        self.assertEqual(reloaded.info_tags.keys(), [])
        data = self.read_bytes()
        self.assertNotIn(b"INFO", data)
        self.assertEqual(pcm_sha256(data), INFO_FIXTURE_PCM_SHA256)

    def test_save_options(self):
        wave_file = self.reload()
        wave_file.info_tags["INAM"] = "info only"
        # Saving only the INFO tags leaves ID3 untouched.
        wave_file.save(id3=False)
        self.assertEqual(self.reload().info_tags["INAM"], "info only")
        self.assertEqual(self.reload().tags["TIT2"], "ID3 Title")

    def test_pprint(self):
        text = self.reload().info_tags.pprint()
        self.assertIn("INAM=Fixture Title", text)
        self.assertIn("XCMT=Custom note", text)

    def test_info_tag_names(self):
        self.assertEqual(INFO_TAG_NAMES["INAM"], "Title")
        self.assertEqual(INFO_TAG_NAMES["IART"], "Artist")
        self.assertEqual(INFO_TAG_NAMES["IPRD"], "Album")

    def test_regular_wav_fixture_still_readable(self):
        fn = os.path.join(DATA_DIR, "silence-2s-PCM-16000-08-ID3v23.wav")
        wave_file = WAVE(fn)
        self.assertEqual(wave_file.info_tags["INAM"], "Silence")
        self.assertEqual(wave_file.info_tags["ITRK"], "02")
        # The existing ID3 data is unaffected.
        self.assertEqual(wave_file.tags["TIT2"], "Silence")

    def test_write_to_notags_fixture(self):
        fn = os.path.join(DATA_DIR, "silence-2s-PCM-16000-08-notags.wav")
        tmp = get_temp_copy(fn)
        try:
            wave_file = WAVE(tmp)
            self.assertEqual(wave_file.info_tags.keys(), [])
            wave_file.info_tags["INAM"] = "Added to bare file"
            wave_file.info_tags.save()
            reloaded = WAVE(tmp)
            self.assertEqual(reloaded.info_tags["INAM"], "Added to bare file")
            self.assertIsNone(reloaded.tags)
        finally:
            os.unlink(tmp)

    def test_multiple_info_chunks_merged(self):
        data = make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", make_info([(b"INAM", b"one\x00")])),
            (b"LIST", make_info([(b"IART", b"two\x00")])),
        ])
        self.write_bytes(data)
        tags = self.reload().info_tags
        self.assertEqual(dict(tags.items()), {"INAM": "one", "IART": "two"})

        tags["ICMT"] = "merged"
        tags.save()
        chunk_ids = [cid for cid, _, _ in iter_top_chunks(self.read_bytes())]
        self.assertEqual(chunk_ids.count(b"LIST"), 1)
        self.assertEqual(dict(self.reload().info_tags.items()),
                         {"INAM": "one", "IART": "two", "ICMT": "merged"})

    def test_trailing_data_preserved(self):
        data = make_wav([
            (b"fmt ", _FMT_PCM),
            (b"data", b"\x80" * 64),
            (b"LIST", make_info([(b"INAM", b"tagged\x00")])),
        ]) + b"TRAILING DATA"
        self.write_bytes(data)

        wave_file = self.reload()
        self.assertEqual(wave_file.info_tags["INAM"], "tagged")
        wave_file.info_tags["INAM"] = "changed"
        wave_file.info_tags.save()

        data = self.read_bytes()
        self.assertTrue(data.endswith(b"TRAILING DATA"))
        self.assertEqual(struct.unpack("<I", data[4:8])[0],
                         len(data) - 8 - len(b"TRAILING DATA"))
        self.assertEqual(self.reload().info_tags["INAM"], "changed")

    def test_list_outside_riff_is_ignored(self):
        body = (b"WAVE" + _riff_chunk(b"fmt ", _FMT_PCM)
                + _riff_chunk(b"data", b"\x80" * 64))
        trailing = (b"LIST" + struct.pack("<I", 18)
                    + make_info([(b"INAM", b"outside\x00")]))
        self.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body
                         + trailing)

        wave_file = self.reload()
        self.assertEqual(wave_file.info_tags.keys(), [])
        wave_file.info_tags["IART"] = "inside"
        wave_file.info_tags.save()
        data = self.read_bytes()
        # The trailing data is neither parsed nor overwritten.
        self.assertTrue(data.endswith(trailing))
        self.assertEqual(self.reload().info_tags["IART"], "inside")

    def test_repeated_saves(self):
        wave_file = self.reload()
        for index in range(3):
            wave_file.info_tags["INAM"] = "pass %d" % index
            wave_file.info_tags.save()
        reloaded = self.reload()
        self.assertEqual(reloaded.info_tags["INAM"], "pass 2")
        self.assertEqual(pcm_sha256(self.read_bytes()),
                         INFO_FIXTURE_PCM_SHA256)
        # Only a single LIST chunk remains.
        chunk_ids = [cid for cid, _, _ in iter_top_chunks(self.read_bytes())]
        self.assertEqual(chunk_ids.count(b"LIST"), 1)
