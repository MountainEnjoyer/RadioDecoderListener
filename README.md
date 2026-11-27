# RadioDecoderListener

A live spectrum viewer for an RTL-SDR dongle, written in Python. It shows the radio spectrum around a chosen frequency, updates it several times per second, and has two buttons to tune up and down by 1 MHz.

It is the starting point of a multi-mode software-defined radio (SDR) project: the tool used to look at the radio spectrum, find stations and check reception before recording and decoding them.

## What it shows

The window plots **power against frequency** over a 2.4 MHz wide slice of the radio spectrum, centred on the tuned frequency:

- **Stations** appear as peaks or humps rising above the noise floor. A broadcast FM station is a hump about 200 kHz wide; air-band voice appears as short bursts that come and go.
- **The noise floor** is the flat baseline underneath: the receiver's own noise plus whatever the antenna picks up.
- **The DC spike** is a narrow peak exactly at the centre frequency. It is produced by the dongle itself, not by a transmitter.
- **The edges** roll off beyond about ±1.1 MHz: that is the dongle's own filter.

The title shows the tuned frequency, and the x axis is in MHz.

## Repository contents

```
RadioDecoderListener/
├── exec.py      # the live spectrum viewer
├── exec.sh      # launcher: activates the virtual environment and runs exec.py
└── README.md
```

## Requirements

- Linux (developed and tested on Arch Linux)
- An RTL-SDR dongle (RTL2832U with an R820T/R820T2 tuner) and its antenna
- Python 3.8 or later, with NumPy, Matplotlib and pyrtlsdr in a virtual environment
- The `rtl-sdr` driver, and Tk for the plot window

## Installation (Arch Linux)

### 1. System packages

```bash
sudo pacman -S --needed python tk git rtl-sdr
```

- `rtl-sdr` is the driver (`librtlsdr`) that pyrtlsdr talks to. It also provides `rtl_test`, to check the dongle.
- `tk` lets Matplotlib open its window. Without it, the script prints `FigureCanvasAgg is non-interactive` and shows nothing.

### 2. Clone the repository

```bash
git clone https://github.com/MountainEnjoyer/RadioDecoderListener.git
cd RadioDecoderListener
```

### 3. Virtual environment and Python packages

Arch marks its system Python as externally managed ([PEP 668](https://peps.python.org/pep-0668/)), so the packages go into a local `.venv`:

```bash
python -m venv .venv
.venv/bin/pip install numpy scipy matplotlib sounddevice "pyrtlsdr[lib]"
```

Use `pip`, not `pipx`: these are libraries the script imports, not command-line programs. SciPy and sounddevice are not used by the viewer yet; they are for the decoding stages that follow.

`pyrtlsdr[lib]` also installs a bundled copy of the driver. Recent pyrtlsdr versions call a driver function (`rtlsdr_set_dithering`) that Arch's `rtl-sdr` package does not provide; see Troubleshooting if the import still fails.

### 4. Check the dongle

With the dongle plugged in:

```bash
rtl_test
```

It should print `Found Rafael Micro R820T tuner` (or R820T2) and start counting samples. Stop it with Ctrl+C.

## Usage

From the repository folder:

```bash
./exec.sh
```

A window opens with the live spectrum, starting at **123 MHz** (the aviation band).

| Control | Action |
| --- | --- |
| **−1 MHz** | Tune 1 MHz down |
| **+1 MHz** | Tune 1 MHz up |
| Matplotlib toolbar | Zoom into part of the spectrum, pan, save an image |
| Closing the window | Stops the viewer and releases the dongle |

Tuning is limited to 25–1750 MHz, roughly the range of an R820T-based dongle.

### Where to look

| Band | Frequency | What you see |
| --- | --- | --- |
| Broadcast FM | 88–108 MHz | Wide, steady humps about 200 kHz wide: radio stations |
| Aviation (AM) | 118–137 MHz | Short bursts when pilots and air traffic control talk |
| Amateur 2 m / APRS | 144–146 MHz | Short bursts; APRS data packets on 144.800 MHz in Europe |
| PMR446 walkie-talkies | 446.0–446.2 MHz | Brief transmissions on narrow channels |
| ADS-B (aircraft positions) | 1090 MHz | Very short pulses from passing aircraft |

## How it works

### Configuration

```python
sdr.sample_rate = 2.4e6
sdr.center_freq = 123e6
sdr.gain = 12
```

The dongle delivers 2.4 million complex I/Q samples per second, which gives a 2.4 MHz wide view centred on `center_freq`. 2.4 MS/s is the fastest rate most computers sustain over USB without losing samples. Frequencies are handled in MHz in the script (`Fs`, `Fc`) and converted to Hz only when talking to the dongle.

### The spectrum

Each update reads 262,144 samples (256 × 1024, about 0.11 s of signal) and computes their **power spectral density** with `mlab.psd`. It cuts the samples into 1024-sample pieces, takes the FFT of each, and averages the 256 results. A single FFT of noise is ragged; averaging gives a smooth, readable curve. Each of the 1024 frequency bins is 2.4 MHz / 1024 ≈ 2.3 kHz wide.

### Updating instead of redrawing

The first spectrum is drawn once with `ax.psd(..., return_line=True)`, which returns the curve as an object. Every update after that only replaces the curve's heights with `line.set_ydata(...)`, rescales the y axis, and asks for a redraw. This is much faster than drawing a new plot each time and avoids flicker.

`plt.pause(interval)` then lets the window process the redraw and any clicks, without freezing it as `time.sleep` would. The loop runs until the window is closed (`plt.fignum_exists`).

### Tuning

`mlab.psd` returns the frequencies of its bins **relative to the centre**, from −1.2 to +1.2 MHz. They are stored once as `offsets`, so the absolute frequencies are always `Fc + offsets`. When a button is pressed, `retune()` keeps everything consistent:

1. sets the dongle's centre frequency;
2. moves the curve to the new frequencies (`set_xdata`);
3. moves the visible range (`set_xlim`) and updates the title;
4. reads and discards 2048 samples, since the tuner needs a moment to settle and the first samples after a change still belong to the old frequency.

The buttons call `retune()` from inside `plt.pause()`, between two reads, so tuning never collides with reading.

### Releasing the dongle

Everything runs inside `try` / `finally: sdr.close()`, so the dongle is released even after an error or Ctrl+C, and the next run can open it.

## Configuration

All settings are at the top of `exec.py`.

| Setting | Default | Description |
| --- | --- | --- |
| `sdr.center_freq` | `123e6` | Starting frequency in Hz. `100e6` starts in the FM band. |
| `sdr.sample_rate` | `2.4e6` | Width of the view, in samples per second. Higher rates may lose samples over USB. |
| `sdr.gain` | `12` | Receiver gain in dB. Raise it if signals are buried in noise; lower it if strong signals create false peaks everywhere. |
| `NFFT` | `1024` | Samples per FFT. More gives finer frequency detail but a noisier curve per update. |
| `interval` | `0.01` | Pause between updates, in seconds. The real rate is limited by reading and processing each block, about 0.1 s. |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'rtlsdr'` | pyrtlsdr is not installed in this project's `.venv` | `.venv/bin/pip install "pyrtlsdr[lib]"`. The package is named `pyrtlsdr`, the module `rtlsdr`. |
| `AttributeError: ... librtlsdr.so: undefined symbol` (`rtlsdr_set_dithering`) | Recent pyrtlsdr expects a driver feature Arch's `rtl-sdr` lacks | Install `"pyrtlsdr[lib]"`; if the error remains, `.venv/bin/pip install "pyrtlsdr==0.2.93" setuptools`. |
| `usb_claim_interface error -6`, or the dongle is busy | Another program (or a previous run) still holds the dongle | Close it; if the kernel's DVB-T driver grabbed the dongle, unplug and replug it, or blacklist `dvb_usb_rtl28xxu`. |
| `FigureCanvasAgg is non-interactive`, no window opens | Matplotlib found no window system | `sudo pacman -S tk`; check that `MPLBACKEND` is not set to `Agg`. |
| Only noise, no stations | Frequency with nothing on it, or weak reception | Try the FM band (88–108 MHz); extend the antenna rods (about 75 cm each for FM), move the antenna near a window, raise the gain. |
| False peaks all over the spectrum | Gain too high: the receiver is overloaded | Lower `sdr.gain`. |
| Many very narrow spikes | Interference from the computer or USB cable | Move the dongle away with a short USB extension cable. |

## Related projects

This viewer is the first step of a series that goes from DSP fundamentals to a working FM receiver:

- [FreqFinder](https://github.com/MountainEnjoyer/FreqFinder): find a frequency with the FFT.
- [FrequencyShiftFilter](https://github.com/MountainEnjoyer/FrequencyShiftFilter): shift a signal to 0 Hz and filter it.
- [FrequencyShiftFilterDecimation](https://github.com/MountainEnjoyer/FrequencyShiftFilterDecimation): lower the sample rate without aliasing.
- [SdrReccord](https://github.com/MountainEnjoyer/SdrReccord): record an FM station and decode it to a WAV file.

## Further reading

- [PySDR: A Guide to SDR and DSP using Python](https://pysdr.org), chapters on the frequency domain and the RTL-SDR
- [pyrtlsdr](https://github.com/pyrtlsdr/pyrtlsdr)
- [Matplotlib widgets](https://matplotlib.org/stable/api/widgets_api.html)
