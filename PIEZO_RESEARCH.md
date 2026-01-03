# Piezo Buzzer Frequency Response Research

> Research findings on piezoelectric buzzer frequency characteristics for the Lost Model Buzzer project.

## Key Findings

### 1. Resonant Nature of Piezo Buzzers

Piezo buzzers **do not have a flat frequency response**. They operate on resonance principle:

- **One main resonance** in the 2-5 kHz range (typically 3-4 kHz)
- **Narrow bandwidth** — ±200 Hz around resonance (high Q factor)
- **Sharp rolloff** outside the resonant frequency

```
      SPL (dB)
         │      ╱╲
         │     ╱  ╲
         │    ╱    ╲      ← bandwidth ~200-500 Hz
         │   ╱      ╲
         │──╱────────╲────────
         │
         └──────────────────── Freq (Hz)
              2.5k  3k  3.5k
                    ↑
               resonance
```

### 2. Multiple Vibration Modes

Piezo disks have several vibration modes:
- **Radial mode**
- **Thickness mode**
- **Edge mode**
- **Thickness shear mode**

Each mode has its own resonant frequency. In practice, this manifests as multiple "peaks" on the frequency response curve.

### 3. Experimental Data from Our Piezo

Analysis with 10 Hz steps showed the piezo "locks" onto discrete resonances:

| Input Range | Detected Frequency | Mode |
|-------------|-------------------|------|
| 2400-2480 Hz | 2422 Hz | #1 |
| 2490-2560 Hz | 2508 Hz | #2 |
| 2570-2650 Hz | 2605 Hz | #3 |
| 2660-2750 Hz | 2702 Hz | #4 |
| 2760-2860 Hz | 2799-2810 Hz | #5 |
| 2870-2990 Hz | 2917 Hz | #6 |

**Distance between modes: ~86-97 Hz** (average ~90 Hz)

### 4. Impact on Calibration

Since the piezo has discrete resonances spaced ~100 Hz apart:
- **10 Hz step is pointless** — piezo only outputs its resonant frequencies anyway
- **100 Hz step is optimal** — falls between resonances
- **25 Hz step is excessive** — provides no additional precision

### 5. FFT Analysis Limitations

```
Sample rate: 44100 Hz
Block size: 4096 samples
FFT resolution: 44100/4096 ≈ 10.7 Hz
```

FFT cannot distinguish frequencies closer than ~10 Hz. This is another reason why fine steps don't help.

## Frequency Selection Guidelines

### Loudness vs Penetration

| Factor | Low (2400-2700 Hz) | High (2800-3200 Hz) |
|--------|-------------------|---------------------|
| Air loudness | Medium | Higher |
| Grass penetration | ✓ Better | ✗ Worse |
| Audible distance | ✓ Farther | ✗ Shorter |
| Reproduction accuracy | ✓ More precise | May distort |
| Harmonics | ✓ Richer | Fewer |

### Harmonics

A tone with multiple harmonics (2x, 3x, 4x of fundamental) is easier to localize by ear. Lower frequencies typically have richer harmonic content.

### Final Recommendation

For Lost Model Buzzer, optimal range: **2500-2700 Hz**
- Good loudness
- Better grass penetration
- Accurate piezo reproduction
- Sufficient harmonics for localization

## Sources

### Piezo Resonance
- [Piezo Resonance Experiment - CSpark Research](https://csparkresearch.in/expeyes17/sound/piezo-resonance.html)
  - Resonance ~3500 Hz, bell-shaped curve
  - Varies between samples
  - Adding mass lowers resonant frequency

### Frequency Response and SPL
- [Same Sky - Resonance in Audio Design](https://www.sameskydevices.com/blog/understanding-the-impact-of-resonance-and-resonant-frequency-in-audio-design)
  - Piezo: 1-5 kHz, narrow bandwidth
  - Higher SPL than magnetic buzzers at same current

### Multiple Modes
- [ResearchGate - Vibration modes in piezoelectric disks](https://www.researchgate.net/figure/Modes-of-vibration-in-piezoelectric-disks-D-t20-except-radial-and-bar-modes-a-radial_fig3_254401362)
  - Radial, thickness, edge, shear modes
  - D/t ratio affects mode distribution

### Q-Factor and Bandwidth
- [Parallax Forums - Piezo frequency response](https://forums.parallax.com/discussion/125763/frequency-response-of-a-piezo-speaker)
  - High Q = narrow bandwidth, sharp peak
  - Typical bandwidth ±200 Hz

### Datasheet Examples
- [TDK Piezoelectric Buzzer Selection Guide](https://product.tdk.com/en/products/selectionguide/piezo-buzzer.html)
  - Resonance 2.0-4.1 kHz depending on model
  - SPL 68-80 dB @ 10cm

- [Murata Piezoelectric Components](https://www.murata.com/~/media/webrenewal/support/library/catalog/products/sound/p15e.ashx)
  - Resonance 2.0-3.8 kHz
  - SPL increases 6 dB per voltage doubling

## Experiments

### Methodology
1. ATtiny13A generates square wave at specified frequency
2. MacBook microphone records sound
3. Python script performs FFT analysis
4. Peak frequency and dB are determined

### Data Files
- `buzzer_analysis_20260103_122142.csv` — sweep with 25 Hz step
- `buzzer_analysis_20260103_123034.csv` — sweep with 10 Hz step

### Tools
- `buzzer_analyzer.py` — real-time spectrum analyzer
- `analyze_spectrum.py` — Phyphox CSV export analysis

---

*Research conducted as part of the ATtiny13A Lost Model Buzzer project, January 2026*
