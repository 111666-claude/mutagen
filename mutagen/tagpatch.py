# Copyright (C) 2026  Christoph Reiter
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Field-level tag patches for ID3, FLAC and MP4 tags.

When two programs (say a library organizer and a player) each hold a
copy of the same file's tags and both modify them, saving the whole
tag set back silently overwrites the other program's changes. Instead
compute a patch containing only the fields you changed and apply it to
a freshly loaded copy of the file's tags::

    patch = diff_tags(tags_before, tags_after)
    data = patch.to_json()          # can be stored/transferred

    # ... later, maybe on another machine:
    audio = MP3(path)               # re-read the current on-disk state
    apply_patch(audio.tags, patch)  # raises PatchConflictError on conflict
    audio.save()

Properties:

* A patch only touches the fields it contains. Every other field,
  unknown frames/atoms and any non-tag data are left alone.
* Each operation carries the fingerprint (SHA-1 of the canonical
  serialized value) of the value it was computed against. If the value
  in the target no longer matches, the operation is reported as a
  conflict instead of being applied.
* Values, including binary ones like covers, are compared by content.
* Multi-value fields are compared as ordered lists: reordering the
  values of a field is a change of that field.
* Applying is all-or-nothing in strict mode (the default): all
  operations are validated before anything is modified, so a failed
  apply never leaves a half-patched tag behind. In non-strict mode the
  conflicting operations are skipped and reported, the rest is
  applied.
* Applying a patch twice is safe: operations whose result is already
  in place are skipped.

Deterministic handling of edge cases:

* ID3 frames are keyed by their ``HashKey``, so repeated frame types
  (e.g. two ``TXXX`` frames with different descriptions) are
  independent fields.
* Vorbis comment keys are case-insensitive and normalized to
  lowercase, as in mutagen itself.
* FLAC pictures are content-addressed: changing a picture shows up as
  a remove plus an add operation. Large picture data only appears in
  the patch when the picture itself was added or changed.
* Empty tags and empty patches are valid: diffing against an empty
  tag (or `None`) yields only "add" operations, applying an empty
  patch changes nothing.
"""

import base64
import binascii
import hashlib
import json

from mutagen._file import FileType
from mutagen._util import MutagenError
from mutagen._vorbis import VCommentDict
from mutagen.flac import FLAC, Picture
from mutagen.id3 import Frames, ID3FileType
from mutagen.id3._tags import ID3Header, ID3Tags
from mutagen.id3._util import ID3EncryptionUnsupportedError, ID3JunkFrameError
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm, MP4Tags

__all__ = [
    "PatchError", "PatchConflictError", "Conflict", "PatchOp",
    "TagPatch", "PatchResult", "diff_tags", "apply_patch",
]

FORMAT_ID3 = "id3"
FORMAT_FLAC = "flac"
FORMAT_MP4 = "mp4"
_FORMATS = (FORMAT_ID3, FORMAT_FLAC, FORMAT_MP4)

ACTION_ADD = "add"
ACTION_REMOVE = "remove"
ACTION_CHANGE = "change"
_ACTIONS = (ACTION_ADD, ACTION_REMOVE, ACTION_CHANGE)

#: Prefix for pseudo keys addressing FLAC pictures. Contains "=" so it
#: can never collide with a Vorbis comment key.
_PICTURE_KEY_PREFIX = "=picture:"

_FORMAT_VERSION = 1


class PatchError(MutagenError):
    """Base class for tag patch errors."""


class PatchConflictError(PatchError):
    """Raised by :func:`apply_patch` in strict mode when one or more
    operations conflict with the current state of the target.

    Attributes:
        conflicts (list[Conflict]): the conflicting operations
    """

    def __init__(self, conflicts):
        self.conflicts = list(conflicts)
        keys = ", ".join(
            "%s (%s)" % (c.key, c.action) for c in self.conflicts)
        super(PatchConflictError, self).__init__(
            "tag patch conflicts: " + keys)


class Conflict(object):
    """Describes one patch operation that could not be applied.

    Attributes:
        key (str): key of the field
        action (str): the action that was attempted
        expected (str | None): fingerprint the operation was computed
            against (`None` for additions)
        found (str | None): fingerprint currently in the target
            (`None` if the field is missing)
    """

    def __init__(self, key, action, expected, found):
        self.key = key
        self.action = action
        self.expected = expected
        self.found = found

    def __eq__(self, other):
        return type(self) is type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return ("<%s key=%r action=%r expected=%r found=%r>" % (
            type(self).__name__, self.key, self.action,
            self.expected, self.found))


class PatchResult(object):
    """The outcome of applying a patch.

    Attributes:
        applied (list[str]): keys of the fields that were modified
        skipped (list[str]): keys whose target state was already
            reached (applying is idempotent)
        conflicts (list[Conflict]): operations that were not applied
            (only non-empty in non-strict mode)
    """

    def __init__(self, applied=(), skipped=(), conflicts=()):
        self.applied = list(applied)
        self.skipped = list(skipped)
        self.conflicts = list(conflicts)

    @property
    def ok(self):
        """Whether everything was applied (or already in place)."""

        return not self.conflicts

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return ("<%s applied=%r skipped=%r conflicts=%r>" % (
            type(self).__name__, self.applied, self.skipped,
            self.conflicts))


def _b64encode(data):
    return base64.b64encode(data).decode("ascii")


def _b64decode(text):
    if not isinstance(text, str):
        raise PatchError("expected base64 string, got %r" % type(text))
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, ValueError) as e:
        raise PatchError("invalid base64 data: %s" % e)


def _fingerprint(payload):
    """Content fingerprint of a canonical field payload."""

    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha1:" + hashlib.sha1(blob).hexdigest()


class PatchOp(object):
    """One field operation of a patch.

    Attributes:
        key (str): key of the field (ID3 HashKey, Vorbis comment key,
            MP4 atom key, or a picture pseudo key)
        action (str): "add", "remove" or "change"
        old_fp (str | None): fingerprint of the value the operation
            was computed against
        new_fp (str | None): fingerprint of the new value
        value: canonical payload of the new value (format specific,
            `None` for removals)
    """

    def __init__(self, key, action, old_fp=None, new_fp=None, value=None):
        if action not in _ACTIONS:
            raise ValueError("invalid action %r" % (action,))
        self.key = key
        self.action = action
        self.old_fp = old_fp
        self.new_fp = new_fp
        self.value = value

    def to_dict(self):
        return {
            "key": self.key,
            "action": self.action,
            "old_fp": self.old_fp,
            "new_fp": self.new_fp,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data):
        try:
            key = data["key"]
            action = data["action"]
        except (TypeError, KeyError) as e:
            raise PatchError("invalid patch operation: %r" % (e,))
        if not isinstance(key, str):
            raise PatchError("invalid operation key %r" % (key,))
        if action not in _ACTIONS:
            raise PatchError("invalid action %r" % (action,))
        old_fp = data.get("old_fp")
        new_fp = data.get("new_fp")
        for fp in (old_fp, new_fp):
            if fp is not None and not isinstance(fp, str):
                raise PatchError("invalid fingerprint %r" % (fp,))
        value = data.get("value")
        if action in (ACTION_ADD, ACTION_CHANGE) and value is None:
            raise PatchError("%r operation without a value" % action)
        return cls(key, action, old_fp, new_fp, value)

    def __eq__(self, other):
        return type(self) is type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return ("<%s %r %s>" % (
            type(self).__name__, self.key, self.action))


class TagPatch(object):
    """A field-level diff between two tag states of the same format.

    Use :func:`diff_tags` to create one and :func:`apply_patch` (or
    :meth:`apply`) to apply it.
    """

    def __init__(self, format, ops=()):
        """
        Args:
            format (str): one of "id3", "flac", "mp4"
            ops (list[PatchOp]): the operations
        """

        if format not in _FORMATS:
            raise ValueError("unknown tag format %r" % (format,))
        self.format = format
        self.ops = list(ops)

    def apply(self, target, strict=True):
        """Apply this patch to a tag object; see :func:`apply_patch`."""

        return apply_patch(target, self, strict=strict)

    def to_dict(self):
        """Returns a JSON-serializable dict representation."""

        return {
            "format": self.format,
            "version": _FORMAT_VERSION,
            "ops": [op.to_dict() for op in self.ops],
        }

    @classmethod
    def from_dict(cls, data):
        """Create a patch from a dict as produced by :meth:`to_dict`.

        Raises:
            PatchError: if the data is malformed
        """

        if not isinstance(data, dict):
            raise PatchError("patch must be a dict")
        format = data.get("format")
        if format not in _FORMATS:
            raise PatchError("unknown tag format %r" % (format,))
        if data.get("version") != _FORMAT_VERSION:
            raise PatchError(
                "unsupported patch version %r" % (data.get("version"),))
        ops = data.get("ops")
        if not isinstance(ops, list):
            raise PatchError("patch ops must be a list")
        return cls(format, [PatchOp.from_dict(op) for op in ops])

    def to_json(self):
        """Returns the patch as a JSON string."""

        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, data):
        """Create a patch from a JSON string.

        Raises:
            PatchError: if the data is malformed
        """

        if isinstance(data, bytes):
            data = data.decode("utf-8")
        try:
            parsed = json.loads(data)
        except ValueError as e:
            raise PatchError("invalid JSON: %s" % e)
        return cls.from_dict(parsed)

    def __len__(self):
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)

    def __bool__(self):
        return bool(self.ops)

    def __eq__(self, other):
        return type(self) is type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<%s format=%r ops=%d>" % (
            type(self).__name__, self.format, len(self.ops))


def _decode_frame(payload):
    """Rebuild an ID3 frame from its canonical payload."""

    if not isinstance(payload, dict):
        raise PatchError("invalid frame payload %r" % (payload,))
    frame_id = payload.get("frame")
    frame_cls = Frames.get(frame_id)
    if frame_cls is None:
        raise PatchError("unsupported frame ID %r" % (frame_id,))
    data = _b64decode(payload.get("data"))
    header = ID3Header()
    header.version = ID3Header._V24
    try:
        return frame_cls._fromData(header, 0, data)
    except (ID3JunkFrameError, NotImplementedError,
            ID3EncryptionUnsupportedError) as e:
        raise PatchError("can't decode %s frame: %s" % (frame_id, e))


def _frame_payload(frame):
    try:
        data = frame._writeData()
    except Exception as e:
        raise PatchError("can't serialize %r: %s" % (frame, e))
    return {"frame": frame.FrameID, "data": _b64encode(data)}


class _Adapter(object):
    """Uniform view on the supported tag containers."""

    format = None

    def fields(self):
        """Returns dict[str, payload] for all fields."""
        raise NotImplementedError

    def prepare_set(self, key, payload):
        """Validate and return a callable performing the mutation."""
        raise NotImplementedError

    def prepare_delete(self, key):
        """Return a callable removing the field."""
        raise NotImplementedError


class _ID3Adapter(_Adapter):

    format = FORMAT_ID3

    def __init__(self, tags):
        # tags: an ID3Tags instance, or None for a file without a tag
        self.tags = tags

    def fields(self):
        if self.tags is None:
            return {}
        fields = {}
        for frame in self.tags.values():
            fields[frame.HashKey] = _frame_payload(frame)
        return fields

    def prepare_set(self, key, payload):
        if self.tags is None:
            raise PatchError(
                "patch contains ID3 frames but the target has no ID3 "
                "tag; call add_tags() first")
        frame = _decode_frame(payload)
        if frame.HashKey != key:
            raise PatchError(
                "frame %r does not match patch key %r" % (
                    frame.HashKey, key))

        def apply():
            self.tags[key] = frame
        return apply

    def prepare_delete(self, key):
        if self.tags is None:
            raise PatchError(
                "patch contains ID3 frames but the target has no ID3 "
                "tag; call add_tags() first")

        def apply():
            del self.tags[key]
        return apply


class _FLACAdapter(_Adapter):

    format = FORMAT_FLAC

    def __init__(self, comments, flac=None):
        # comments: a VCommentDict or None; flac: the FLAC FileType
        # holding the pictures, or None if pictures are unsupported
        self.comments = comments
        self.flac = flac

    @property
    def pictures(self):
        if self.flac is None:
            return None
        return self.flac.pictures

    def _picture_payload(self, picture):
        return {"picture": _b64encode(picture.write())}

    def fields(self):
        fields = {}
        if self.comments is not None:
            for key in self.comments.keys():
                texts = list(self.comments[key])
                for text in texts:
                    if not isinstance(text, str):
                        raise PatchError(
                            "non-text value in vorbis comment %r" % key)
                fields[key] = {"texts": texts}
        if self.pictures is not None:
            for picture in self.pictures:
                payload = self._picture_payload(picture)
                key = _PICTURE_KEY_PREFIX + _fingerprint(payload)
                fields[key] = payload
        return fields

    def prepare_set(self, key, payload):
        if key.startswith(_PICTURE_KEY_PREFIX):
            if self.flac is None:
                raise PatchError(
                    "patch contains a picture but the target "
                    "has no picture support")
            if not isinstance(payload, dict) or "picture" not in payload:
                raise PatchError("invalid picture payload")
            picture = Picture(_b64decode(payload["picture"]))

            def apply():
                self.flac.add_picture(picture)
            return apply

        if self.comments is None:
            raise PatchError(
                "patch contains vorbis comments but the target "
                "has no comment block")
        if not isinstance(payload, dict):
            raise PatchError("invalid comment payload")
        texts = payload.get("texts")
        if not isinstance(texts, list) or \
                not all(isinstance(t, str) for t in texts):
            raise PatchError("invalid comment values %r" % (texts,))
        texts = list(texts)

        def apply():
            self.comments[key] = texts
        return apply

    def prepare_delete(self, key):
        if key.startswith(_PICTURE_KEY_PREFIX):
            if self.flac is None:
                raise PatchError(
                    "patch contains a picture but the target "
                    "has no picture support")
            wanted = key[len(_PICTURE_KEY_PREFIX):]

            def apply():
                blocks = self.flac.metadata_blocks
                for i, block in enumerate(blocks):
                    if block.code != Picture.code:
                        continue
                    payload = self._picture_payload(block)
                    if _fingerprint(payload) == wanted:
                        del blocks[i]
                        return
                raise PatchError("picture %s vanished" % wanted)
            return apply

        def apply():
            del self.comments[key]
        return apply


def _encode_mp4_value(value):
    if isinstance(value, MP4Cover):
        return {"t": "cover", "v": _b64encode(bytes(value)),
                "fmt": int(value.imageformat)}
    if isinstance(value, MP4FreeForm):
        return {"t": "freeform", "v": _b64encode(bytes(value)),
                "fmt": int(value.dataformat), "ver": int(value.version)}
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, str):
        return {"t": "text", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": value}
    if isinstance(value, (bytes, bytearray)):
        return {"t": "bytes", "v": _b64encode(bytes(value))}
    if isinstance(value, tuple) and \
            all(isinstance(v, int) and not isinstance(v, bool)
                for v in value):
        return {"t": "tuple", "v": list(value)}
    raise PatchError(
        "unsupported MP4 value type %r" % type(value).__name__)


def _decode_mp4_value(entry):
    if not isinstance(entry, dict):
        raise PatchError("invalid MP4 value %r" % (entry,))
    kind = entry.get("t")
    value = entry.get("v")
    if kind == "text":
        if not isinstance(value, str):
            raise PatchError("invalid text value %r" % (value,))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise PatchError("invalid bool value %r" % (value,))
        return value
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise PatchError("invalid int value %r" % (value,))
        return value
    if kind == "bytes":
        return _b64decode(value)
    if kind == "cover":
        fmt = entry.get("fmt")
        if not isinstance(fmt, int) or isinstance(fmt, bool):
            raise PatchError("invalid cover format %r" % (fmt,))
        return MP4Cover(_b64decode(value), imageformat=fmt)
    if kind == "freeform":
        fmt = entry.get("fmt")
        ver = entry.get("ver", 0)
        if not isinstance(fmt, int) or not isinstance(ver, int):
            raise PatchError("invalid freeform format %r" % (entry,))
        return MP4FreeForm(_b64decode(value), dataformat=fmt, version=ver)
    if kind == "tuple":
        if not isinstance(value, list) or \
                not all(isinstance(v, int) and not isinstance(v, bool)
                        for v in value):
            raise PatchError("invalid tuple value %r" % (value,))
        return tuple(value)
    raise PatchError("unknown MP4 value type %r" % (kind,))


class _MP4Adapter(_Adapter):

    format = FORMAT_MP4

    def __init__(self, tags):
        # tags: an MP4Tags instance, or None for a file without tags
        self.tags = tags

    def fields(self):
        if self.tags is None:
            return {}
        fields = {}
        for key, values in self.tags.items():
            # most keys map to a list of values, but a few (e.g. 'cpil')
            # map to a single value; remember the shape so applying
            # restores it exactly
            single = not isinstance(values, list)
            if single:
                values = [values]
            payload = {"values": [_encode_mp4_value(v) for v in values]}
            if single:
                payload["single"] = True
            fields[key] = payload
        return fields

    def prepare_set(self, key, payload):
        if self.tags is None:
            raise PatchError(
                "patch contains MP4 tags but the target has no tag "
                "atom; call add_tags() first")
        if not isinstance(payload, dict) or \
                not isinstance(payload.get("values"), list):
            raise PatchError("invalid MP4 payload %r" % (payload,))
        values = [_decode_mp4_value(entry) for entry in payload["values"]]
        if payload.get("single"):
            if len(values) != 1:
                raise PatchError(
                    "single-value payload with %d values" % len(values))

            def apply():
                self.tags[key] = values[0]
        else:

            def apply():
                self.tags[key] = values
        return apply

    def prepare_delete(self, key):
        if self.tags is None:
            raise PatchError(
                "patch contains MP4 tags but the target has no tag "
                "atom; call add_tags() first")

        def apply():
            del self.tags[key]
        return apply


def _adapt(target):
    """Wrap a supported tag object (or a FileType holding one)."""

    if isinstance(target, ID3Tags):
        return _ID3Adapter(target)
    if isinstance(target, FLAC):
        return _FLACAdapter(target.tags, target)
    if isinstance(target, VCommentDict):
        return _FLACAdapter(target)
    if isinstance(target, MP4Tags):
        return _MP4Adapter(target)
    if isinstance(target, MP4):
        return _MP4Adapter(target.tags)
    if isinstance(target, ID3FileType):
        return _ID3Adapter(target.tags)
    if isinstance(target, FileType):
        tags = target.tags
        if tags is not None:
            return _adapt(tags)
    raise TypeError("unsupported tag object: %r" % type(target).__name__)


def diff_tags(old, new):
    """diff_tags(old, new) -> TagPatch

    Compute the field-level difference between two tag states of the
    same format (ID3, FLAC or MP4). Either side may be a tag object
    (:class:`mutagen.id3.ID3`, :class:`mutagen.flac.FLAC`,
    :class:`mutagen.flac.VCFLACDict`, :class:`mutagen.mp4.MP4Tags`),
    a :class:`mutagen.FileType` holding one of them, or `None` (treated
    as an empty tag of the other side's format). A file without tags
    (``audio.tags is None``) is treated as an empty tag of its format.

    Applying the returned patch to `old` yields `new`; applying it to
    a tag that no longer matches `old` reports conflicts instead.

    Raises:
        ValueError: if the formats differ or both sides are `None`
        PatchError: if a value can't be represented in a patch
    """

    if old is None and new is None:
        raise ValueError("both tags are None")
    old_adapter = _adapt(old) if old is not None else None
    new_adapter = _adapt(new) if new is not None else None
    if old_adapter is not None and new_adapter is not None and \
            old_adapter.format != new_adapter.format:
        raise ValueError(
            "can't diff %s tags against %s tags" % (
                old_adapter.format, new_adapter.format))
    format = (old_adapter or new_adapter).format
    old_fields = old_adapter.fields() if old_adapter is not None else {}
    new_fields = new_adapter.fields() if new_adapter is not None else {}

    ops = []
    for key in sorted(set(old_fields) | set(new_fields)):
        in_old = key in old_fields
        in_new = key in new_fields
        old_fp = _fingerprint(old_fields[key]) if in_old else None
        new_fp = _fingerprint(new_fields[key]) if in_new else None
        if in_old and not in_new:
            ops.append(PatchOp(key, ACTION_REMOVE, old_fp=old_fp))
        elif in_new and not in_old:
            ops.append(PatchOp(key, ACTION_ADD, new_fp=new_fp,
                               value=new_fields[key]))
        elif old_fp != new_fp:
            ops.append(PatchOp(key, ACTION_CHANGE, old_fp=old_fp,
                               new_fp=new_fp, value=new_fields[key]))
    return TagPatch(format, ops)


def apply_patch(target, patch, strict=True):
    """apply_patch(target, patch, strict=True) -> PatchResult

    Apply a patch created by :func:`diff_tags` to a freshly loaded tag
    object (anything :func:`diff_tags` accepts, except `None`). If the
    target is a file without a tag block (``audio.tags is None``) and
    the patch is not empty, :class:`PatchError` is raised; call
    ``add_tags()`` on the file first.

    All operations are validated before anything is modified: if any
    operation conflicts with the current state, strict mode (the
    default) raises :class:`PatchConflictError` and the target is left
    untouched. With ``strict=False`` the conflicting operations are
    skipped and returned in ``PatchResult.conflicts`` while the rest
    is applied. A malformed patch raises :class:`PatchError` before
    any modification as well.

    Args:
        target: the tag object to modify
        patch (TagPatch | str | dict): the patch, or its JSON/dict
            representation
        strict (bool): raise on conflicts instead of skipping them

    Raises:
        PatchConflictError: in strict mode, if any operation conflicts
        PatchError: if the patch is malformed
        ValueError: if the patch format doesn't match the target
        TypeError: if the target type isn't supported
    """

    if isinstance(patch, (str, bytes)):
        patch = TagPatch.from_json(patch)
    elif isinstance(patch, dict):
        patch = TagPatch.from_dict(patch)
    if not isinstance(patch, TagPatch):
        raise TypeError("expected a TagPatch, got %r" % type(patch))

    adapter = _adapt(target)
    if adapter.format != patch.format:
        raise ValueError(
            "can't apply a %s patch to %s tags" % (
                patch.format, adapter.format))

    current = adapter.fields()
    current_fps = {key: _fingerprint(payload)
                   for key, payload in current.items()}

    # Phase 1: verify every operation against the current state and
    # decode all payloads. Nothing is modified yet, so any failure
    # here leaves the target untouched.
    planned = []
    skipped = []
    conflicts = []
    for op in patch.ops:
        now = current_fps.get(op.key)
        if op.action == ACTION_ADD:
            if now is None:
                planned.append((op, adapter.prepare_set(op.key, op.value)))
            elif now == op.new_fp:
                skipped.append(op.key)
            else:
                conflicts.append(Conflict(op.key, op.action, None, now))
        elif op.action == ACTION_REMOVE:
            if now is None:
                skipped.append(op.key)
            elif now == op.old_fp:
                planned.append((op, adapter.prepare_delete(op.key)))
            else:
                conflicts.append(
                    Conflict(op.key, op.action, op.old_fp, now))
        else:
            assert op.action == ACTION_CHANGE
            if now is not None and now == op.new_fp:
                skipped.append(op.key)
            elif now is not None and now == op.old_fp:
                planned.append((op, adapter.prepare_set(op.key, op.value)))
            else:
                conflicts.append(
                    Conflict(op.key, op.action, op.old_fp, now))

    if conflicts and strict:
        raise PatchConflictError(conflicts)

    # Phase 2: everything validated, perform the mutations.
    applied = []
    for op, mutate in planned:
        mutate()
        applied.append(op.key)

    return PatchResult(applied, skipped, conflicts)
