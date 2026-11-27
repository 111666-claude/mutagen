# Copyright (C) 2026  Mutagen contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Read the Microsoft ``Xtra`` atom found in MP4/M4A files.

Windows (Windows Media Player, Explorer) stores a number of metadata
fields in ``moov.udta.Xtra`` instead of the iTunes ``ilst`` atom.  The
values use Windows Media attribute names such as ``WM/Director`` or
``WM/SharedUserRating``.

The binary format (all structure sizes are big endian, the values
themselves are little endian) is::

    tag_size    uint32be  size of the whole tag including this field
    name_size   uint32be  size of the attribute name
    name        bytes     attribute name (e.g. WM/Director, ASCII/UTF-8)
    value_count uint32be  number of values
    value_count times:
        value_size uint32be  size of the value including this field
        value_type uint16be  Windows Media type (8 = UTF-16LE, 19 = uint64)
        value      bytes     little endian payload

Only the value types needed for text and integer attributes are
decoded; values of other types (file times, GUIDs, ...) are ignored.
Parsing is deliberately tolerant: a structural problem stops the scan
at that point but keeps everything parsed before it, malformed values
are skipped, and no exception escapes so that the regular iTunes tags
stay readable.
"""

import struct

from collections.abc import Mapping

from mutagen._util import MutagenError


class XtraError(MutagenError):
    """Raised when the Xtra atom itself cannot be located or read."""


# Windows Media value types
VT_UNICODE = 8
VT_UINT64 = 19

# Sentinel for a value which could not be decoded
_invalid = object()


def _decode_utf16(data):
    """Decode a Windows Media Unicode value.

    Returns the decoded `str` or ``_invalid`` if the payload isn't valid
    UTF-16.  The values are usually NUL terminated UTF-16LE; a byte order
    mark is honoured if one is present.
    """

    if not data:
        return u""

    if data[:2] == b"\xff\xfe":
        data = data[2:]
        encoding = "utf-16-le"
    elif data[:2] == b"\xfe\xff":
        data = data[2:]
        encoding = "utf-16-be"
    else:
        encoding = "utf-16-le"

    # UTF-16 is made up of 16 bit units
    if len(data) % 2:
        return _invalid

    try:
        value = data.decode(encoding)
    except UnicodeDecodeError:
        return _invalid

    # The value is normally NUL terminated, don't expose the terminator
    return value.rstrip(u"\x00")


def _parse_value(value_type, payload):
    """Parse a single value.

    Returns ``(value, error)`` where ``value`` is ``_invalid`` if the
    value isn't exposed and ``error`` is a message if the value is
    malformed.  Unsupported types are not errors, their values are
    simply not exposed.
    """

    if value_type == VT_UNICODE:
        value = _decode_utf16(payload)
        if value is _invalid:
            return _invalid, "invalid Xtra text encoding"
        return value, None
    elif value_type == VT_UINT64:
        if len(payload) != 8:
            return _invalid, "invalid Xtra integer size %d" % len(payload)
        return struct.unpack("<Q", payload)[0], None
    else:
        # Unknown/unsupported type, ignore this value
        return _invalid, None


class MP4Xtra(Mapping):
    """MP4Xtra()

    Read-only view of the tags stored in the Microsoft ``Xtra`` atom.

    Keys are the Microsoft attribute names exactly as stored in the
    file, so they can't be confused with the four character keys of the
    regular iTunes tags in :attr:`MP4.tags`:::

        audio = MP4("example.m4a")
        if audio.xtra is not None:
            print(audio.xtra["WM/Director"])
            print(audio.xtra["WM/SharedUserRating"])

    Every value is a list, so attributes with multiple values don't lose
    any of them.  Text values are returned as `str`, integer values as
    `int`.  Values of other Microsoft types are not exposed.

    This object is read-only: it is never written back when saving the
    regular tags and modifying it does not affect the file.  If the
    atom is malformed while being read, the values parsed before the
    problem are kept and :attr:`error` describes what went wrong.

    MP4 tag data cannot exist outside of the structure of an MP4 file,
    so this class should not be manually instantiated.
    """

    def __init__(self, *args, **kwargs):
        self._values = {}
        self._error = None
        super(MP4Xtra, self).__init__()
        if args or kwargs:
            self.load(*args, **kwargs)

    def load(self, atoms, fileobj):
        """Load the Xtra values.

        Raises :class:`XtraError` if the ``Xtra`` atom itself is missing
        or can't be read.  Malformed tag data inside the atom is reported
        through :attr:`error` instead.
        """

        self._values = {}
        self._error = None

        try:
            atom = atoms.path(b"moov", b"udta", b"Xtra")[-1]
        except KeyError as key:
            raise XtraError("Xtra atom not found: %s" % (key,))

        ok, data = atom.read(fileobj)
        if not ok:
            raise XtraError("truncated Xtra atom")

        self._parse(data)

    @classmethod
    def _can_load(cls, atoms):
        return b"moov.udta.Xtra" in atoms

    def _set_error(self, message):
        # Keep the first problem, it is the reason parsing stopped or
        # the reason a value is missing.
        if self._error is None:
            self._error = message

    def _parse(self, data):
        """Parse the atom payload, stopping at the first bad record."""

        pos = 0
        end = len(data)

        while pos + 4 <= end:
            if pos + 12 > end:
                self._set_error("truncated Xtra tag header")
                return

            tag_size = struct.unpack_from(">I", data, pos)[0]
            record_end = pos + tag_size
            # 4 bytes tag size + 4 bytes name size + 4 bytes value count
            if tag_size < 12 or record_end > end:
                self._set_error("invalid Xtra tag size %d" % tag_size)
                return

            name_size = struct.unpack_from(">I", data, pos + 4)[0]
            if name_size > tag_size - 12:
                self._set_error(
                    "invalid Xtra tag name size %d" % name_size)
                return

            name_start = pos + 8
            name_end = name_start + name_size

            try:
                name = data[name_start:name_end].decode("utf-8")
            except UnicodeDecodeError:
                # The record boundaries are still known, skip this tag
                # but continue with the next one.
                self._set_error("invalid Xtra tag name")
                pos = record_end
                continue

            value_count = struct.unpack_from(">I", data, name_end)[0]
            value_pos = name_end + 4
            values = []
            structural = False

            for _i in range(value_count):
                if value_pos + 6 > record_end:
                    self._set_error("truncated Xtra value header")
                    structural = True
                    break

                value_size, value_type = struct.unpack_from(
                    ">IH", data, value_pos)
                if value_size < 6 or value_pos + value_size > record_end:
                    self._set_error(
                        "invalid Xtra value size %d" % value_size)
                    structural = True
                    break

                payload = data[value_pos + 6:value_pos + value_size]
                value, err = _parse_value(value_type, payload)
                if err is not None:
                    self._set_error("%s for %s" % (err, name))
                elif value is not _invalid:
                    values.append(value)

                value_pos += value_size

            if values:
                # merge with previous records using the same name
                self._values.setdefault(name, []).extend(values)

            if structural:
                # The remaining bytes of this atom can't be trusted
                return

            pos = record_end

    @property
    def error(self):
        """`str` or `None`: the first problem seen while parsing."""

        return self._error

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self._values)

    def pprint(self):
        """Return a string with one ``Xtra:key=value`` line per value."""

        lines = []
        for key, values in sorted(self._values.items()):
            for value in values:
                lines.append(u"Xtra:%s=%s" % (key, value))
        return u"\n".join(lines)
