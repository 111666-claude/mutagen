# Copyright (C) 2026  Mutagen Authors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""Chapter information shared by the format specific implementations.

A chapter marks a point inside an audio stream with a start time and a
title. The start time is always expressed in milliseconds so that the
same chapter list can be moved between formats with different native
time bases (e.g. ID3v2 chapters and the MPEG-4 ``chpl`` atom).
"""

__all__ = ["Chapter"]


class Chapter(object):
    """Chapter(start, title)

    A single chapter with a start time and a title.

    Attributes:
        start (`int`): start time relative to the beginning of the stream,
            in milliseconds. Has to be zero or positive.
        title (`str`): human readable chapter title
    """

    def __init__(self, start, title):
        self.start = start
        self.title = title

    def __eq__(self, other):
        if not isinstance(other, Chapter):
            return NotImplemented
        return self.start == other.start and self.title == other.title

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other):
        if not isinstance(other, Chapter):
            return NotImplemented
        return self.start < other.start

    def __hash__(self):
        return hash((self.start, self.title))

    def __repr__(self):
        return "Chapter(%r, %r)" % (self.start, self.title)
