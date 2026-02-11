#!/usr/bin/env python3
"""
Decoder Volume CV Knowledge Base

Maps decoder families to their master volume CV number, range, and default
value. Used by audio_calibrate.py to compute volume adjustments.

Usage:
    from decoder_volume import lookup_decoder, compute_new_cv

    info = lookup_decoder("LokSound 5 XL")
    # -> {"cv": 63, "min": 0, "max": 192, "default": 180, "decoder_name": "LokSound 5"}

    new_val = compute_new_cv(current_cv=180, delta_db=6.0, cv_min=0, cv_max=192)
    # -> 90  (halve amplitude to reduce 6 dB)
"""

import math


# Decoder family -> volume CV info.
# family_match: lowercase substrings to match against JMRI's getDecoderModel().
DECODER_VOLUME_TABLE = {
    "LokSound 5": {
        "cv": 63,
        "min": 0,
        "max": 192,
        "default": 180,
        "family_match": ["loksound 5", "loksound5", "esu loksound"],
    },
    "SoundTraxx Tsunami2": {
        "cv": 128,
        "min": 0,
        "max": 255,
        "default": 255,
        "family_match": ["tsunami2", "tsunami 2", "soundtraxx tsunami"],
    },
    "SoundTraxx Econami": {
        "cv": 128,
        "min": 0,
        "max": 255,
        "default": 255,
        "family_match": ["econami", "soundtraxx econami"],
    },
    "Digitrax SDH": {
        "cv": 58,
        "min": 0,
        "max": 15,
        "default": 15,
        "family_match": ["digitrax sdh", "digitrax sdn", "sdh166", "sdn144"],
    },
    "BLI Paragon4": {
        "cv": 161,
        "min": 0,
        "max": 255,
        "default": 255,
        "family_match": ["paragon4", "paragon 4", "bli paragon", "paragon3",
                         "paragon 3"],
    },
    "TCS WOWSound": {
        "cv": 128,
        "min": 0,
        "max": 255,
        "default": 200,
        "family_match": ["wowsound", "wow sound", "tcs wow"],
    },
}


def lookup_decoder(decoder_type):
    """Find volume CV info for a decoder type string.

    Tries exact key match first, then case-insensitive substring match
    against family_match patterns.

    Returns dict {cv, min, max, default, decoder_name} or None.
    """
    if not decoder_type:
        return None
    dt_lower = decoder_type.lower().strip()

    # Exact key match
    if decoder_type in DECODER_VOLUME_TABLE:
        info = DECODER_VOLUME_TABLE[decoder_type]
        return {
            "cv": info["cv"], "min": info["min"],
            "max": info["max"], "default": info["default"],
            "decoder_name": decoder_type,
        }

    # Substring match against family patterns
    for name, info in DECODER_VOLUME_TABLE.items():
        for pattern in info["family_match"]:
            if pattern in dt_lower:
                return {
                    "cv": info["cv"], "min": info["min"],
                    "max": info["max"], "default": info["default"],
                    "decoder_name": name,
                }
    return None


def compute_new_cv(current_cv, delta_db, cv_min=0, cv_max=255):
    """Compute new volume CV value to adjust by -delta_db.

    delta_db: positive means target is louder than reference,
              so we need to *reduce* volume.

    CV value is proportional to amplitude (linear volume control).
      dB = 20 * log10(amplitude)
    To shift by -delta_db:
      ratio = 10^(-delta_db / 20)
      new_cv = round(current_cv * ratio)
    """
    if current_cv <= 0:
        return cv_min

    ratio = 10.0 ** (-delta_db / 20.0)
    new_cv = round(current_cv * ratio)
    return max(cv_min, min(cv_max, new_cv))
