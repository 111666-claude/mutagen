# Copyright (C) 2026  Christoph Reiter
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import copy
import os
import shutil
import struct

import pytest

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TXXX, APIC
from mutagen.id3 import PictureType
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.tagpatch import (
    PatchConflictError, PatchError, TagPatch, apply_patch, diff_tags,
)

from tests import DATA_DIR


@pytest.fixture
def mp3_path(tmp_path):
    path = str(tmp_path / "test.mp3")
    shutil.copy(os.path.join(DATA_DIR, "silence-44-s.mp3"), path)
    return path


@pytest.fixture
def flac_path(tmp_path):
    path = str(tmp_path / "test.flac")
    shutil.copy(os.path.join(DATA_DIR, "silence-44-s.flac"), path)
    return path


@pytest.fixture
def m4a_path(tmp_path):
    path = str(tmp_path / "test.m4a")
    shutil.copy(os.path.join(DATA_DIR, "has-tags.m4a"), path)
    return path


def make_picture(data=b"\x89PNGfake", mime="image/png"):
    pic = Picture()
    pic.type = 3
    pic.mime = mime
    pic.data = data
    return pic


def op_map(patch):
    return {op.key: op.action for op in patch}


class TestID3Patch(object):

    def test_diff_apply_save_reload(self, mp3_path):
        before = ID3(mp3_path)
        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        del after["TPE1"]
        after.add(TALB(encoding=3, text="New Album"))
        after.add(TXXX(encoding=3, desc="mood", text="happy"))
        after.add(APIC(encoding=3, mime="image/png",
                       type=PictureType.COVER_FRONT, desc="front",
                       data=b"\x89PNG" + b"\x00" * 1000))

        patch = diff_tags(before, after)
        assert patch.format == "id3"
        assert op_map(patch) == {
            "TIT2": "change", "TPE1": "remove", "TALB": "change",
            "TXXX:mood": "add", "APIC:front": "add",
        }
        for op in patch:
            if op.action in ("remove", "change"):
                assert op.old_fp.startswith("sha1:")

        # apply to a freshly read copy of the unchanged file
        fresh = ID3(mp3_path)
        result = apply_patch(fresh, patch)
        assert result.ok
        assert not diff_tags(fresh, after).ops

        fresh.save()
        reloaded = ID3(mp3_path)
        assert not diff_tags(reloaded, after).ops

    def test_merge_no_conflict(self, mp3_path):
        base = ID3(mp3_path)

        organizer = copy.deepcopy(base)
        organizer["TIT2"] = TIT2(encoding=3, text="Organizer Title")
        patch_a = diff_tags(base, organizer)

        player = copy.deepcopy(base)
        player["TALB"] = TALB(encoding=3, text="Player Album")
        patch_b = diff_tags(base, player)

        # the organizer writes first
        tags = ID3(mp3_path)
        apply_patch(tags, patch_a)
        tags.save()

        # the player's patch still applies cleanly afterwards
        tags = ID3(mp3_path)
        result = apply_patch(tags, patch_b)
        assert result.ok
        tags.save()

        final = ID3(mp3_path)
        assert final["TIT2"].text == ["Organizer Title"]
        assert final["TALB"].text == ["Player Album"]

    def test_same_field_conflict(self, mp3_path):
        base = ID3(mp3_path)
        mine = copy.deepcopy(base)
        mine["TIT2"] = TIT2(encoding=3, text="My Title")
        mine["TALB"] = TALB(encoding=3, text="My Album")
        patch = diff_tags(base, mine)

        # someone else changes the same field on disk
        other = ID3(mp3_path)
        other["TIT2"] = TIT2(encoding=3, text="Their Title")
        other.save()

        # strict: nothing is applied, the target is untouched
        fresh = ID3(mp3_path)
        snapshot = diff_tags(fresh, ID3(mp3_path))
        assert not snapshot.ops
        with pytest.raises(PatchConflictError) as excinfo:
            apply_patch(fresh, patch)
        assert [c.key for c in excinfo.value.conflicts] == ["TIT2"]
        assert not diff_tags(fresh, ID3(mp3_path)).ops
        assert fresh["TIT2"].text == ["Their Title"]
        assert fresh["TALB"].text == ["Quod Libet Test Data"]

        # non-strict: the conflicting op is skipped, the rest applied
        result = apply_patch(fresh, patch, strict=False)
        assert not result.ok
        assert [c.key for c in result.conflicts] == ["TIT2"]
        assert result.applied == ["TALB"]
        assert fresh["TIT2"].text == ["Their Title"]
        assert fresh["TALB"].text == ["My Album"]

    def test_duplicate_keys(self, mp3_path):
        tags = ID3()
        tags.add(TXXX(encoding=3, desc="one", text="1"))
        tags.add(TXXX(encoding=3, desc="two", text="2"))

        changed = copy.deepcopy(tags)
        changed["TXXX:two"] = TXXX(encoding=3, desc="two", text="changed")

        patch = diff_tags(tags, changed)
        assert op_map(patch) == {"TXXX:two": "change"}

        apply_patch(tags, patch)
        assert tags["TXXX:one"].text == ["1"]
        assert tags["TXXX:two"].text == ["changed"]

    def test_empty_and_none(self):
        assert not diff_tags(ID3(), ID3()).ops
        assert not diff_tags(ID3(), ID3())

        tags = ID3()
        tags.add(TIT2(encoding=3, text="Title"))
        patch = diff_tags(None, tags)
        assert op_map(patch) == {"TIT2": "add"}

        empty = ID3()
        result = apply_patch(empty, patch)
        assert result.ok
        assert not diff_tags(empty, tags).ops

        # removing everything again
        patch = diff_tags(tags, None)
        assert op_map(patch) == {"TIT2": "remove"}
        apply_patch(empty, patch)
        assert not diff_tags(empty, ID3()).ops

        with pytest.raises(ValueError):
            diff_tags(None, None)

    def test_unknown_frames_untouched(self, mp3_path):
        # a fresh v2.4 tag with a raw unknown frame
        tags = ID3()
        tags.add(TIT2(encoding=3, text="Title"))
        tags.add(TALB(encoding=3, text="Album"))
        payload = b"XYZ1" + struct.pack(">I", 4) + b"\x00\x00" + b"data"
        tags.unknown_frames.append(payload)
        tags.save(mp3_path)

        before = ID3(mp3_path)
        assert before.unknown_frames == [payload]

        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        patch = diff_tags(before, after)

        fresh = ID3(mp3_path)
        apply_patch(fresh, patch)
        assert fresh.unknown_frames == [payload]
        fresh.save()

        reloaded = ID3(mp3_path)
        assert reloaded.unknown_frames == [payload]
        assert reloaded["TIT2"].text == ["New Title"]
        # unrelated frames are untouched
        assert reloaded["TALB"].text == ["Album"]

    def test_filetype_unwrap(self, mp3_path):
        before = MP3(mp3_path)
        after_tags = copy.deepcopy(before.tags)
        after_tags["TIT2"] = TIT2(encoding=3, text="New Title")
        patch = diff_tags(before, after_tags)

        fresh = MP3(mp3_path)
        result = apply_patch(fresh, patch)
        assert result.ok
        assert fresh.tags["TIT2"].text == ["New Title"]

    def test_tagless_file(self, tmp_path):
        path = str(tmp_path / "empty.mp3")
        shutil.copy(os.path.join(DATA_DIR, "no-tags.mp3"), path)
        audio = MP3(path)
        assert audio.tags is None

        tags = ID3()
        tags.add(TIT2(encoding=3, text="Title"))
        patch = diff_tags(audio, tags)
        assert op_map(patch) == {"TIT2": "add"}

        # applying to a file without a tag block fails cleanly
        with pytest.raises(PatchError):
            apply_patch(audio, patch)
        assert audio.tags is None

        audio.add_tags()
        result = apply_patch(audio, patch)
        assert result.ok
        audio.save()
        assert MP3(path).tags["TIT2"].text == ["Title"]


class TestFLACPatch(object):

    def test_diff_apply_save_reload(self, flac_path):
        before = FLAC(flac_path)
        after = FLAC(flac_path)
        after.tags["title"] = "New Title"
        after.tags["artist"] = ["jzig", "piman"]  # reordered
        after.tags["comment"] = ["hello"]
        del after.tags["date"]
        after.pictures[0].data = b"\x89PNG" + b"\xff" * 1000
        after.add_picture(make_picture(b"\x89PNGsecond"))

        patch = diff_tags(before, after)
        assert patch.format == "flac"
        ops = op_map(patch)
        assert ops["title"] == "change"
        assert ops["artist"] == "change"
        assert ops["comment"] == "add"
        assert ops["date"] == "remove"
        # one picture changed (remove + add) and one was added
        pic_ops = [op for op in patch if op.key.startswith("=picture:")]
        assert [op.action for op in pic_ops].count("add") == 2
        assert [op.action for op in pic_ops].count("remove") == 1

        fresh = FLAC(flac_path)
        result = apply_patch(fresh, patch)
        assert result.ok
        assert not diff_tags(fresh, after).ops

        fresh.save()
        reloaded = FLAC(flac_path)
        assert not diff_tags(reloaded, after).ops
        assert reloaded.tags["artist"] == ["jzig", "piman"]
        assert len(reloaded.pictures) == 2

    def test_merge_no_conflict(self, flac_path):
        base = FLAC(flac_path)

        organizer = FLAC(flac_path)
        organizer.tags["title"] = "Organizer Title"
        patch_a = diff_tags(base, organizer)

        player = FLAC(flac_path)
        player.tags["genre"] = "Player Genre"
        patch_b = diff_tags(base, player)

        tags = FLAC(flac_path)
        apply_patch(tags, patch_a)
        tags.save()

        tags = FLAC(flac_path)
        result = apply_patch(tags, patch_b)
        assert result.ok
        tags.save()

        final = FLAC(flac_path)
        assert final.tags["title"] == ["Organizer Title"]
        assert final.tags["genre"] == ["Player Genre"]
        # untouched fields survive
        assert final.tags["artist"] == ["piman", "jzig"]

    def test_same_field_conflict(self, flac_path):
        base = FLAC(flac_path)
        mine = FLAC(flac_path)
        mine.tags["title"] = "My Title"
        mine.tags["genre"] = "My Genre"
        patch = diff_tags(base, mine)

        other = FLAC(flac_path)
        other.tags["title"] = "Their Title"
        other.save()

        fresh = FLAC(flac_path)
        with pytest.raises(PatchConflictError) as excinfo:
            apply_patch(fresh, patch)
        assert [c.key for c in excinfo.value.conflicts] == ["title"]
        assert fresh.tags["title"] == ["Their Title"]
        assert fresh.tags["genre"] == ["Silence"]

        result = apply_patch(fresh, patch, strict=False)
        assert [c.key for c in result.conflicts] == ["title"]
        assert fresh.tags["title"] == ["Their Title"]
        assert fresh.tags["genre"] == ["My Genre"]

    def test_multivalue_order_is_significant(self, flac_path):
        before = FLAC(flac_path)
        after = FLAC(flac_path)
        after.tags["artist"] = ["jzig", "piman"]

        patch = diff_tags(before, after)
        assert op_map(patch) == {"artist": "change"}

        fresh = FLAC(flac_path)
        apply_patch(fresh, patch)
        fresh.save()
        assert FLAC(flac_path).tags["artist"] == ["jzig", "piman"]

    def test_big_cover(self, flac_path):
        before = FLAC(flac_path)
        after = FLAC(flac_path)
        big = bytes(bytearray(range(256))) * 8192  # 2 MiB
        after.add_picture(make_picture(big))

        patch = diff_tags(before, after)
        assert len([op for op in patch if op.key.startswith("=picture:")]) == 1

        patch = TagPatch.from_json(patch.to_json())
        fresh = FLAC(flac_path)
        apply_patch(fresh, patch)
        fresh.save()

        reloaded = FLAC(flac_path)
        assert len(reloaded.pictures) == 2
        assert reloaded.pictures[1].data == big

    def test_empty_tags(self, tmp_path):
        path = str(tmp_path / "empty.flac")
        shutil.copy(os.path.join(DATA_DIR, "no-tags.flac"), path)
        empty = FLAC(path)
        assert empty.tags is None or not empty.tags

        full = FLAC(path)
        if full.tags is None:
            full.add_tags()
        full.tags["title"] = "Title"
        full.add_picture(make_picture())

        patch = diff_tags(empty, full)
        assert set(op_map(patch).values()) == {"add"}

        fresh = FLAC(path)
        if fresh.tags is None:
            fresh.add_tags()
        apply_patch(fresh, patch)
        assert not diff_tags(fresh, full).ops

    def test_bare_vorbis_comment_rejects_pictures(self, flac_path):
        flac = FLAC(flac_path)
        other = FLAC(flac_path)
        other.add_picture(make_picture())
        patch = diff_tags(flac, other)
        assert any(op.key.startswith("=picture:") for op in patch)

        with pytest.raises(PatchError):
            apply_patch(flac.tags, patch)


class TestMP4Patch(object):

    def test_diff_apply_save_reload(self, m4a_path):
        before = MP4(m4a_path)
        after = MP4(m4a_path)
        after.tags["\xa9nam"] = ["New Name"]
        after.tags["tmpo"] = [120]
        after.tags["cpil"] = True
        after.tags["trkn"] = [(2, 9)]
        after.tags["covr"] = [MP4Cover(b"\xff\xd8" + b"\x00" * 1000,
                                       imageformat=MP4Cover.FORMAT_JPEG)]
        after.tags["----:com.apple.iTunes:BAR"] = [
            MP4FreeForm(b"\x01\x02", dataformat=0)]
        del after.tags["\xa9too"]

        patch = diff_tags(before, after)
        assert patch.format == "mp4"
        assert op_map(patch) == {
            "\xa9nam": "add", "tmpo": "add", "cpil": "add",
            "trkn": "add", "covr": "change",
            "----:com.apple.iTunes:BAR": "add", "\xa9too": "remove",
        }

        fresh = MP4(m4a_path)
        result = apply_patch(fresh, patch)
        assert result.ok
        assert not diff_tags(fresh, after).ops

        fresh.save()
        reloaded = MP4(m4a_path)
        assert not diff_tags(reloaded, after).ops
        assert reloaded.tags["trkn"] == [(2, 9)]
        assert reloaded.tags["cpil"] is True

    def test_merge_no_conflict(self, m4a_path):
        base = MP4(m4a_path)

        organizer = MP4(m4a_path)
        organizer.tags["\xa9nam"] = ["Organizer Name"]
        patch_a = diff_tags(base, organizer)

        player = MP4(m4a_path)
        player.tags["tmpo"] = [99]
        patch_b = diff_tags(base, player)

        tags = MP4(m4a_path)
        apply_patch(tags, patch_a)
        tags.save()

        tags = MP4(m4a_path)
        result = apply_patch(tags, patch_b)
        assert result.ok
        tags.save()

        final = MP4(m4a_path)
        assert final.tags["\xa9nam"] == ["Organizer Name"]
        assert final.tags["tmpo"] == [99]
        assert final.tags["\xa9ART"] == ["Test Artist"]

    def test_same_field_conflict(self, m4a_path):
        base = MP4(m4a_path)
        mine = MP4(m4a_path)
        mine.tags["\xa9ART"] = ["My Artist"]
        mine.tags["\xa9nam"] = ["My Name"]
        patch = diff_tags(base, mine)

        other = MP4(m4a_path)
        other.tags["\xa9ART"] = ["Their Artist"]
        other.save()

        fresh = MP4(m4a_path)
        with pytest.raises(PatchConflictError) as excinfo:
            apply_patch(fresh, patch)
        assert [c.key for c in excinfo.value.conflicts] == ["\xa9ART"]
        assert fresh.tags["\xa9ART"] == ["Their Artist"]
        assert "\xa9nam" not in fresh.tags

        result = apply_patch(fresh, patch, strict=False)
        assert [c.key for c in result.conflicts] == ["\xa9ART"]
        assert fresh.tags["\xa9ART"] == ["Their Artist"]
        assert fresh.tags["\xa9nam"] == ["My Name"]

    def test_binary_values_compared_by_content(self, m4a_path):
        before = MP4(m4a_path)

        same = MP4(m4a_path)
        # a new object with identical content is not a change
        same.tags["covr"] = [
            MP4Cover(bytes(c), imageformat=c.imageformat)
            for c in before.tags["covr"]
        ]
        assert not diff_tags(before, same).ops

        changed = MP4(m4a_path)
        changed.tags["covr"] = [
            MP4Cover(b"\x89PNGother", imageformat=MP4Cover.FORMAT_PNG)]
        patch = diff_tags(before, changed)
        assert op_map(patch) == {"covr": "change"}

    def test_filetype_unwrap(self, m4a_path):
        before = MP4(m4a_path)
        after = MP4(m4a_path)
        after.tags["\xa9nam"] = ["New Name"]
        patch = diff_tags(before, after)

        fresh = MP4(m4a_path)
        apply_patch(fresh, patch)
        assert fresh.tags["\xa9nam"] == ["New Name"]

    def test_tagless_file(self, tmp_path, m4a_path):
        path = str(tmp_path / "empty.m4a")
        shutil.copy(os.path.join(DATA_DIR, "no-tags.m4a"), path)
        audio = MP4(path)
        assert audio.tags is None

        patch = diff_tags(audio, MP4(m4a_path))
        assert set(op_map(patch).values()) == {"add"}

        with pytest.raises(PatchError):
            apply_patch(audio, patch)
        assert audio.tags is None

        audio.add_tags()
        result = apply_patch(audio, patch)
        assert result.ok
        audio.save()
        assert not diff_tags(MP4(path), MP4(m4a_path)).ops


class TestSerialization(object):

    def test_json_roundtrip(self, mp3_path, flac_path, m4a_path):
        id3_old = ID3(mp3_path)
        id3_new = copy.deepcopy(id3_old)
        id3_new.add(APIC(encoding=3, mime="image/png",
                         type=PictureType.COVER_FRONT, desc="",
                         data=b"\x89PNG" + b"\x00" * 100))
        id3_patch = diff_tags(id3_old, id3_new)

        flac_old = FLAC(flac_path)
        flac_new = FLAC(flac_path)
        flac_new.add_picture(make_picture(b"\x89PNG" + b"\x01" * 100))
        flac_patch = diff_tags(flac_old, flac_new)

        mp4_old = MP4(m4a_path)
        mp4_new = MP4(m4a_path)
        mp4_new.tags["covr"] = [MP4Cover(b"\xff\xd8" + b"\x02" * 100,
                                         imageformat=MP4Cover.FORMAT_JPEG)]
        mp4_patch = diff_tags(mp4_old, mp4_new)

        for patch in (id3_patch, flac_patch, mp4_patch):
            assert TagPatch.from_json(patch.to_json()) == patch
            assert TagPatch.from_dict(patch.to_dict()) == patch
            assert TagPatch.from_json(patch.to_json().encode()) == patch

        # and the round-tripped patches still apply
        apply_patch(ID3(mp3_path), TagPatch.from_json(id3_patch.to_json()))
        apply_patch(FLAC(flac_path),
                    TagPatch.from_json(flac_patch.to_json()))
        apply_patch(MP4(m4a_path), TagPatch.from_json(mp4_patch.to_json()))

    def test_apply_accepts_json_and_dict(self, mp3_path):
        before = ID3(mp3_path)
        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        patch = diff_tags(before, after)

        apply_patch(ID3(mp3_path), patch.to_json())
        apply_patch(ID3(mp3_path), patch.to_dict())

    def test_from_dict_validation(self):
        with pytest.raises(PatchError):
            TagPatch.from_dict({"format": "ogg", "version": 1, "ops": []})
        with pytest.raises(PatchError):
            TagPatch.from_dict({"format": "id3", "version": 2, "ops": []})
        with pytest.raises(PatchError):
            TagPatch.from_dict({"format": "id3", "version": 1, "ops": [
                {"key": "TIT2", "action": "explode"}]})
        with pytest.raises(PatchError):
            TagPatch.from_dict({"format": "id3", "version": 1, "ops": [
                {"key": "TIT2", "action": "add"}]})
        with pytest.raises(PatchError):
            TagPatch.from_json("not json")
        with pytest.raises(ValueError):
            TagPatch("ogg")

    def test_format_mismatch(self, mp3_path, flac_path):
        with pytest.raises(ValueError):
            diff_tags(ID3(mp3_path), FLAC(flac_path))

        patch = diff_tags(ID3(mp3_path), ID3(mp3_path))
        with pytest.raises(ValueError):
            apply_patch(FLAC(flac_path), patch)


class TestApplySemantics(object):

    def test_strict_apply_is_atomic(self, mp3_path):
        base = ID3(mp3_path)
        mine = copy.deepcopy(base)
        mine["TIT2"] = TIT2(encoding=3, text="My Title")
        mine["TALB"] = TALB(encoding=3, text="My Album")
        patch = diff_tags(base, mine)

        fresh = ID3(mp3_path)
        fresh["TIT2"] = TIT2(encoding=3, text="Their Title")

        with pytest.raises(PatchConflictError):
            apply_patch(fresh, patch)
        # the non-conflicting operation was not applied either
        assert fresh["TALB"].text == ["Quod Libet Test Data"]

    def test_malformed_payload_changes_nothing(self, mp3_path):
        before = ID3(mp3_path)
        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        after["TALB"] = TALB(encoding=3, text="New Album")
        patch = diff_tags(before, after)

        for op in patch:
            if op.key == "TIT2":
                op.value = {"frame": "TIT2", "data": "!!!not-base64!!!"}

        fresh = ID3(mp3_path)
        with pytest.raises(PatchError):
            apply_patch(fresh, patch, strict=False)
        assert not diff_tags(fresh, ID3(mp3_path)).ops

    def test_unknown_frame_id_rejected(self, mp3_path):
        before = ID3(mp3_path)
        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        patch = diff_tags(before, after)
        for op in patch:
            op.value = {"frame": "XYZ1", "data": "AAAA"}

        with pytest.raises(PatchError):
            apply_patch(ID3(mp3_path), patch)

    def test_apply_twice_is_idempotent(self, mp3_path):
        before = ID3(mp3_path)
        after = copy.deepcopy(before)
        after["TIT2"] = TIT2(encoding=3, text="New Title")
        del after["TPE1"]
        patch = diff_tags(before, after)

        fresh = ID3(mp3_path)
        first = apply_patch(fresh, patch)
        assert first.ok
        assert set(first.applied) == {"TIT2", "TPE1"}

        second = apply_patch(fresh, patch)
        assert second.ok
        assert not second.applied
        assert set(second.skipped) == {"TIT2", "TPE1"}
        assert not diff_tags(fresh, after).ops

    def test_conflicting_add(self, mp3_path):
        base = ID3(mp3_path)
        del base["TIT2"]
        mine = copy.deepcopy(base)
        mine["TIT2"] = TIT2(encoding=3, text="My Title")
        patch = diff_tags(base, mine)

        fresh = ID3(mp3_path)  # still has the original TIT2
        with pytest.raises(PatchConflictError) as excinfo:
            apply_patch(fresh, patch)
        assert excinfo.value.conflicts[0].key == "TIT2"
        assert fresh["TIT2"].text == ["Silence"]

        # same value already present -> skipped, not a conflict
        fresh["TIT2"] = TIT2(encoding=3, text="My Title")
        result = apply_patch(fresh, patch)
        assert result.ok
        assert result.skipped == ["TIT2"]
