"""Background-noise reduction for the microphone (spectral gating, numpy only).

It keeps learning what the room sounds like when nobody is talking close to the mic (fans, AC, keyboard
clatter, the murmur of a co-working space) and turns those frequencies down, so your voice stands out.
A voice right next to someone else's can't be separated this way; the wake word handles that.

  Denoiser(rate).process(block)  streaming, for live calls (about 32 ms delay)
  denoise(samples, rate)         a whole recording at once (Classic mode, wake-word checks)
"""
from __future__ import annotations

import numpy as np

LEVELS = {"off": None, "normal": (1.6, 0.14), "strong": (2.6, 0.07)}   # (over-subtraction, gain floor)


def level() -> str:
    from . import schedule
    v = schedule.get_setting("noise_reduction") or "normal"
    return v if v in LEVELS else "normal"


class Denoiser:
    def __init__(self, rate: int = 16000, strength: str = "normal"):
        self.n = 512 if rate >= 16000 else 256
        self.hop = self.n // 2
        self.win = np.sqrt(np.hanning(self.n + 1)[:-1]).astype(np.float32)   # sqrt-Hann in and out = perfect overlap-add
        self.over, self.floor = LEVELS.get(strength) or LEVELS["normal"]
        self.inbuf = np.zeros(self.n - self.hop, np.float32)
        self.outbuf = np.zeros(self.n, np.float32)
        self.noise: np.ndarray | None = None
        self.prev = np.ones(self.n // 2 + 1, np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.inbuf, x.astype(np.float32)])
        out, pos, n, hop = [], 0, self.n, self.hop
        while pos + n <= buf.size:
            spec = np.fft.rfft(buf[pos:pos + n] * self.win)
            p = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
            if self.noise is None:
                self.noise = p.copy()
            # learn the room's sound from frames that aren't speech (average, not minimum: the minimum of
            # noisy frames is ~8 dB below the real noise level, which would leave most of it in)
            quiet = p.sum() < 2.5 * self.noise.sum()
            self.noise += (p - self.noise) * (0.08 if quiet else 0.002)
            g = np.sqrt(np.clip(1.0 - self.over * self.noise / (p + 1e-10), self.floor ** 2, 1.0))
            g = np.convolve(g, (0.25, 0.5, 0.25), mode="same")             # smooth across frequency
            g = np.where(g > self.prev, g, 0.65 * self.prev + 0.35 * g)    # open fast, close gently (no "musical" noise)
            self.prev = g.astype(np.float32)
            self.outbuf += np.fft.irfft(spec * g, n).astype(np.float32) * self.win
            out.append(self.outbuf[:hop].copy())
            self.outbuf = np.concatenate([self.outbuf[hop:], np.zeros(hop, np.float32)])
            pos += hop
        self.inbuf = buf[pos:]
        return np.concatenate(out) if out else np.zeros(0, np.float32)


def denoise(x: np.ndarray, rate: int = 16000, strength: str = "normal") -> np.ndarray:
    """A whole recording: the noise is the average of its quietest quarter (vectorised, fast)."""
    params = LEVELS.get(strength)
    if not params or x.size < 2048:
        return x
    over, floor = params
    n = 512 if rate >= 16000 else 256
    hop = n // 2
    win = np.sqrt(np.hanning(n + 1)[:-1]).astype(np.float32)
    pad = np.concatenate([np.zeros(hop, np.float32), x.astype(np.float32), np.zeros(n, np.float32)])
    count = (pad.size - n) // hop + 1
    idx = np.arange(n)[None, :] + hop * np.arange(count)[:, None]
    spec = np.fft.rfft(pad[idx] * win, axis=1)
    p = spec.real ** 2 + spec.imag ** 2
    energy = p.sum(axis=1)
    quiet = energy <= np.percentile(energy, 25)                             # the quietest quarter = the room
    noise = p[quiet].mean(axis=0)
    g = np.sqrt(np.clip(1.0 - over * noise / (p + 1e-10), floor ** 2, 1.0))
    k = np.array([0.25, 0.5, 0.25])
    g = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, g)
    g = np.maximum(g, 0.65 * np.vstack([g[:1], g[:-1]]))                  # don't chop word endings
    frames = np.fft.irfft(spec * g, n, axis=1) * win
    out = np.zeros(pad.size, np.float32)
    np.add.at(out, idx, frames.astype(np.float32))
    return out[hop:hop + x.size]
