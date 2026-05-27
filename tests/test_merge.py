from listenerd.merge import Segment, TaggedSegment, merge_segments


def test_merge_empty_inputs_returns_empty():
    assert merge_segments([], []) == []


def test_merge_only_mic_segments_tags_all_me():
    mic = [Segment(0, 1000, "hello"), Segment(2000, 3000, "world")]
    result = merge_segments(mic, [])
    assert result == [
        TaggedSegment(0, 1000, "hello", "Me"),
        TaggedSegment(2000, 3000, "world", "Me"),
    ]


def test_merge_only_system_segments_tags_all_others():
    system = [Segment(500, 1500, "hi")]
    result = merge_segments([], system)
    assert result == [TaggedSegment(500, 1500, "hi", "Others")]


def test_merge_interleaves_chronologically():
    mic = [Segment(0, 1000, "I say first"), Segment(3000, 4000, "I say third")]
    system = [Segment(1500, 2500, "they say second")]
    result = merge_segments(mic, system)
    assert [s.text for s in result] == [
        "I say first",
        "they say second",
        "I say third",
    ]
    assert [s.speaker for s in result] == ["Me", "Others", "Me"]


def test_merge_ties_break_with_mic_first():
    mic = [Segment(1000, 2000, "me")]
    system = [Segment(1000, 2000, "others")]
    result = merge_segments(mic, system)
    assert result[0].speaker == "Me"
    assert result[1].speaker == "Others"


def test_merge_strips_whitespace_in_text():
    mic = [Segment(0, 1000, "  hello  ")]
    result = merge_segments(mic, [])
    assert result[0].text == "hello"


def test_merge_drops_segments_with_empty_text():
    mic = [Segment(0, 1000, ""), Segment(2000, 3000, "real")]
    system = [Segment(1500, 1600, "   ")]
    result = merge_segments(mic, system)
    assert len(result) == 1
    assert result[0].text == "real"
