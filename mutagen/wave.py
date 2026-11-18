# Copyright (C) 2017  Borewit
# Copyright (C) 2019-2020  Philipp Wolfer
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Microsoft WAVE/RIFF audio file/stream information and tags."""

import sys
import struct

from mutagen import StreamInfo, FileType, Metadata

from mutagen.id3 import ID3
from mutagen._riff import RiffFile
from mutagen._iff import error as _IffError, InvalidChunk
from mutagen.id3._util import ID3NoHeaderError, error as ID3Error
from mutagen._util import (
    DictMixin,
    convert_error,
    delete_bytes,
    endswith,
    insert_bytes,
    loadfile,
    reraise,
    resize_bytes,
)

__all__ = ["WAVE", "RiffInfo", "InfoTags", "InfoError", "Open", "delete"]


class error(_IffError):
    """WAVE stream parsing errors."""


class InfoError(error):
    """Error while reading or writing RIFF ``LIST/INFO`` tags."""


#: Largest amount of data a RIFF chunk can describe with its 32 bit size.
_MAX_CHUNK_SIZE = 0xFFFFFFFF

#: Container name of the RIFF LIST chunk holding INFO text.
_INFO_NAME = b"INFO"

#: Human readable descriptions for the INFO four character codes defined by
#: the RIFF specification. Unknown codes are still read and written unchanged.
INFO_TAG_NAMES = {
    "IARL": "Archival Location",
    "IART": "Artist",
    "ICMS": "Commissioned",
    "ICMT": "Comments",
    "ICOP": "Copyright",
    "ICRD": "Creation Date",
    "IENG": "Engineer",
    "IGNR": "Genre",
    "IKEY": "Keywords",
    "IMED": "Medium",
    "INAM": "Title",
    "IPRD": "Album",
    "ISBJ": "Subject",
    "ISFT": "Software",
    "ISRC": "Source",
    "ISRF": "Source Form",
    "ITCH": "Technician",
    "ITRK": "Track Number",
}
"""Mapping of the common RIFF INFO four character codes to descriptions."""


class _InfoEntry(object):
    """A single key/value pair inside a ``LIST/INFO`` chunk.

    ``data`` is stored exactly as it appears in the file. Values which are
    not valid text therefore survive a load/save round trip unchanged.
    """

    __slots__ = ("id", "data")

    def __init__(self, id_, data):
        self.id = id_
        self.data = data

    def __repr__(self):
        return "<_InfoEntry %r>" % (self.id,)


def _lookup_key(key):
    """Convert a mapping key into the raw four byte INFO code.

    Arbitrary (also non ASCII) four byte codes can be present in files, so
    lookups accept any four byte value. New keys are validated separately in
    :func:`_valid_new_key`.
    """

    if isinstance(key, bytes):
        id_ = key
    elif isinstance(key, str):
        try:
            id_ = key.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError("INFO tag key must be four bytes: %r" % (key,))
    else:
        raise TypeError("INFO tag key must be str or bytes, not %r"
                        % type(key).__name__)

    if len(id_) != 4:
        raise ValueError("INFO tag key must be four bytes: %r" % (key,))
    return id_


def _valid_new_key(id_):
    """Return whether ``id_`` may be used for a new INFO entry."""

    return all(0x20 <= byte <= 0x7E for byte in id_)


def _encode_value(value):
    """Turn a tag value into the raw bytes stored in the file.

    Strings are UTF-8 encoded and NUL terminated. Bytes are written
    verbatim, which allows callers to store non-text values; the caller is
    responsible for any desired NUL terminator.
    """

    if isinstance(value, str):
        data = value.encode("utf-8") + b"\x00"
    elif isinstance(value, bytes):
        data = value
    elif isinstance(value, bytearray):
        data = bytes(value)
    else:
        raise TypeError("INFO tag value must be str or bytes, not %r"
                        % type(value).__name__)

    _check_value_size(data)
    return data


def _check_value_size(data):
    """Raise if a raw INFO value can not be stored.

    A RIFF sub chunk needs eight header bytes and, for an odd sized value,
    one padding byte on top of the value itself, all described by the
    ``LIST`` chunk's 32 bit size field.
    """

    if 8 + len(data) + (len(data) & 1) > _MAX_CHUNK_SIZE - len(_INFO_NAME):
        raise InfoError("INFO tag value is too large (%i bytes)" % len(data))


def _decode_value(data):
    """Return the text representation of raw INFO value bytes.

    Trailing NUL terminators and padding are removed. UTF-8 is preferred,
    but files in the wild use other encodings; Latin-1 never fails and
    preserves every byte value. Use :meth:`RiffInfo.get_raw` when the exact
    bytes matter.
    """

    data = data.rstrip(b"\x00")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _file_size(fileobj):
    fileobj.seek(0, 2)
    return fileobj.tell()


def _find_info_chunks(fileobj, root):
    """Find the top level ``LIST`` chunks whose type is ``INFO``.

    RIFF sub chunks are scanned manually instead of using
    :meth:`IffContainerChunkMixin.subchunks` so that a malformed chunk
    elsewhere in the file does not hide an INFO chunk, and so non ASCII
    chunk IDs do not abort the scan.

    Returns:
        tuple: ``(chunks, truncated)`` where chunks is a list of
        ``(offset, declared_size)`` tuples and truncated is `True` if a
        chunk claimed more data than the file holds.
    """

    file_size = _file_size(fileobj)
    declared_end = root.data_offset + root.data_size
    scan_end = min(declared_end, file_size)
    offset = root.data_offset + len(_INFO_NAME)
    chunks = []
    # The RIFF chunk itself claiming more data than the file holds is also
    # a truncation, even though all present chunks may be complete.
    truncated = declared_end > file_size

    while offset + 8 <= scan_end:
        fileobj.seek(offset)
        header = fileobj.read(8)
        if len(header) < 8:
            truncated = True
            break

        id_ = header[:4]
        size = struct.unpack("<I", header[4:])[0]

        if id_ == b"LIST":
            fileobj.seek(offset + 8)
            if fileobj.read(len(_INFO_NAME)) == _INFO_NAME:
                chunks.append((offset, size))

        data_end = offset + 8 + size
        if data_end > scan_end:
            truncated = True
            break
        offset = data_end + (size & 1)
        if offset > scan_end:
            # Only the final padding byte is missing, no data was lost.
            offset = scan_end

    if offset < scan_end:
        # Incomplete trailing bytes which do not form a chunk header.
        truncated = True

    return chunks, truncated


def _read_payload(fileobj, offset, data_size, chunk_end):
    """Read the payload of a ``LIST/INFO`` chunk without trusting its size.

    ``chunk_end`` bounds the read to the enclosing RIFF chunk, so trailing
    data outside of it is never mistaken for tag data.

    Returns ``(payload, truncated)`` where payload excludes the ``INFO``
    container name.
    """

    available = max(0, chunk_end - (offset + 8))
    to_read = min(data_size, available)
    truncated = to_read < data_size

    fileobj.seek(offset + 8)
    data = fileobj.read(to_read)

    if data[:len(_INFO_NAME)] != _INFO_NAME:
        return b"", True

    return data[len(_INFO_NAME):], truncated


def _parse_entries(payload):
    """Parse raw INFO sub chunk data.

    Returns ``(entries, truncated)``. A sub chunk whose declared size runs
    past the end of the payload is kept with the bytes that are present and
    marks the result as truncated. Incomplete trailing bytes are dropped.
    """

    entries = []
    truncated = False
    pos = 0
    length = len(payload)

    while pos < length:
        if length - pos < 8:
            truncated = True
            break

        id_ = payload[pos:pos + 4]
        size = struct.unpack("<I", payload[pos + 4:pos + 8])[0]
        start = pos + 8

        if size > length - start:
            entries.append(_InfoEntry(id_, payload[start:]))
            truncated = True
            break

        entries.append(_InfoEntry(id_, payload[start:start + size]))
        pos = start + size
        if size & 1:
            if pos >= length:
                # The even byte padding required by RIFF is missing.
                truncated = True
            else:
                pos += 1

    return entries, truncated


def _serialize_entries(entries):
    """Serialize INFO entries into a complete ``LIST/INFO`` payload."""

    if not entries:
        return b""

    body = bytearray()
    for entry in entries:
        if len(entry.id) != 4:
            raise InfoError("Invalid INFO chunk ID %r" % (entry.id,))
        _check_value_size(entry.data)
        body += entry.id
        body += struct.pack("<I", len(entry.data))
        body += entry.data
        if len(entry.data) & 1:
            body += b"\x00"

    if len(body) + len(_INFO_NAME) > _MAX_CHUNK_SIZE:
        raise InfoError("INFO chunk is too large")

    return _INFO_NAME + bytes(body)


def _compute_root_size(root, old_file_size, size_diff):
    """Return the RIFF data size after ``size_diff`` bytes were inserted.

    The size is derived from the previous one so arbitrary data trailing the
    RIFF chunk stays outside of it. A RIFF size which extended past the end
    of the file (a truncated file) is repaired to end at the file end.
    """

    declared_end = root.data_offset + root.data_size
    old_end = min(declared_end, old_file_size)
    return max(0, old_end - root.data_offset) + size_diff


def _check_root_size(data_size):
    """Raise if a RIFF data size can not be described in 32 bits."""

    if data_size > _MAX_CHUNK_SIZE:
        raise InfoError("RIFF file is too large to describe in 32 bits")


def _fix_root_size(fileobj, root, old_file_size):
    """Recompute and write the RIFF size after the file changed."""

    new_file_size = _file_size(fileobj)
    data_size = _compute_root_size(
        root, old_file_size, new_file_size - old_file_size)
    _check_root_size(data_size)

    root.data_size = data_size
    root._calculate_size()
    fileobj.seek(root.offset + 4)
    root.write_size()


def _chunk_span(offset, data_size, limit):
    """Return the number of file bytes a chunk occupies.

    The size is clamped to ``limit`` so a chunk whose declared size was
    truncated is treated as ending at the enclosing RIFF chunk / file end.
    """

    return max(0, min(8 + data_size + (data_size & 1), limit - offset))


def _remove_chunk(fileobj, offset, data_size, limit):
    """Remove a chunk (including padding) tolerating a truncated size."""

    size = _chunk_span(offset, data_size, limit)
    if size > 0:
        delete_bytes(fileobj, size, offset)


def _replace_chunk(fileobj, offset, data_size, blob, limit):
    """Replace a chunk at ``offset`` with the serialized ``blob``."""

    old_size = _chunk_span(offset, data_size, limit)
    resize_bytes(fileobj, old_size, len(blob), offset)
    fileobj.seek(offset)
    fileobj.write(blob)


def _insert_chunk(fileobj, offset, blob):
    """Insert ``blob`` at ``offset``, keeping the chunk word aligned."""

    prefix = b""
    if offset & 1:
        # Chunks should start at an even offset. If the RIFF data before
        # the new chunk has an odd length add a single padding byte.
        prefix = b"\x00"

    data = prefix + blob
    insert_bytes(fileobj, len(data), offset)
    fileobj.seek(offset)
    fileobj.write(data)


class RiffInfo(DictMixin, Metadata):
    """RiffInfo(filething=None)

    RIFF ``LIST/INFO`` tags, as used by WAVE (and other RIFF) files.

    The mapping keys are the four character codes stored in the file, for
    example ``INAM`` for the title and ``IART`` for the artist. Common codes
    are listed in :data:`INFO_TAG_NAMES`; unknown codes are exposed by their
    raw four character code and are written back unchanged unless they are
    explicitly modified.

    Values are strings. A value may also be assigned as bytes, which is
    stored verbatim; :meth:`get_raw` returns the exact bytes stored in the
    file. Loaded entries keep their exact bytes until their value is
    changed, so values which are not valid UTF-8 survive a load/save round
    trip.

    If a key occurs more than once, mapping access returns the last value
    and :meth:`getall` returns every value in file order. Assigning a key
    replaces all of its occurrences with a single new entry at the position
    of the first one. Deleting a key removes all of them.

    Attributes:
        truncated (bool): `True` if the file contained a ``LIST/INFO``
            chunk or a sub chunk whose declared size extended past the end
            of the file, or if the chunk scan stopped early. Such files can
            still be read and saved; saving rewrites the chunk with correct
            sizes.
    """

    __module__ = "mutagen.wave"

    def __init__(self, *args, **kwargs):
        self._entries = []
        self.truncated = False
        super(RiffInfo, self).__init__(*args, **kwargs)

    @convert_error(IOError, InfoError)
    @loadfile()
    def load(self, filething):
        """Load INFO tags from a RIFF file.

        Args:
            filething (filething): filename or file object
        Raises:
            mutagen.wave.error: if the file is not a valid RIFF file
        """

        fileobj = filething.fileobj
        self._entries = []
        self.truncated = False

        riff_file = RiffFile(fileobj)
        root = riff_file.root
        chunk_end = min(root.data_offset + root.data_size,
                        _file_size(fileobj))
        chunks, truncated = _find_info_chunks(fileobj, root)

        entries = []
        for offset, data_size in chunks:
            payload, payload_truncated = _read_payload(
                fileobj, offset, data_size, chunk_end)
            parsed, entries_truncated = _parse_entries(payload)
            entries.extend(parsed)
            truncated = truncated or payload_truncated or entries_truncated

        self._entries = entries
        self.truncated = truncated

    @convert_error(IOError, InfoError)
    @loadfile(writable=True)
    def save(self, filething=None):
        """Save the INFO tags to the RIFF file.

        A ``LIST/INFO`` chunk is created if it does not exist yet, and
        removed again when no tags are left. Its size, the enclosing RIFF
        size and the even byte padding are recomputed. No other chunk,
        including an existing ID3 chunk and the audio data, is modified.
        All values are encoded and validated before the file is touched, so
        invalid input cannot leave a half written chunk behind.

        If the file contains several ``LIST/INFO`` chunks they are merged
        into the first one.

        Raises:
            mutagen.wave.InfoError: if the tags could not be written
        """

        fileobj = filething.fileobj
        riff_file = RiffFile(fileobj)
        root = riff_file.root
        old_file_size = _file_size(fileobj)

        # Serialize first: this validates keys and sizes and means a bad
        # value never modifies the file.
        payload = _serialize_entries(self._entries)
        chunks, _ = _find_info_chunks(fileobj, root)
        chunk_end = min(root.data_offset + root.data_size, old_file_size)

        if not payload:
            # No tags left: remove every INFO chunk.
            removed = sum(_chunk_span(offset, size, chunk_end)
                          for offset, size in chunks)
            _check_root_size(
                _compute_root_size(root, old_file_size, -removed))
            for offset, data_size in reversed(chunks):
                _remove_chunk(fileobj, offset, data_size, chunk_end)
        else:
            blob = bytearray()
            blob += b"LIST"
            blob += struct.pack("<I", len(payload))
            blob += payload
            if len(payload) & 1:
                blob += b"\x00"

            if chunks:
                # Merge additional INFO chunks into the first one. Removing
                # the later chunks first keeps the earlier offsets valid.
                removed = sum(_chunk_span(offset, size, chunk_end)
                              for offset, size in chunks[1:])
                first_size = _chunk_span(
                    chunks[0][0], chunks[0][1], chunk_end)
                _check_root_size(_compute_root_size(
                    root, old_file_size, len(blob) - removed - first_size))
                for offset, data_size in reversed(chunks[1:]):
                    _remove_chunk(fileobj, offset, data_size, chunk_end)
                _replace_chunk(fileobj, chunks[0][0], chunks[0][1],
                               bytes(blob), chunk_end)
            else:
                # Append at the end of the RIFF chunk. Chunks are aligned
                # to even offsets, and data trailing the RIFF chunk is
                # never touched.
                declared_end = root.data_offset + root.data_size
                offset = min(declared_end, old_file_size)
                added = len(blob) + (offset & 1)
                _check_root_size(
                    _compute_root_size(root, old_file_size, added))
                _insert_chunk(fileobj, offset, bytes(blob))

        _fix_root_size(fileobj, root, old_file_size)
        fileobj.flush()
        self.truncated = False

    @convert_error(IOError, InfoError)
    @loadfile(writable=True)
    def delete(self, filething=None):
        """Remove the ``LIST/INFO`` chunk from the RIFF file.

        Other LIST chunks and other tags (for example ID3) are kept.
        """

        fileobj = filething.fileobj
        riff_file = RiffFile(fileobj)
        root = riff_file.root
        old_file_size = _file_size(fileobj)

        chunk_end = min(root.data_offset + root.data_size, old_file_size)
        chunks, _ = _find_info_chunks(fileobj, root)
        for offset, data_size in reversed(chunks):
            _remove_chunk(fileobj, offset, data_size, chunk_end)

        _fix_root_size(fileobj, root, old_file_size)
        fileobj.flush()
        self._entries = []
        self.truncated = False

    def __getitem__(self, key):
        id_ = _lookup_key(key)
        for entry in reversed(self._entries):
            if entry.id == id_:
                return _decode_value(entry.data)
        raise KeyError(key)

    def __setitem__(self, key, value):
        id_ = _lookup_key(key)

        indices = [i for i, entry in enumerate(self._entries)
                   if entry.id == id_]
        if not indices and not _valid_new_key(id_):
            raise ValueError(
                "INFO tag key must be four printable ASCII characters: %r"
                % (key,))

        data = _encode_value(value)

        if indices:
            self._entries[indices[0]] = _InfoEntry(id_, data)
            for index in reversed(indices[1:]):
                del self._entries[index]
        else:
            self._entries.append(_InfoEntry(id_, data))

    def __delitem__(self, key):
        id_ = _lookup_key(key)
        remaining = [entry for entry in self._entries if entry.id != id_]
        if len(remaining) == len(self._entries):
            raise KeyError(key)
        self._entries = remaining

    def keys(self):
        """Return the unique INFO codes in file order."""

        keys = []
        seen = set()
        for entry in self._entries:
            if entry.id not in seen:
                seen.add(entry.id)
                keys.append(entry.id.decode("latin-1"))
        return keys

    def getall(self, key):
        """Return all values for a key in file order.

        Raises:
            KeyError: if the key is not present
        """

        id_ = _lookup_key(key)
        values = [_decode_value(entry.data) for entry in self._entries
                  if entry.id == id_]
        if not values:
            raise KeyError(key)
        return values

    def get_raw(self, key):
        """Return the raw bytes of the last value for a key.

        Raises:
            KeyError: if the key is not present
        """

        id_ = _lookup_key(key)
        for entry in reversed(self._entries):
            if entry.id == id_:
                return entry.data
        raise KeyError(key)

    def getall_raw(self, key):
        """Return the raw bytes of every value for a key in file order.

        Raises:
            KeyError: if the key is not present
        """

        id_ = _lookup_key(key)
        values = [entry.data for entry in self._entries
                  if entry.id == id_]
        if not values:
            raise KeyError(key)
        return values

    def raw_items(self):
        """Return ``(key, raw bytes)`` pairs in file order.

        Unlike :meth:`items` this includes duplicate keys and does not
        decode the values.
        """

        return [(entry.id.decode("latin-1"), entry.data)
                for entry in self._entries]

    def pprint(self):
        """Return the INFO tags as ``key=value`` lines in file order."""

        return "\n".join("%s=%s" % item for item in self.items())


#: Alias for :class:`RiffInfo`.
InfoTags = RiffInfo


class _WaveFile(RiffFile):
    """Representation of a RIFF/WAVE file"""

    def __init__(self, fileobj):
        RiffFile.__init__(self, fileobj)

        if self.file_type != u'WAVE':
            raise error("Expected RIFF/WAVE.")

        # Normalize ID3v2-tag-chunk to lowercase
        if u'ID3' in self:
            self[u'ID3'].id = u'id3'


class WaveStreamInfo(StreamInfo):
    """WaveStreamInfo()

    Microsoft WAVE file information.

    Information is parsed from the 'fmt' & 'data'chunk of the RIFF/WAVE file

    Attributes:
        length (`float`): audio length, in seconds
        bitrate (`int`): audio bitrate, in bits per second
        channels (`int`): The number of audio channels
        sample_rate (`int`): audio sample rate, in Hz
        bits_per_sample (`int`): The audio sample size
    """

    length = 0.0
    bitrate = 0
    channels = 0
    sample_rate = 0
    bits_per_sample = 0

    SIZE = 16

    @convert_error(IOError, error)
    def __init__(self, fileobj):
        """Raises error"""

        wave_file = _WaveFile(fileobj)
        try:
            format_chunk = wave_file[u'fmt']
        except KeyError as e:
            raise error(str(e))

        data = format_chunk.read()
        if len(data) < 16:
            raise InvalidChunk()

        # RIFF: http://soundfile.sapp.org/doc/WaveFormat/
        #  Python struct.unpack:
        #    https://docs.python.org/2/library/struct.html#byte-order-size-and-alignment
        info = struct.unpack('<HHLLHH', data[:self.SIZE])
        self.audio_format, self.channels, self.sample_rate, byte_rate, \
            block_align, self.bits_per_sample = info
        self.bitrate = self.channels * self.bits_per_sample * self.sample_rate

        # Calculate duration
        self._number_of_samples = 0
        if block_align > 0:
            try:
                data_chunk = wave_file[u'data']
                self._number_of_samples = data_chunk.data_size / block_align
            except KeyError:
                pass

        if self.sample_rate > 0:
            self.length = self._number_of_samples / self.sample_rate

    def pprint(self):
        return u"%d channel RIFF @ %d bps, %s Hz, %.2f seconds" % (
            self.channels, self.bitrate, self.sample_rate, self.length)


class _WaveID3(ID3):
    """A Wave file with ID3v2 tags"""

    def _pre_load_header(self, fileobj):
        try:
            fileobj.seek(_WaveFile(fileobj)[u'id3'].data_offset)
        except (InvalidChunk, KeyError):
            raise ID3NoHeaderError("No ID3 chunk")

    @convert_error(IOError, error)
    @loadfile(writable=True)
    def save(self, filething, v1=1, v2_version=4, v23_sep='/', padding=None):
        """Save ID3v2 data to the Wave/RIFF file"""

        fileobj = filething.fileobj
        wave_file = _WaveFile(fileobj)

        if u'id3' not in wave_file:
            wave_file.insert_chunk(u'id3')

        chunk = wave_file[u'id3']

        try:
            data = self._prepare_data(
                fileobj, chunk.data_offset, chunk.data_size, v2_version,
                v23_sep, padding)
        except ID3Error as e:
            reraise(error, e, sys.exc_info()[2])

        chunk.resize(len(data))
        chunk.write(data)

    def delete(self, filething):
        """Completely removes the ID3 chunk from the RIFF/WAVE file"""

        delete(filething)
        self.clear()


@convert_error(IOError, error)
@loadfile(method=False, writable=True)
def delete(filething):
    """Completely removes the ID3 chunk from the RIFF/WAVE file"""

    try:
        _WaveFile(filething.fileobj).delete_chunk(u'id3')
    except KeyError:
        pass


class WAVE(FileType):
    """WAVE(filething)

    A Waveform Audio File Format
    (WAVE, or more commonly known as WAV due to its filename extension)

    Arguments:
        filething (filething)

    Attributes:
        tags (`mutagen.id3.ID3`): the ID3v2 tag, or `None` if there is none
        info_tags (`RiffInfo`): the RIFF ``LIST/INFO`` tags. This is always
            available, also when the file has no INFO chunk yet; it is
            empty in that case.
        info (`WaveStreamInfo`)
    """

    _mimes = ["audio/wav", "audio/wave"]

    def __init__(self, *args, **kwargs):
        self.info_tags = RiffInfo()
        super(WAVE, self).__init__(*args, **kwargs)

    @staticmethod
    def score(filename, fileobj, header):
        filename = filename.lower()

        riff_wave = header.startswith(b"RIFF") and header[8:12] == b"WAVE"
        return (2 * riff_wave
                + endswith(filename, b".wav") + endswith(filename, b".wave"))

    def add_tags(self):
        """Add an empty ID3 tag to the file."""
        if self.tags is None:
            self.tags = _WaveID3()
        else:
            raise error("an ID3 tag already exists")

    @convert_error(IOError, error)
    @loadfile()
    def load(self, filething, **kwargs):
        """Load stream and tag information from a file."""

        fileobj = filething.fileobj
        self.info = WaveStreamInfo(fileobj)
        fileobj.seek(0, 0)

        id3_error = None
        try:
            self.tags = _WaveID3(fileobj, **kwargs)
        except ID3NoHeaderError:
            self.tags = None
        except ID3Error as e:
            # Still expose the INFO tags, they are independent of ID3.
            id3_error = e
            self.tags = None
        else:
            self.tags.filename = self.filename

        fileobj.seek(0, 0)
        self.info_tags = RiffInfo(fileobj)
        self.info_tags.filename = self.filename

        if id3_error is not None:
            raise error(id3_error)

    @loadfile(writable=True)
    def save(self, filething=None, **kwargs):
        """save(filething=None, **kwargs)

        Save both the ID3v2 and the RIFF ``LIST/INFO`` tags.

        The ID3 tag (if any) is written first, then the INFO tags. The two
        formats are stored in separate chunks and do not overwrite each
        other. Use ``id3=False`` or ``info=False`` to save only one of them.
        """

        save_id3 = kwargs.pop("id3", True)
        save_info = kwargs.pop("info", True)

        if save_id3 and self.tags is not None:
            self.tags.save(filething, **kwargs)

        if save_info and self.info_tags is not None:
            self.info_tags.save(filething)

    @loadfile(writable=True)
    def delete(self, filething=None):
        """delete(filething=None)

        Remove both the ID3v2 and the RIFF ``LIST/INFO`` tags.
        """

        if self.tags is not None:
            self.tags.delete(filething)
        if self.info_tags is not None:
            self.info_tags.delete(filething)

    def pprint(self):
        """Return stream information and both tag sets as text."""

        stream = "%s (%s)" % (self.info.pprint(), self.mime[0])
        parts = [stream]
        if self.tags is not None:
            text = self.tags.pprint()
            if text:
                parts.append(text)
        if self.info_tags:
            parts.append(self.info_tags.pprint())
        return "\n".join(parts)


Open = WAVE
