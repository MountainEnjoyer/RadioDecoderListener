import queue
import threading

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import mlab
from matplotlib.widgets import Button
from rtlsdr import RtlSdr
import sounddevice as sd
from scipy import signal

# ---------------- settings ----------------
FS = 2.4e6                  # dongle sample rate
OFFSET = 250e3              # tune 250 kHz above the station: keeps it off the DC spike
BLOCK = 243200              # samples per block (101 ms): a multiple of 256 for USB, of 50 for both decimations
DEC1, DEC2 = 10, 5          # 2.4 MS/s -> 240 kS/s -> 48 kS/s
FS1 = FS / DEC1
FS2 = FS1 / DEC2
VOLUME = 0.5                # fixed scale: the demodulator's output stays within about ±2
NFFT = 1024
start_mhz = 101.1           # the station to listen to

sd.default.device = "pipewire"      # or whichever one beeped

class FMDemod:
    """Shift, filter, ÷10, demodulate, de-emphasis, audio filter, ÷5: one block at a time.

    Every stage that looks at past samples keeps its memory between blocks, so the blocks join
    without a click. That memory is what makes block processing sound like one continuous signal.
    """

    def __init__(self):
        self.taps1 = signal.firwin(201, 100e3, fs=FS)
        self.taps2 = signal.firwin(101, 15e3, fs=FS1)
        a = np.exp(-1 / (50e-6 * FS1))
        self.de_b, self.de_a = [1 - a], [1, -a]
        self.reset()

    def reset(self):
        self.phase = 0.0                                          # where the shifting tone stopped
        self.zi1 = np.zeros(len(self.taps1) - 1, dtype=complex)   # channel filter memory
        self.zi_de = np.zeros(1)                                  # de-emphasis memory
        self.zi2 = np.zeros(len(self.taps2) - 1)                  # audio filter memory
        self.last = 1 + 0j                                        # last sample, for the demodulator

    def process(self, x):
        # 1. shift the station from −OFFSET to 0 Hz, continuing the tone's phase from the last block
        step = 2 * np.pi * OFFSET / FS
        y = x * np.exp(1j * (self.phase + step * np.arange(len(x))))
        self.phase = (self.phase + step * len(x)) % (2 * np.pi)

        # 2. channel filter ±100 kHz, then keep 1 in 10
        z, self.zi1 = signal.lfilter(self.taps1, 1.0, y, zi=self.zi1)
        z = z[::DEC1]

        # 3. FM demodulation, with the previous block's last sample in front
        z = np.concatenate(([self.last], z))
        self.last = z[-1]
        audio = np.angle(z[1:] * np.conj(z[:-1]))

        # 4. de-emphasis, 15 kHz audio filter, keep 1 in 5
        audio, self.zi_de = signal.lfilter(self.de_b, self.de_a, audio, zi=self.zi_de)
        audio, self.zi2 = signal.lfilter(self.taps2, 1.0, audio, zi=self.zi2)
        return np.clip(audio[::DEC2] * VOLUME, -1, 1).astype(np.float32)


raw_q = queue.Queue(maxsize=20)      # blocks from the dongle, waiting to be decoded (~2 s)
audio_q = queue.Queue(maxsize=20)    # decoded audio, waiting for the sound card
latest = {"samples": None}           # newest block, for the spectrum plot
running = threading.Event()
running.set()


def put_dropping_oldest(q, item):
    """Never block: if the queue is full, throw the oldest item away."""
    while True:
        try:
            q.put_nowait(item)
            return
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass


# --- thread 1: the dongle streams continuously, with no gaps between blocks ---
def on_samples(samples, context):
    latest["samples"] = samples
    put_dropping_oldest(raw_q, samples)


# --- thread 2: decoding ---
def decode_loop(demod):
    while running.is_set():
        try:
            block = raw_q.get(timeout=0.5)
        except queue.Empty:
            continue
        put_dropping_oldest(audio_q, demod.process(block))


# --- thread 3 (inside sounddevice): the sound card asks for audio whenever it needs some ---
pending = np.zeros(0, dtype=np.float32)


def play(outdata, frames, time, status):
    global pending
    while len(pending) < frames:
        try:
            pending = np.concatenate((pending, audio_q.get_nowait()))
        except queue.Empty:
            break
    n = min(frames, len(pending))
    outdata[:n, 0] = pending[:n]
    outdata[n:, 0] = 0                       # nothing ready yet: silence rather than garbage
    pending = pending[n:]


# --- main thread: the window ---
sdr = RtlSdr()
sdr.sample_rate = FS
sdr.gain = 12
listen = start_mhz                           # MHz: the station you hear
sdr.center_freq = listen * 1e6 + OFFSET      # the dongle sits OFFSET above it

demod = FMDemod()
reader = threading.Thread(target=lambda: sdr.read_samples_async(on_samples, num_samples=BLOCK), daemon=True)
decoder = threading.Thread(target=decode_loop, args=(demod,), daemon=True)
stream = sd.OutputStream(samplerate=FS2, channels=1, dtype="float32", callback=play)

try:
    reader.start()
    decoder.start()
    stream.start()

    plt.ion()
    fig, ax = plt.subplots()
    fig.subplots_adjust(bottom=0.25)
    Fs = FS / 1e6                                            # MHz
    offsets = np.fft.fftshift(np.fft.fftfreq(NFFT, d=1 / Fs))   # −1.2 … +1.2 MHz, as mlab.psd sorts them
    line, = ax.plot(offsets, np.zeros(NFFT))
    marker = ax.axvline(listen, color="red", linestyle="--", alpha=0.6)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Relative power (dB)")

    def retune(new_mhz):
        global listen
        listen = min(max(new_mhz, 24.0), 1700.0)
        center = listen + OFFSET / 1e6
        sdr.center_freq = center * 1e6
        line.set_xdata(center + offsets)
        ax.set_xlim(center - Fs / 2, center + Fs / 2)
        marker.set_xdata([listen, listen])
        ax.set_title(f"Listening to {listen:.1f} MHz")

    buttons = []
    for i, (label, mhz) in enumerate([("−1", -1), ("−0.1", -0.1), ("+0.1", +0.1), ("+1", +1)]):
        b = Button(fig.add_axes([0.20 + i * 0.16, 0.08, 0.13, 0.06]), f"{label} MHz")
        b.on_clicked(lambda event, d=mhz: retune(round(listen + d, 1)))
        buttons.append(b)                        # keep a reference, or the button stops working

    retune(listen)
    plt.show()

    while plt.fignum_exists(fig.number):
        samples = latest["samples"]
        if samples is not None:
            pxx, _ = mlab.psd(samples, NFFT=NFFT, Fs=Fs)
            line.set_ydata(10 * np.log10(pxx))
            ax.relim()
            ax.autoscale_view(scalex=False)
            fig.canvas.draw_idle()
        plt.pause(0.1)

finally:
    running.clear()
    try:
        sdr.cancel_read_async()
    except Exception:
        pass
    stream.stop()
    stream.close()
    sdr.close()                                  # always release the dongle
