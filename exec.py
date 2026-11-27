import numpy as np
import matplotlib.pyplot as plt
from matplotlib import mlab
from rtlsdr import RtlSdr
from matplotlib.widgets import Button
import sounddevice as sd
from scipy import signal

NFFT = 1024
interval = 0.01  # seconds between updates
num_taps = 201
dec1 = 10
dec2 = 5
fs = 2.4e6
fs1 = fs / dec1
fs2 = fs1 / dec2

sdr = RtlSdr()

# configure device
sdr.sample_rate = fs
sdr.center_freq = 123e6
sdr.gain = 12

Fs = sdr.sample_rate / 1e6   # MHz
Fc = sdr.center_freq / 1e6   # MHz


def avg_spectrum(x, fs, nfft=1024):
    rows = len(x) // nfft
    blocks = x[:rows * nfft].reshape(rows, nfft) * np.hanning(nfft)
    power = np.mean(np.abs(np.fft.fft(blocks, axis=1)) ** 2, axis=0)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, d=1 / fs))
    return freqs, np.fft.fftshift(10 * np.log10(power + 1e-12))

def retune(new_fc):
    global Fc
    Fc = new_fc
    sdr.center_freq = Fc * 1e6                  # 1. the dongle (in Hz)
    line.set_xdata(Fc + offsets)                # 2. the curve's frequencies
    ax.set_xlim(Fc - Fs / 2, Fc + Fs / 2)       # 3. the visible range
    ax.set_title(f"{Fc:.1f} MHz")
    sdr.read_samples(2048)                      # drop samples from before the change

def step(mhz):
    retune(min(max(Fc + mhz, 25.0), 1750.0))    # stay within the dongle's range

try:
    plt.ion()
    fig, ax = plt.subplots()
    fig.subplots_adjust(bottom=0.25)               # leave room under the plot

    # first plot: creates the line we will update afterwards
    samples = sdr.read_samples(256 * 1024)
    _, _, line = ax.psd(samples, NFFT=NFFT, Fs=Fs, Fc=Fc, return_line=True)
    line = line[0]
    ax.set_xlabel('Frequency (MHz)')
    ax.set_ylabel('Relative power (dB)')

    # frequencies relative to the centre: −1.2 … +1.2 MHz, sorted
    _, offsets = mlab.psd(samples, NFFT=NFFT, Fs=Fs)

    ax_less = fig.add_axes([0.36, 0.08, 0.12, 0.06])
    less = Button(ax_less, "−1 MHz")
    less.on_clicked(lambda event: step(-1))

    ax_more = fig.add_axes([0.52, 0.08, 0.12, 0.06])
    more = Button(ax_more, "+1 MHz")
    more.on_clicked(lambda event: step(+1))

    retune(Fc)
    plt.show()

    # loop until the window is closed
    while plt.fignum_exists(fig.number):
        samples = sdr.read_samples(256 * 1024)
        
        t = np.arange(len(samples)) / fs
        y = samples * np.exp(-2j * np.pi * Fc * t)
        taps = signal.firwin(num_taps, 100e3, fs=fs)
        z = signal.lfilter(taps, 1.0, y)[num_taps:][::dec1]

        audio = np.angle(z[1:] * np.conj(z[:-1]))

        a = np.exp(-1 / (50e-6 * fs1))
        audio = signal.lfilter([1 - a], [1, -a], audio)

        taps2 = signal.firwin(101, 15e3, fs=fs1)
        audio = signal.lfilter(taps2, 1.0, audio)[101:][::dec2]

        audio = audio / np.max(np.abs(audio)) * 0.9
        sd.play(audio)

        # compute the PSD without drawing a new plot
        pxx, _ = mlab.psd(samples, NFFT=NFFT, Fs=Fs)
        line.set_ydata(10 * np.log10(pxx))

        # rescale the y axis if the power level changes
        ax.relim()
        ax.autoscale_view(scalex=False)

        fig.canvas.draw_idle()
        plt.pause(interval)

finally:
    sdr.close()   # always release the dongle, even on Ctrl+C or error
