# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Procedurally generated notification sound packs.

Every pack is a pair of `(celebrate_pcm_builder, wave_pcm_builder)`
functions that return stereo int16 PCM bytes. Building all packs at
startup keeps the tray "Sound" submenu preview instant — no allocation
or synthesis happens on the audio thread.

Adding a new pack:

1. Write two builders that return PCM bytes (use `_gen_voices` or
   `_gen_bell_tone` to stay consistent with existing packs).
2. Register them in `SOUND_PACKS` under a new key.
3. The tray submenu and config persistence pick the new pack up
   automatically.
"""

import array
import math


# Sample rate used by every pack. 22.05 kHz is plenty for notification
# tones and halves the data footprint vs 44.1 kHz.
SOUND_SAMPLE_RATE = 22050

# Pack identifiers — `SOUND_PACK_OFF` is a sentinel that means "muted"
# (no PCM, mixer not touched). The tray submenu and config persistence
# both rely on `SOUND_PACK_CHOICES` being the canonical allow-list.
SOUND_PACK_OFF = "off"
DEFAULT_SOUND_PACK = "fanfare"


def _gen_voices(freqs, duration, sample_rate=SOUND_SAMPLE_RATE, fade=0.05,
                amplitude=8500, shape="sine"):
    """Stereo int16 interleaved PCM bytes for summed sine OR square voices.

    Single-frequency arg ⇒ a plain tone. Multi-frequency arg ⇒ a chord
    (waves summed sample-by-sample). Amplitude is divided across voices so
    the chord doesn't clip. A raised-cosine (Hann-style) envelope smooths
    attack and release.

    `shape`:
      - "sine"   — soft, musical (used by fanfare/minimal/wave packs)
      - "square" — snappy 8-bit character (used by retro pack)
        Squares peak at ±1 (vs sine's RMS ~0.7) so call with a lower
        amplitude to avoid sounding much louder than the sine packs.

    Output is interleaved stereo (L,R,L,R,...). pygame's mixer runs in
    stereo regardless of any `channels=1` hint, so we duplicate each sample
    into both channels — feeding mono PCM into a stereo mixer plays back
    at the wrong pitch.
    """
    if isinstance(freqs, (int, float)):
        freqs = (freqs,)
    n_samples = int(sample_rate * duration)
    fade_samples = max(1, int(sample_rate * fade))
    per_voice = amplitude / max(1, len(freqs))
    two_pi = 2 * math.pi
    buf = array.array("h")
    for i in range(n_samples):
        # Raised-cosine envelope: smooth attack + release, sustain in middle.
        if i < fade_samples:
            env = (1 - math.cos(math.pi * i / fade_samples)) / 2
        elif i > n_samples - fade_samples:
            j = n_samples - i
            env = (1 - math.cos(math.pi * j / fade_samples)) / 2
        else:
            env = 1.0
        sample = 0.0
        for f in freqs:
            if shape == "square":
                sample += per_voice * (
                    1 if math.sin(two_pi * f * i / sample_rate) >= 0
                    else -1)
            else:
                sample += per_voice * math.sin(two_pi * f * i / sample_rate)
        s = int(sample * env)
        # Clip to int16 range.
        s = max(-32768, min(32767, s))
        # Stereo: duplicate L+R.
        buf.append(s)
        buf.append(s)
    return buf.tobytes()


def _gen_bell_tone(freq, duration, sample_rate=SOUND_SAMPLE_RATE,
                   amplitude=10000):
    """Bell-like tone: fundamental + harmonic partials with exponential decay.

    More resonant than `_gen_voices` for the chime pack — the harmonics
    (2x, 3x, 4x) at decaying amplitudes give the metallic ring.
    """
    n_samples = int(sample_rate * duration)
    partials = [
        (1.0, 1.0),   # fundamental
        (2.0, 0.5),   # 1st harmonic
        (3.0, 0.25),  # 2nd
        (4.0, 0.125), # 3rd
    ]
    buf = array.array("h")
    two_pi = 2 * math.pi
    for i in range(n_samples):
        # Exponential decay shapes the whole bell.
        env = math.exp(-3.0 * i / n_samples)
        sample = 0.0
        for ratio, weight in partials:
            sample += weight * math.sin(
                two_pi * freq * ratio * i / sample_rate)
        s = int(amplitude * env * sample / sum(w for _, w in partials))
        s = max(-32768, min(32767, s))
        buf.append(s)
        buf.append(s)
    return buf.tobytes()


# ── Pack builders ─────────────────────────────────────────────────────
def _pcm_fanfare_celebrate():
    """Motivational achievement fanfare — C major arpeggio + landing triad."""
    return (
        _gen_voices(523, 0.09)
        + _gen_voices(659, 0.09)
        + _gen_voices(784, 0.11)
        + _gen_voices((523, 659, 784), 0.32, fade=0.08, amplitude=11000)
    )


def _pcm_fanfare_wave():
    """Warm two-note doorbell call (G4 → D4)."""
    return (
        _gen_voices(392, 0.18, amplitude=7000)
        + _gen_voices(294, 0.26, amplitude=7000)
    )


def _pcm_chime_celebrate():
    """Peaceful two-bell chime, ascending."""
    return _gen_bell_tone(659, 0.32) + _gen_bell_tone(880, 0.60)


def _pcm_chime_wave():
    """Single lower chime — calm 'someone's at the door' feel."""
    return _gen_bell_tone(440, 0.55)


def _pcm_retro_celebrate():
    """8-bit coin-pickup flourish — ascending square arpeggio."""
    sq = {"shape": "square", "amplitude": 5500, "fade": 0.008}
    return (
        _gen_voices(523, 0.07, **sq)
        + _gen_voices(659, 0.07, **sq)
        + _gen_voices(784, 0.07, **sq)
        + _gen_voices(1047, 0.16, **sq)
    )


def _pcm_retro_wave():
    """Two short low-high square blips."""
    sq = {"shape": "square", "amplitude": 5000, "fade": 0.008}
    return (
        _gen_voices(440, 0.07, **sq)
        + _gen_voices(587, 0.11, **sq)
    )


def _pcm_minimal_celebrate():
    """Single short soft tone — barely-there acknowledgment."""
    return _gen_voices(784, 0.13, fade=0.05, amplitude=6500)


def _pcm_minimal_wave():
    """Single short low tone — subtle nudge."""
    return _gen_voices(523, 0.11, fade=0.05, amplitude=5500)


SOUND_PACKS = {
    "fanfare":  (_pcm_fanfare_celebrate,  _pcm_fanfare_wave),
    "chime":    (_pcm_chime_celebrate,    _pcm_chime_wave),
    "retro":    (_pcm_retro_celebrate,    _pcm_retro_wave),
    "minimal":  (_pcm_minimal_celebrate,  _pcm_minimal_wave),
}
SOUND_PACK_NAMES = list(SOUND_PACKS.keys())        # display order for tray
SOUND_PACK_CHOICES = [SOUND_PACK_OFF] + SOUND_PACK_NAMES


def init_sounds():
    """Initialise pygame's mixer and pre-build a Sound pair for each pack.

    Returns `{pack_name: (celebrate_sound, wave_sound)}`. Empty dict on
    audio init failure (headless / no audio device) — callers should
    treat a missing pack as "silent".

    Pre-building every pack at startup keeps tray-menu preview instant
    and avoids audio-thread allocation later. Each pack's PCM is small
    (< 100KB) and synthesis is fast.

    Mixer note: `pygame.init()` auto-initializes the mixer at its
    defaults (44100 Hz stereo) before we get here. A bare `mixer.init()`
    with new params is then a no-op, so we `mixer.quit()` first to
    force a fresh init at OUR sample rate.

    Imported lazily so importing this module doesn't drag pygame in for
    tests that only care about PCM characteristics.
    """
    import pygame
    try:
        if pygame.mixer.get_init() is not None:
            pygame.mixer.quit()
        pygame.mixer.init(frequency=SOUND_SAMPLE_RATE, size=-16,
                          channels=2, buffer=512)
    except pygame.error as e:
        print(f"[buddy] Audio init failed, sounds disabled: {e}")
        return {}
    sounds = {}
    for pack, (cel_fn, wav_fn) in SOUND_PACKS.items():
        try:
            cel = pygame.mixer.Sound(buffer=cel_fn())
            wav = pygame.mixer.Sound(buffer=wav_fn())
            cel.set_volume(0.55)
            wav.set_volume(0.45)
            sounds[pack] = (cel, wav)
        except pygame.error as e:
            print(f"[buddy] Could not build '{pack}' sounds: {e}")
    return sounds
