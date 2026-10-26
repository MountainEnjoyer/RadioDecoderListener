import numpy as np
import matplotlib.pyplot as plt
from matplotlib import mlab
from rtlsdr import RtlSdr

NFFT = 1024
interval = 0.5  # seconds between updates

sdr = RtlSdr()

# configure device
sdr.sample_rate = 2.4e6
sdr.center_freq = 2.4e9
sdr.gain = 4

Fs = sdr.sample_rate / 1e6   # MHz
Fc = sdr.center_freq / 1e6   # MHz

try:
    plt.ion()
    fig, ax = plt.subplots()

    # first plot: creates the line we will update afterwards
    samples = sdr.read_samples(256 * 1024)
    _, _, line = ax.psd(samples, NFFT=NFFT, Fs=Fs, Fc=Fc, return_line=True)
    line = line[0]
    ax.set_xlabel('Frequency (MHz)')
    ax.set_ylabel('Relative power (dB)')
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
