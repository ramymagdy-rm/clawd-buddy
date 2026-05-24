# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the procedural sound packs.

PCM bytes are deterministic — every test runs the same builders pygame
runs at startup, so we can assert on length, framing, and amplitude
characteristics without touching the audio device.
"""

import math
import struct

import pytest

from clawd_buddy.ui import sound


# Stereo interleaved int16 — 4 bytes per sample frame.
BYTES_PER_FRAME = 4


def _frame_count(pcm):
    """Number of (L,R) frames in a stereo int16 buffer."""
    assert len(pcm) % BYTES_PER_FRAME == 0, "PCM is not a whole number of frames"
    return len(pcm) // BYTES_PER_FRAME


# ── Pack registry ────────────────────────────────────────────────────
class TestRegistry:
    def test_default_pack_is_in_packs(self):
        assert sound.DEFAULT_SOUND_PACK in sound.SOUND_PACKS

    def test_pack_names_mirror_dict_order(self):
        assert sound.SOUND_PACK_NAMES == list(sound.SOUND_PACKS.keys())

    def test_choices_starts_with_off(self):
        # The off sentinel must come first so config/tray UI conventions
        # render it consistently.
        assert sound.SOUND_PACK_CHOICES[0] == sound.SOUND_PACK_OFF

    def test_choices_covers_off_plus_every_pack(self):
        expected = {sound.SOUND_PACK_OFF, *sound.SOUND_PACK_NAMES}
        assert set(sound.SOUND_PACK_CHOICES) == expected

    def test_off_is_not_a_real_pack(self):
        assert sound.SOUND_PACK_OFF not in sound.SOUND_PACKS

    @pytest.mark.parametrize("pack", list(sound.SOUND_PACKS.keys()))
    def test_each_pack_has_two_callables(self, pack):
        cel, wav = sound.SOUND_PACKS[pack]
        assert callable(cel)
        assert callable(wav)


# ── PCM generators ───────────────────────────────────────────────────
class TestGenVoices:
    def test_single_frequency_produces_correct_frame_count(self):
        # 0.1 second at 22050 Hz → 2205 frames
        pcm = sound._gen_voices(440, 0.1)
        assert _frame_count(pcm) == int(0.1 * sound.SOUND_SAMPLE_RATE)

    def test_stereo_layout_L_equals_R(self):
        # Both channels are the same sample value — feeding mono PCM to a
        # stereo mixer plays at the wrong pitch, so the duplication
        # invariant matters.
        pcm = sound._gen_voices(440, 0.05)
        for i in range(0, len(pcm), BYTES_PER_FRAME):
            l, r = struct.unpack_from("<hh", pcm, i)
            assert l == r

    def test_envelope_starts_and_ends_at_zero(self):
        # Raised-cosine envelope should give a silent start and end frame.
        pcm = sound._gen_voices(440, 0.1)
        first = struct.unpack_from("<h", pcm, 0)[0]
        last = struct.unpack_from("<h", pcm, len(pcm) - 2)[0]
        assert first == 0
        # The last sample is close to zero but the envelope dips on the
        # final fade step — allow a tiny tolerance.
        assert abs(last) < 200

    def test_chord_amplitude_split_avoids_clipping(self):
        # Three summed sines at default amplitude must each be scaled
        # down so the combined wave doesn't exceed int16 range.
        pcm = sound._gen_voices((440, 660, 880), 0.1, amplitude=10000)
        peak = 0
        for i in range(0, len(pcm), 2):
            s = struct.unpack_from("<h", pcm, i)[0]
            peak = max(peak, abs(s))
        assert peak < 32768

    def test_square_shape_produces_bipolar_samples(self):
        # Square wave saturates either positive or negative — there's no
        # "ramp" sample between extremes once past the envelope.
        pcm = sound._gen_voices(
            440, 0.1, shape="square", amplitude=5000, fade=0.001,
        )
        middle = len(pcm) // 2 - (len(pcm) // 2) % BYTES_PER_FRAME
        sample = struct.unpack_from("<h", pcm, middle)[0]
        # Middle should be either strongly positive or strongly negative,
        # not near-zero (which would be a sine-shaped wave).
        assert abs(sample) > 1000


class TestGenBellTone:
    def test_frame_count_matches_duration(self):
        pcm = sound._gen_bell_tone(440, 0.2)
        assert _frame_count(pcm) == int(0.2 * sound.SOUND_SAMPLE_RATE)

    def test_amplitude_decays(self):
        # Exponential decay envelope — early samples should be louder
        # than late samples.
        pcm = sound._gen_bell_tone(440, 0.4)
        early_peak = late_peak = 0
        third = len(pcm) // 3
        for i in range(0, third, BYTES_PER_FRAME):
            early_peak = max(early_peak, abs(struct.unpack_from("<h", pcm, i)[0]))
        for i in range(len(pcm) - third, len(pcm), BYTES_PER_FRAME):
            late_peak = max(late_peak, abs(struct.unpack_from("<h", pcm, i)[0]))
        assert early_peak > late_peak * 2  # decisively quieter at the tail


# ── Per-pack PCM ─────────────────────────────────────────────────────
class TestPackBuilders:
    @pytest.mark.parametrize("pack", list(sound.SOUND_PACKS.keys()))
    def test_celebrate_pcm_non_empty(self, pack):
        cel_fn, _ = sound.SOUND_PACKS[pack]
        pcm = cel_fn()
        assert isinstance(pcm, (bytes, bytearray))
        assert len(pcm) > 0
        assert len(pcm) % BYTES_PER_FRAME == 0

    @pytest.mark.parametrize("pack", list(sound.SOUND_PACKS.keys()))
    def test_wave_pcm_non_empty(self, pack):
        _, wav_fn = sound.SOUND_PACKS[pack]
        pcm = wav_fn()
        assert isinstance(pcm, (bytes, bytearray))
        assert len(pcm) > 0
        assert len(pcm) % BYTES_PER_FRAME == 0

    @pytest.mark.parametrize("pack", list(sound.SOUND_PACKS.keys()))
    def test_celebrate_and_wave_differ(self, pack):
        # If a pack's celebrate and wave are byte-identical we've shipped
        # a broken pack (same sound for both events).
        cel_fn, wav_fn = sound.SOUND_PACKS[pack]
        assert cel_fn() != wav_fn()
