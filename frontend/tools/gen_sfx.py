"""Синтез звуків для гри «Дурак» (без чужих семплів). Запуск: python tools/gen_sfx.py public/sfx /tmp/sfx-wav"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
TMP = Path(sys.argv[2])
TMP.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)


def t_(dur):
    return np.arange(int(SR * dur)) / SR


def env(n, attack, decay_tau):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / decay_tau)


def band(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def place(buf, x, at):
    x = np.array(x, dtype=float)
    k = min(len(x), int(SR * 0.04))
    x[-k:] *= np.linspace(1, 0, k) ** 2          # без клацань на обрізаних хвостах
    i = int(at * SR)
    buf[i:i + len(x)] += x[: max(0, len(buf) - i)]


def reverb(x, size=0.35, mix=0.18):
    n = int(SR * size)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * size / 5))
    ir = lp(ir, 5000)
    ir /= np.sqrt(np.sum(ir ** 2))
    wet = signal.fftconvolve(x, ir)[: len(x) + n]
    wet = np.pad(wet, (0, len(x) + n - len(wet)))
    dry = np.concatenate([x, np.zeros(n)])
    return dry * (1 - mix) + wet * mix


def norm(x, peak=0.8):
    m = np.max(np.abs(x)) or 1
    return x / m * peak


# ---------- карти ----------
def paper(dur=0.07, lo=1800, hi=7000, attack=0.002, tau=0.018, vol=1.0):
    n = int(SR * dur)
    x = rng.standard_normal(n)
    # «зернистість» паперу: амплітудна модуляція дрібними імпульсами
    grain = 1 + 0.6 * lp(rng.standard_normal(n), 900)
    x = band(x * grain, lo, hi) * env(n, attack, tau)
    return x * vol


def felt_thump(vol=0.6, f=110, tau=0.03):
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (f * t - 25 * t ** 2)) * env(n, 0.002, tau)
    knock = lp(rng.standard_normal(n), 900) * env(n, 0.001, 0.01)
    return (body * 0.8 + knock * 0.5) * vol


def card_place(seed):
    """Карта лягає на сукно: короткий шелест у повітрі + мʼякий стук."""
    global rng
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.25))
    place(buf, paper(0.06, 2500, 9000, 0.012, 0.02, 0.35), 0.0)       # свист у повітрі
    place(buf, paper(0.05, 1200, 6000, 0.001, 0.012, 1.0), 0.045)     # ляп
    place(buf, felt_thump(0.55, 105 + seed * 7), 0.046)
    return norm(reverb(buf, 0.18, 0.08), 0.7)


def card_throw(seed):
    """Підкидання: швидший і легший кидок з ковзанням по столу."""
    global rng
    rng = np.random.default_rng(100 + seed)
    buf = np.zeros(int(SR * 0.3))
    place(buf, paper(0.05, 3000, 9500, 0.006, 0.015, 0.4), 0.0)
    place(buf, paper(0.04, 1500, 6500, 0.001, 0.01, 0.9), 0.035)
    place(buf, felt_thump(0.35, 130), 0.036)
    place(buf, paper(0.12, 900, 3500, 0.01, 0.04, 0.25), 0.05)        # проїхала по сукну
    return norm(reverb(buf, 0.18, 0.08), 0.6)


def card_defend(seed):
    """Відбій: впевнений «ляп» картою поверх карти."""
    global rng
    rng = np.random.default_rng(200 + seed)
    buf = np.zeros(int(SR * 0.28))
    place(buf, paper(0.035, 2500, 9000, 0.008, 0.012, 0.3), 0.0)
    place(buf, paper(0.06, 800, 5000, 0.0005, 0.016, 1.2), 0.03)
    place(buf, paper(0.03, 4000, 10000, 0.0005, 0.006, 0.6), 0.03)    # клац краю
    place(buf, felt_thump(0.75, 95), 0.031)
    return norm(reverb(buf, 0.2, 0.1), 0.8)


def card_draw(seed):
    """Взяти карту з колоди: ковзання карти по карті."""
    global rng
    rng = np.random.default_rng(300 + seed)
    n = int(SR * 0.16)
    x = rng.standard_normal(n)
    t = np.arange(n) / SR
    e = np.sin(np.pi * np.clip(t / 0.13, 0, 1)) ** 1.5
    sweep = np.concatenate([band(x[i:i + 512], 1500 + 3000 * i / n, 4000 + 4000 * i / n) for i in range(0, n, 512)])[:n]
    y = sweep * e * 0.7
    return norm(reverb(y, 0.15, 0.06), 0.45)


def deal():
    buf = np.zeros(int(SR * 0.7))
    for i in range(6):
        place(buf, card_place(i % 3) * 0.6, i * 0.085 + rng.uniform(0, 0.01))
    return norm(buf, 0.6)


def take():
    """Забрати купку карт: кілька шелестів, що зливаються, і глухий стук."""
    global rng
    rng = np.random.default_rng(400)
    buf = np.zeros(int(SR * 0.55))
    for i in range(5):
        place(buf, paper(0.09, 1200 + 300 * i, 5000, 0.01, 0.03, 0.5), i * 0.035)
    place(buf, felt_thump(0.7, 85, 0.05), 0.2)
    place(buf, paper(0.05, 800, 3000, 0.002, 0.015, 0.6), 0.2)
    return norm(reverb(buf, 0.2, 0.1), 0.7)


def beaten():
    """«Бито»: карти зсуваються у відбій."""
    global rng
    rng = np.random.default_rng(500)
    n = int(SR * 0.4)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    e = np.sin(np.pi * np.clip(t / 0.32, 0, 1)) ** 2
    y = band(x, 700, 4200) * e * 0.6
    buf = np.zeros(int(SR * 0.55))
    place(buf, y, 0)
    place(buf, felt_thump(0.3, 90), 0.3)
    return norm(reverb(buf, 0.2, 0.1), 0.5)


# ---------- музичні ----------
def marimba(f, dur=1.4, vol=1.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    y = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.35)
         + 0.35 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t / 0.06)
         + 0.12 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-t / 0.02))
    y *= np.clip(t / 0.003, 0, 1)
    return y * vol


def bell(f, dur=1.6, vol=1.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    parts = [(1, 1, 0.9), (2.0, 0.4, 0.5), (2.76, 0.25, 0.35), (5.4, 0.12, 0.15), (8.9, 0.06, 0.08)]
    y = sum(a * np.sin(2 * np.pi * f * m * t) * np.exp(-t / tau) for m, a, tau in parts)
    return y * np.clip(t / 0.002, 0, 1) * vol


def pad(freqs, dur, vol=0.3, attack=0.08, tau=0.6):
    n = int(SR * dur)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for f in freqs:
        for det in (-0.004, 0, 0.004):
            ph = rng.uniform(0, 2 * np.pi)
            y += np.sin(2 * np.pi * f * (1 + det) * t + ph) + 0.3 * np.sin(4 * np.pi * f * (1 + det) * t + ph)
    y = lp(y, 2500) * env(n, attack, tau)
    return y / len(freqs) * vol


def note(name):
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    base, octv = name[:-1], int(name[-1])
    semi = names[base[0]] + (1 if "#" in base else -1 if "b" in base else 0)
    return 440 * 2 ** ((semi + 12 * (octv - 4)) / 12)


def win():
    buf = np.zeros(int(SR * 2.2))
    seq = ["C5", "E5", "G5", "C6"]
    for i, n in enumerate(seq):
        place(buf, marimba(note(n), 1.0, 0.8), i * 0.09)
    place(buf, pad([note("C4"), note("E4"), note("G4"), note("C5")], 1.6, 0.5, 0.05, 0.5), 0.36)
    place(buf, bell(note("G6"), 1.2, 0.25), 0.36)
    place(buf, bell(note("C7"), 1.2, 0.18), 0.46)
    # іскорки
    for k in range(6):
        place(buf, bell(note("E7") * (1 + 0.06 * k), 0.4, 0.06), 0.5 + 0.07 * k)
    return norm(reverb(buf, 0.9, 0.25), 0.75)


def lose():
    buf = np.zeros(int(SR * 1.9))
    seq = [("E4", 0), ("Eb4", 0.22), ("D4", 0.44), ("Db4", 0.66)]
    for n, at in seq:
        f = note(n)
        tt = t_(0.7 if at < 0.6 else 1.1)
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.5 * tt) * (tt > 0.15)
        y = np.sin(2 * np.pi * np.cumsum(f * vib) / SR)
        y = y + 0.4 * np.sin(2 * 2 * np.pi * np.cumsum(f * vib) / SR) + 0.2 * np.sin(3 * 2 * np.pi * np.cumsum(f * vib) / SR)
        e = env(len(tt), 0.03, 0.25 if at < 0.6 else 0.45)
        place(buf, lp(y, 1400) * e * 0.5, at)
    place(buf, felt_thump(0.4, 70, 0.08), 0.66)
    return norm(reverb(buf, 0.7, 0.22), 0.6)


def tie():
    buf = np.zeros(int(SR * 1.4))
    place(buf, marimba(note("G4"), 1.0, 0.7), 0)
    place(buf, marimba(note("C5"), 1.0, 0.7), 0.14)
    place(buf, pad([note("G3"), note("C4"), note("D4")], 1.0, 0.3, 0.05, 0.4), 0.14)
    return norm(reverb(buf, 0.6, 0.2), 0.55)


def turn():
    buf = np.zeros(int(SR * 1.4))
    place(buf, marimba(note("E5"), 1.2, 0.6), 0)
    place(buf, marimba(note("A5"), 1.2, 0.5), 0.09)
    return norm(reverb(buf, 0.5, 0.18), 0.45)


def coin():
    buf = np.zeros(int(SR * 1.0))
    place(buf, bell(note("B6"), 0.6, 0.6), 0)
    place(buf, bell(note("E7"), 0.8, 0.6), 0.075)
    return norm(reverb(buf, 0.5, 0.15), 0.5)


def emoji():
    n = int(SR * 0.16)
    t = np.arange(n) / SR
    f = 380 + 900 * (1 - np.exp(-t / 0.03))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.035)
    return norm(reverb(y, 0.2, 0.1), 0.45)


def catch():
    global rng
    rng = np.random.default_rng(600)
    buf = np.zeros(int(SR * 1.3))
    n = int(SR * 0.25)
    t = np.arange(n) / SR
    x = band(rng.standard_normal(n), 600, 5000) * np.sin(np.pi * t / 0.25) ** 2 * 0.5
    place(buf, x, 0)
    place(buf, felt_thump(0.9, 80, 0.06), 0.22)
    place(buf, marimba(note("A4"), 0.95, 0.6), 0.23)
    place(buf, marimba(note("Eb5"), 0.95, 0.5), 0.23)
    return norm(reverb(buf, 0.4, 0.15), 0.7)


def achievement():
    buf = np.zeros(int(SR * 1.6))
    for i, n in enumerate(["G5", "B5", "D6", "G6"]):
        place(buf, bell(note(n), 1.0, 0.5), i * 0.06)
    place(buf, pad([note("G4"), note("B4"), note("D5")], 1.2, 0.35, 0.03, 0.4), 0.18)
    return norm(reverb(buf, 0.8, 0.25), 0.6)


def click():
    global rng
    rng = np.random.default_rng(700)
    return norm(paper(0.03, 3000, 9000, 0.0005, 0.005, 1.0), 0.3)


SOUNDS = {
    **{f"card{i}": (lambda i=i: card_place(i)) for i in range(3)},
    **{f"throw{i}": (lambda i=i: card_throw(i)) for i in range(3)},
    **{f"defend{i}": (lambda i=i: card_defend(i)) for i in range(3)},
    **{f"draw{i}": (lambda i=i: card_draw(i)) for i in range(3)},
    "deal": deal, "take": take, "beaten": beaten, "win": win, "lose": lose, "tie": tie, "turn": turn,
    "coin": coin, "emoji": emoji, "catch": catch, "achievement": achievement, "click": click,
}

for name, fn in SOUNDS.items():
    y = fn().astype(np.float32)
    # мʼякий кінець без клацання
    fade = min(len(y), int(SR * 0.06))
    y[-fade:] *= np.linspace(1, 0, fade)
    wav = TMP / f"{name}.wav"
    wavfile.write(wav, SR, (y * 32767).astype(np.int16))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-ar", "44100",
                    "-codec:a", "libmp3lame", "-b:a", "64k", str(OUT / f"{name}.mp3")], check=True)
    print(name, round(len(y) / SR, 2), "s")
