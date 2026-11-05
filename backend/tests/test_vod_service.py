"""VOD 播放地址选择：优先 HLS / H.264，避免无转码的 HEVC 原片。"""

from __future__ import annotations

from app.services.vod_service import (
    _extract_duration,
    _pick_play_url,
    _sign_hotlink_url,
)


def test_sign_hotlink_url_matches_tencent_doc_example() -> None:
    url = _sign_hotlink_url(
        "http://example.com/dir1/dir2/myVideo.mp4",
        expire_at=0x5A71AFC0,
        key="24FEQmTzro4V5u3D5epW",
        us="72d4cd1101",
    )

    assert url == (
        "http://example.com/dir1/dir2/myVideo.mp4"
        "?t=5a71afc0&us=72d4cd1101"
        "&sign=3d8488faeb37d52d6bf63b63c1b171c3"
    )


def test_pick_play_url_prefers_h264_transcode_over_hevc_original() -> None:
    media_info = {
        "BasicInfo": {
            "MediaUrl": "https://example.vod-qcloud.com/original.mp4",
        },
        "MetaData": {
            "VideoStreamSet": [{"Codec": "hevc"}],
        },
        "TranscodeInfo": {
            "TranscodeSet": [
                {
                    "Url": "https://example.vod-qcloud.com/h264.mp4",
                    "VideoStreamSet": [{"Codec": "h264"}],
                }
            ]
        },
    }

    assert (
        _pick_play_url(media_info)
        == "https://example.vod-qcloud.com/h264.mp4"
    )


def test_pick_play_url_falls_back_to_adaptive_hls() -> None:
    media_info = {
        "AdaptiveDynamicStreamingInfo": {
            "AdaptiveDynamicStreamingSet": [
                {"Url": "https://example.vod-qcloud.com/master.m3u8"}
            ]
        },
    }

    assert (
        _pick_play_url(media_info)
        == "https://example.vod-qcloud.com/master.m3u8"
    )


def test_pick_play_url_returns_none_without_https_url() -> None:
    media_info = {
        "BasicInfo": {"MediaUrl": "http://insecure.example.com/a.mp4"},
    }

    assert _pick_play_url(media_info) is None


def test_extract_duration_prefers_basic_info() -> None:
    media_info = {
        "BasicInfo": {"Duration": 338.4},
        "TranscodeInfo": {
            "TranscodeSet": [{"Duration": 337.9}],
        },
    }

    assert _extract_duration(media_info) == 338


def test_extract_duration_falls_back_to_transcode() -> None:
    media_info = {
        "TranscodeInfo": {
            "TranscodeSet": [{"Duration": 9.05}],
        },
    }

    assert _extract_duration(media_info) == 9


def test_extract_duration_returns_zero_for_missing_or_invalid() -> None:
    assert _extract_duration(None) == 0
    assert _extract_duration({"BasicInfo": {"Duration": "unknown"}}) == 0
    assert _extract_duration({"BasicInfo": {"Duration": 0}}) == 0
