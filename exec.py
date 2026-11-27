import numpy as np
import matplotlib.pyplot as plt
from matplotlib import mlab
from rtlsdr import RtlSdr
from matplotlib.widgets import Button

NFFT = 1024
interval = 0.01  # seconds between updates

sdr = RtlSdr()

# configure device
sdr.sample_rate = 2.4e6
sdr.center_freq = 123e6
sdr.gain = 12

Fs = sdr.sample_rate / 1e6   # MHz
Fc = sdr.center_freq / 1e6   # MHz

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
