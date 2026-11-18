"""Acoustic echo cancellation: take the assistant's own voice out of the microphone.

On laptop speakers the mic hears the assistant about as loudly as it hears you, so "is that you, or its
echo?" can't be decided by loudness alone, and talking over it didn't work. Jarvis knows exactly what it
sent to the speaker, so an adaptive filter learns how that sound reaches the mic (speaker, room, delay) and
subtracts it. What is left is you (plus a little residual echo).

Partitioned-block frequency-domain NLMS: 256-sample blocks at 16 kHz, 16 partitions = 256 ms of echo path.
Adaptation slows down while you talk (double-talk) so your voice doesn't "un-learn" the filter.
"""
from __future__ import annotations

import threading

import numpy as np

B = 256          # block (16 ms)
P = 16           # partitions -> 4096 taps = 256 ms
N = 2 * B        # FFT size
_cache: dict[str, np.ndarray] = {}   # learned filters per mic+speaker, so the next call starts already trained


class EchoCanceller:
    def __init__(self, key: str = "", margin_ms: float = 16.0, mu: float = 0.1):
        self.key = key
        self.mu = mu
        self.W = _cache.get(key, np.zeros((P, B + 1), np.complex128)).copy()
        self.X = np.zeros((P, B + 1), np.complex128)        # spectra of the last P reference blocks
        self.prev_ref = np.zeros(B)
        self.pow = np.full(B + 1, 1e-4)                       # smoothed reference power per bin
        self.ref = np.zeros(16000 * 4, np.float64)            # ring buffer of what was played (16 kHz)
        self.wpos = 0                                         # samples written into the ring
        self.rpos: int | None = None                          # next reference sample to use
        self.margin = margin_ms / 1000                        # read a little earlier than "heard at the same time"
        self.last_push: tuple[int, float] | None = None       # (samples written so far, wall time the last one is heard)
        self.din = np.zeros(0)
        self.dout = np.zeros(0)
        self.lock = threading.Lock()
        self.erle = 0.0                                       # how much echo it removes (dB, for the log)
        self.started = False

    # what the speaker just played (16 kHz float) and the wall-clock time its first sample reaches your ears
    def push_ref(self, x: np.ndarray, heard_at: float) -> None:
        with self.lock:
            n = x.size
            i = self.wpos % self.ref.size
            first = min(n, self.ref.size - i)
            self.ref[i:i + first] = x[:first]
            if first < n:
                self.ref[:n - first] = x[first:]
            self.wpos += n
            self.last_push = (self.wpos, heard_at + n / 16000)

    def _take_ref(self, n: int, captured_at: float) -> np.ndarray:
        """The played samples heard during the mic block that started at captured_at (a bit earlier, as margin)."""
        with self.lock:
            if self.last_push is None:
                return np.zeros(n)
            w_end, t_end = self.last_push
            target = int(round(w_end - (t_end - (captured_at - self.margin)) * 16000))
            # (re)sync at the start or after drifting (clock drift, a stalled speaker); otherwise read on smoothly
            if self.rpos is None or abs(self.rpos - target) > 480:
                self.rpos = target
            i = self.rpos % self.ref.size
            idx = (np.arange(n) + i) % self.ref.size
            ok = 0 <= self.rpos and self.rpos + n <= self.wpos and self.wpos - self.rpos < self.ref.size
            out = self.ref[idx].copy() if ok else np.zeros(n)
            self.rpos += n
            return out

    def process(self, d: np.ndarray, captured_at: float) -> np.ndarray:
        """Microphone audio (16 kHz float) whose first sample was captured at captured_at (wall clock) in,
        the same audio with the echo removed out (same length overall, delayed by < 16 ms)."""
        start = captured_at - self.din.size / 16000            # when the oldest waiting sample was captured
        self.din = np.concatenate([self.din, d.astype(np.float64)])
        out, done = [], 0
        while self.din.size >= B:
            mic, self.din = self.din[:B], self.din[B:]
            ref = self._take_ref(B, start + done / 16000)
            done += B
            self.X = np.roll(self.X, 1, axis=0)
            self.X[0] = np.fft.rfft(np.concatenate([self.prev_ref, ref]))
            self.prev_ref = ref
            y = np.fft.irfft((self.W * self.X).sum(axis=0), N)[B:]       # predicted echo
            e = mic - y
            ref_e, mic_e, y_e = float(np.dot(ref, ref)), float(np.dot(mic, mic)), float(np.dot(y, y))
            if ref_e > 1e-6 * B:                                          # only learn while something is playing
                xp = np.abs(self.X[0]) ** 2                                  # per-bin power of the newest block
                # start from the real level (not ~0: that made the first steps huge and the filter blow up)
                self.pow = xp.copy() if not self.started else 0.9 * self.pow + 0.1 * xp
                self.started = True
                # you talking at the same time (much more in the mic than the predicted echo): learn slowly
                # (only once the filter works: before that a small prediction would look like "you talking"
                #  every time, and it would never learn)
                talk = self.erle > 6.0 and mic_e > 1.5 * y_e
                mu = self.mu * (0.0 if talk else 1.0)
                E = np.fft.rfft(np.concatenate([np.zeros(B), e]))
                G = mu * E / (self.pow + 1e-3 * float(self.pow.mean()) + 1e-9)
                self.W += np.conj(self.X) * G
                w = np.fft.irfft(self.W, N, axis=1)                       # keep it a proper (linear) filter
                w[:, B:] = 0
                self.W = np.fft.rfft(w, axis=1)
                if not talk and mic_e > 1e-8:
                    self.erle = 0.95 * self.erle + 0.05 * 10 * np.log10(mic_e / (float(np.dot(e, e)) + 1e-12))
            out.append(e)
        if self.key:
            _cache[self.key] = self.W
        return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)
