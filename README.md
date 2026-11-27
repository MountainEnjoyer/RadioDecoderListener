# RadioDecoderListener

A live FM radio receiver in Python. It drives an RTL-SDR dongle, shows the radio spectrum in a window, and plays the station you tune to through your speakers, continuously and in real time. Buttons tune by ±0.1 MHz and ±1 MHz.

Everything between the antenna and the speakers is done in Python with NumPy and SciPy: frequency shift, channel filter, decimation, FM demodulation, de-emphasis and audio filtering, on a stream of 2.4 million samples per second.

It is the real-time stage of a multi-mode software-defined radio (SDR) project. The earlier repositories build each piece offline; this one runs them live:

1. [FreqFinder](https://github.com/MountainEnjoyer/FreqFinder): find a frequency with the FFT.
2. [FrequencyShiftFilter](https://github.com/MountainEnjoyer/FrequencyShiftFilter): shift a signal to 0 Hz and filter it.
3. [FrequencyShiftFilterDecimation](https://github.com/MountainEnjoyer/FrequencyShiftFilterDecimation): lower the sample rate without aliasing.
4. [SdrReccord](https://github.com/MountainEnjoyer/SdrReccord): record a station and decode it to a WAV file.
5. **RadioDecoderListener (this repository):** the same decoder, live.

## Repository contents

```
RadioDecoderListener/
├── exec.py      # the live receiver: spectrum window, tuning buttons, audio
├── exec.sh      # launcher: activates the virtual environment and runs exec.py
└── README.md
```

## Requirements

- Linux (developed and tested on Arch Linux with PipeWire)
- An RTL-SDR dongle (RTL2832U with an R820T/R820T2 tuner) and its antenna
- Python 3.8 or later, with NumPy, SciPy, Matplotlib, pyrtlsdr and sounddevice in a virtual environment
- The `rtl-sdr` driver, PortAudio for sound, and Tk for the window

## Installation (Arch Linux)

### 1. System packages

```bash
sudo pacman -S --needed python tk git rtl-sdr portaudio
```

- `rtl-sdr` is the driver (`librtlsdr`) that pyrtlsdr talks to. It also provides `rtl_test`, to check the dongle.
- `portaudio` is the sound library sounddevice uses.
- `tk` lets Matplotlib open its window.

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

Use `pip`, not `pipx`: these are libraries the script imports, not command-line programs. `pyrtlsdr[lib]` also installs a bundled copy of the driver; see Troubleshooting if importing `rtlsdr` fails with an `undefined symbol` error.

### 4. Check the dongle and the sound output

```bash
rtl_test
```

should print `Found Rafael Micro R820T tuner` (or R820T2); stop it with Ctrl+C. Then play a test beep through the output the receiver will use:

```bash
.venv/bin/python -c "import numpy as np, sounddevice as sd; t=np.arange(48000)/48000; sd.play(0.3*np.sin(2*np.pi*440*t), 48000, device='pipewire'); sd.wait()"
```

If you hear nothing, try `'pulse'` or `'default'` instead of `'pipewire'`, and put the one that works in `OUTPUT_DEVICE` (see Configuration). `.venv/bin/python -m sounddevice` lists every output.

## Usage

From the repository folder:

```bash
./exec.sh
```

The window opens on **101.1 MHz** and the station starts playing within a fraction of a second.

| Control | Action |
| --- | --- |
| **−1 MHz / +1 MHz** | Jump 1 MHz down or up |
| **−0.1 MHz / +0.1 MHz** | Step to the neighbouring channel (FM stations sit on a 0.1 MHz grid) |
| Red dashed line | The frequency you are hearing |
| Title | The same frequency, in MHz |
| Closing the window | Stops the receiver, the sound and the dongle |

In the plot, a station is a hump about 200 kHz wide. Tune until the red line sits in the middle of one. Between stations you hear hiss.

### The status line

Once a second, the terminal shows how far the signal gets through the program:

```
blocks read   47 | decoded   47 | audio queue  1 | played    3.9 s, silence    0.2 s | audio peak 0.41
```

| Field | Meaning |
| --- | --- |
| `blocks read` | Blocks received from the dongle (one every 85 ms) |
| `decoded` | Blocks turned into audio. It should follow `blocks read`. |
| `audio queue` | Decoded blocks waiting for the sound card. Small and steady is right. |
| `played` / `silence` | Time of audio sent to the sound card, and time it had to fill with silence because nothing was ready |
| `audio peak` | Loudest value in the last decoded block. Near 0 means nothing is being received. |

## How it works

### Three threads

A live receiver has three jobs that run at their own pace, so each gets its own thread, connected by queues:

| Thread | Job |
| --- | --- |
| **Reader** (`read_samples_async`) | The dongle streams without interruption. Each block of 204,800 samples goes into `raw_q`. |
| **Decoder** (`decode_loop`) | Takes a block, runs it through the FM decoder, puts the audio into `audio_q`. |
| **Sound card** (sounddevice's `OutputStream`) | Calls `play()` whenever it needs more audio and takes it from `audio_q`. If nothing is ready, it plays silence instead of garbage. |

The **window** runs in the main thread: it plots the newest block's spectrum ten times a second and handles the buttons. Because reading, decoding and playing no longer wait for the window, the sound never stops while the plot redraws.

**Why not `read_samples` and `sd.play()` in a loop?** With `read_samples`, samples arriving while Python decodes or draws are lost. `sd.play()` replaces whatever is playing, so each block cuts off the previous one. The result is short bursts of sound separated by gaps.

### The decoder, block by block

`FMDemod.process()` applies the same chain as [SdrReccord](https://github.com/MountainEnjoyer/SdrReccord)'s `decode.py` to each 85 ms block:

| Stage | Rate after |
| --- | --- |
| Shift the station from −250 kHz to 0 Hz | 2.4 MS/s |
| Channel filter ±100 kHz (201-tap FIR), keep 1 sample in 10 | 240 kS/s |
| FM demodulation: `angle(z[n]·conj(z[n−1]))` | 240 kS/s |
| De-emphasis 50 µs (Europe), audio filter 15 kHz (101 taps), keep 1 in 5 | 48 kS/s |

**Memory between blocks.** Every stage that looks at past samples keeps its memory from one block to the next:

- each filter returns its internal state (`zi`), which is passed into the next block;
- the shifting tone continues from the phase where it stopped;
- the demodulator receives the previous block's last sample.

Without this, every block would start from scratch and put a click at every join, about 12 times a second. With it, decoding block by block gives exactly the same output as decoding the whole signal at once.

**The block size, 204,800 samples (85 ms),** is chosen for two reasons. It is 409,600 bytes, a multiple of the 16,384-byte transfers the driver uses when streaming. And it divides evenly by 10 and by 50, so both decimations keep exactly the same rhythm from one block to the next.

### Tuning

The dongle is always tuned **250 kHz above** the station you hear, as in SdrReccord. Every dongle produces a false peak at its exact center frequency (the DC spike); tuning beside the station keeps it out of the audio. The decoder shifts the station back to 0 Hz.

When a button is pressed, `retune()` sets the dongle's new frequency and moves the curve, the visible range, the red marker and the title together. It does not reset the decoder: the audio carries on, and the new station is heard after a few blocks.

### Volume and overflow

The audio is scaled by a fixed `VOLUME` rather than normalised block by block, which would make the level jump every 85 ms. Both queues hold about 1.7 seconds; if one fills up, the oldest block is dropped, so a slow moment never builds up a growing delay.

## Configuration

All settings are at the top of `exec.py`.

| Setting | Default | Description |
| --- | --- | --- |
| `start_mhz` | `101.1` | Station tuned at start, in MHz. |
| `OUTPUT_DEVICE` | `"pipewire"` | Sound output, by name or part of a name. Going through PipeWire follows your desktop's sound settings. |
| `VOLUME` | `0.5` | Audio level. Raise it for a weak station; lower it if the sound distorts. |
| `sdr.gain` | `12` | Receiver gain in dB. Raise it if stations are buried in noise; lower it if strong signals create false peaks. |
| `FS` | `2.4e6` | Dongle sample rate. |
| `OFFSET` | `250e3` | How far the dongle sits above the station, in Hz. |
| `BLOCK` | `204800` | Samples per block. Keep it a multiple of 8,192 and of 50. |
| `DEC1`, `DEC2` | `10`, `5` | Decimation factors: 2.4 MS/s → 240 kS/s → 48 kS/s. |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| No sound, status line normal (`played` rising) | Audio goes to the wrong output, for example `HDA Intel PCH: HDMI 0` | Check the `Sound output:` line printed at start. Set `OUTPUT_DEVICE` to `"pipewire"`, `"pulse"` or `"default"`, whichever plays the test beep. |
| `blocks read` stays at 0 | The dongle is not streaming | Look for an error above the status lines; check the dongle with `rtl_test`. |
| `decoded` stays at 0 | The decoder fails | Its error is printed in full in the terminal. |
| `audio peak` near 0.00 | Nothing is being received | Tune onto a station: the red line must sit in a hump. |
| Hiss only | Between stations, or a very weak station | Step with ±0.1 MHz; extend the antenna rods (about 75 cm each for FM) and move the antenna near a window. |
| Regular short dropouts, `silence` keeps rising | Decoding cannot keep up | Close other heavy programs. Each block takes well under its 85 ms on a desktop. |
| Rare short gap after several minutes | The dongle's and the sound card's clocks differ slightly | Expected: the queues drop an old block rather than let the delay grow. |
| `AttributeError: ... undefined symbol` (`rtlsdr_set_dithering`) | Recent pyrtlsdr expects a driver feature Arch's `rtl-sdr` lacks | Install `"pyrtlsdr[lib]"`; if the error remains, `.venv/bin/pip install "pyrtlsdr==0.2.93" setuptools`. |
| `OSError: PortAudio library not found` | PortAudio is not installed | `sudo pacman -S portaudio` |
| `FigureCanvasAgg is non-interactive`, no window | Matplotlib found no window system | `sudo pacman -S tk`; check that `MPLBACKEND` is not set to `Agg`. |
| `usb_claim_interface error -6`, dongle busy | Another program, or a previous run, still holds it | Close it; unplug and replug the dongle if needed. |

## Roadmap

- **Done:** DSP fundamentals, offline FM decoding, live FM listening.
- **Next:** AM for the aviation band (118–137 MHz), narrowband FM and SSB; then a modular architecture where each mode is a swappable demodulator, a spectrum and waterfall interface with click-to-tune, and digital modes such as RDS (station names), ADS-B (aircraft) and APRS.

## Further reading

- [PySDR: A Guide to SDR and DSP using Python](https://pysdr.org), chapters on FM and real-time processing
- [pyrtlsdr](https://github.com/pyrtlsdr/pyrtlsdr), including `read_samples_async`
- [sounddevice](https://python-sounddevice.readthedocs.io/): `OutputStream` and callbacks
- [SciPy `lfilter`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.lfilter.html), and its `zi` state argument
