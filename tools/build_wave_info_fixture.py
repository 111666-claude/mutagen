import os
import hashlib
import struct
from io import BytesIO

from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TDRC, TCON, Encoding


def riff_chunk(cid, payload):
    data = cid + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        data += b"\x00"
    return data


def make_info(entries):
    body = bytearray(b"INFO")
    for cid, value in entries:
        body += cid + struct.pack("<I", len(value)) + value
        if len(value) & 1:
            body += b"\x00"
    return bytes(body)


def main(path):
    sample_rate = 16000
    channels = 2
    bits = 8
    # Fixed, deterministic PCM: a sawtooth-ish pattern that differs from
    # silence so the audio payload can be identified by its hash.
    frames = sample_rate * 2
    pcm = bytearray()
    for i in range(frames):
        left = (i * 7 + 3) & 0xFF
        right = (i * 13 + 11) & 0xFF
        pcm += bytes((left, right))

    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    fmt = struct.pack("<HHLLHH", 1, channels, sample_rate, byte_rate,
                      block_align, bits)

    info_entries = [
        (b"IPRD", b"Fixture Album\x00"),
        (b"IART", b"Fixture Artist\x00"),
        (b"IGNR", b"Test Tone\x00"),
        (b"INAM", b"Fixture Title\x00"),
        (b"ITRK", b"07\x00"),
        (b"ICRD", b"2024\x00"),
        # An unknown INFO key with plain text.
        (b"XCMT", b"Custom note\x00"),
        # An unknown INFO key with non-text bytes. It must survive a
        # load/save round trip byte for byte.
        (b"XRAW", b"\x00\x01\xfe\xff\x10"),
    ]

    id3 = ID3()
    id3.add(TIT2(encoding=Encoding.UTF8, text="ID3 Title"))
    id3.add(TPE1(encoding=Encoding.UTF8, text="ID3 Artist"))
    id3.add(TALB(encoding=Encoding.UTF8, text="ID3 Album"))
    id3.add(TRCK(encoding=Encoding.UTF8, text="3/9"))
    id3.add(TDRC(encoding=Encoding.UTF8, text="2023"))
    id3.add(TCON(encoding=Encoding.UTF8, text="ID3 Genre"))
    id3_buf = BytesIO()
    id3.save(id3_buf, v2_version=3)
    id3_data = id3_buf.getvalue()

    body = bytearray(b"WAVE")
    body += riff_chunk(b"fmt ", fmt)
    body += riff_chunk(b"data", bytes(pcm))
    body += riff_chunk(b"LIST", make_info(info_entries))
    body += riff_chunk(b"ID3 ", id3_data)

    data = b"RIFF" + struct.pack("<I", len(body)) + bytes(body)
    with open(path, "wb") as h:
        h.write(data)

    print("wrote", path, len(data))
    print("pcm sha256", hashlib.sha256(bytes(pcm)).hexdigest())
    print("file sha256", hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "data",
        "pattern-2s-PCM-16000-08-INFO-ID3.wav"))
