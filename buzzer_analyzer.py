#!/usr/bin/env python3
"""
Real-time Buzzer Frequency Analyzer for macOS
Listens to microphone and finds optimal piezo frequency during calibration sweep.

Usage:
    python buzzer_analyzer.py              # Real-time analysis
    python buzzer_analyzer.py --record     # Record sweep and analyze
    python buzzer_analyzer.py --help       # Show help
"""

import argparse
import sys
import time
import signal
from datetime import datetime
from collections import deque
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("Installing sounddevice...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "sounddevice", "-q"])
    import sounddevice as sd

# Audio settings
SAMPLE_RATE = 44100
BLOCK_SIZE = 4096  # ~93ms per block
CHANNELS = 1

# Buzzer frequency range (must match firmware!)
FREQ_MIN = 2400
FREQ_MAX = 3000
FREQ_STEP = 100

# Intro beeps (for auto-detection)
INTRO_FREQ = 2500      # DEFAULT_FREQ in firmware
INTRO_BEEP_MS = 400    # BEEP_LONG_MS
INTRO_PAUSE_MS = 300   # PAUSE_LONG_MS
INTRO_TOTAL_MS = 1600  # 2 beeps + pauses before sweep

# Tone detection
TONE_THRESHOLD_DB = -40  # dB threshold for tone detection
MIN_TONE_DURATION = 0.5  # Minimum tone duration in seconds

# Analysis settings
DB_REFERENCE = 1e-5  # Reference for dB calculation
SMOOTHING_ALPHA = 0.3  # EMA smoothing for display


class SpectrumAnalyzer:
    """Real-time audio spectrum analyzer"""

    def __init__(self, sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.freq_resolution = sample_rate / block_size

        # Pre-compute frequency bins
        self.freqs = np.fft.rfftfreq(block_size, 1/sample_rate)

        # Find indices for buzzer range
        self.buzzer_mask = (self.freqs >= FREQ_MIN) & (self.freqs <= FREQ_MAX)
        self.buzzer_freqs = self.freqs[self.buzzer_mask]

        # State
        self.current_spectrum = None
        self.smoothed_spectrum = None
        self.full_spectrum_db = None  # Full spectrum for harmonics
        self.peak_freq = 0
        self.peak_db = -100

        # Recording
        self.recording = False
        self.recorded_peaks = []  # List of (timestamp, freq, db, harmonics)
        self.start_time = None

        # Window function for better FFT
        self.window = np.hanning(block_size)

    def process_audio(self, data):
        """Process audio block and compute spectrum"""
        # Apply window and compute FFT
        windowed = data.flatten() * self.window
        fft = np.fft.rfft(windowed)
        magnitude = np.abs(fft) / self.block_size

        # Convert to dB
        magnitude_db = 20 * np.log10(magnitude + DB_REFERENCE)
        self.full_spectrum_db = magnitude_db

        # Extract buzzer range
        buzzer_spectrum = magnitude_db[self.buzzer_mask]

        # Smooth for display
        if self.smoothed_spectrum is None:
            self.smoothed_spectrum = buzzer_spectrum
        else:
            self.smoothed_spectrum = (SMOOTHING_ALPHA * buzzer_spectrum +
                                      (1 - SMOOTHING_ALPHA) * self.smoothed_spectrum)

        self.current_spectrum = buzzer_spectrum

        # Find peak in buzzer range
        peak_idx = np.argmax(buzzer_spectrum)
        self.peak_freq = self.buzzer_freqs[peak_idx]
        self.peak_db = buzzer_spectrum[peak_idx]

        # Detect harmonics
        harmonics = self.find_harmonics(self.peak_freq)

        # Record if enabled
        if self.recording and self.start_time:
            elapsed = time.time() - self.start_time
            self.recorded_peaks.append((elapsed, self.peak_freq, self.peak_db, harmonics))

        return self.peak_freq, self.peak_db

    def find_harmonics(self, fundamental, max_harmonic=5, tolerance_hz=50):
        """Find harmonics of fundamental frequency and their dB levels"""
        if self.full_spectrum_db is None or fundamental < 100:
            return []

        harmonics = []
        for n in range(1, max_harmonic + 1):
            target_freq = fundamental * n

            # Skip if beyond Nyquist
            if target_freq > self.sample_rate / 2:
                break

            # Find bin closest to target
            freq_diff = np.abs(self.freqs - target_freq)
            closest_idx = np.argmin(freq_diff)

            # Check if within tolerance
            if freq_diff[closest_idx] <= tolerance_hz:
                # Find peak in small window around target
                window_size = int(tolerance_hz / self.freq_resolution)
                start_idx = max(0, closest_idx - window_size)
                end_idx = min(len(self.full_spectrum_db), closest_idx + window_size + 1)

                window_db = self.full_spectrum_db[start_idx:end_idx]
                peak_in_window = np.argmax(window_db)
                actual_idx = start_idx + peak_in_window

                harmonics.append({
                    'n': n,
                    'expected_freq': target_freq,
                    'actual_freq': self.freqs[actual_idx],
                    'db': self.full_spectrum_db[actual_idx]
                })

        return harmonics

    def start_recording(self):
        """Start recording peaks for sweep analysis"""
        self.recording = True
        self.recorded_peaks = []
        self.start_time = time.time()

    def stop_recording(self):
        """Stop recording and return results"""
        self.recording = False
        return self.recorded_peaks

    def get_spectrum_bar(self, width=60):
        """Generate ASCII spectrum bar for terminal display"""
        if self.smoothed_spectrum is None:
            return ""

        # Normalize to 0-1 range
        spec = self.smoothed_spectrum
        spec_norm = (spec - spec.min()) / (spec.max() - spec.min() + 1e-10)

        # Resample to width
        indices = np.linspace(0, len(spec_norm) - 1, width).astype(int)
        bars = spec_norm[indices]

        # Generate bar characters
        bar_chars = " ▁▂▃▄▅▆▇█"
        result = ""
        for b in bars:
            idx = min(int(b * (len(bar_chars) - 1)), len(bar_chars) - 1)
            result += bar_chars[idx]

        return result


def detect_tones(peaks, threshold_db=TONE_THRESHOLD_DB, min_duration=MIN_TONE_DURATION):
    """Detect individual tones from recorded peaks using dB threshold.

    Returns list of tones: [(start_time, end_time, avg_freq, max_db, samples), ...]
    """
    if not peaks:
        return []

    tones = []
    in_tone = False
    tone_start = 0
    tone_samples = []

    for entry in peaks:
        if len(entry) == 4:
            t, freq, db, harmonics = entry
        else:
            t, freq, db = entry
            harmonics = []

        if not in_tone and db > threshold_db:
            # Tone started
            in_tone = True
            tone_start = t
            tone_samples = [(t, freq, db, harmonics)]
        elif in_tone and db > threshold_db:
            # Tone continues
            tone_samples.append((t, freq, db, harmonics))
        elif in_tone and db <= threshold_db:
            # Tone ended
            in_tone = False
            duration = t - tone_start
            if duration >= min_duration and len(tone_samples) >= 3:
                freqs = [s[1] for s in tone_samples]
                dbs = [s[2] for s in tone_samples]
                all_harmonics = [s[3] for s in tone_samples if s[3]]
                tones.append({
                    'start': tone_start,
                    'end': t,
                    'duration': duration,
                    'avg_freq': np.median(freqs),
                    'max_db': np.max(dbs),
                    'avg_db': np.mean(dbs),
                    'samples': len(tone_samples),
                    'harmonics': all_harmonics
                })
            tone_samples = []

    # Handle tone at end of recording
    if in_tone and len(tone_samples) >= 3:
        t = tone_samples[-1][0]
        duration = t - tone_start
        if duration >= min_duration:
            freqs = [s[1] for s in tone_samples]
            dbs = [s[2] for s in tone_samples]
            all_harmonics = [s[3] for s in tone_samples if s[3]]
            tones.append({
                'start': tone_start,
                'end': t,
                'duration': duration,
                'avg_freq': np.median(freqs),
                'max_db': np.max(dbs),
                'avg_db': np.mean(dbs),
                'samples': len(tone_samples),
                'harmonics': all_harmonics
            })

    return tones


def analyze_sweep(peaks, tone_duration=1.5, pause_duration=0.5):
    """Analyze recorded sweep with auto-detection of sweep start.

    Detects the intro pattern (2 beeps at ~3000 Hz) and finds sweep start.
    Maps tones to expected frequencies by order, not absolute time.
    """
    if not peaks:
        return None

    # Step 1: Detect all tones
    tones = detect_tones(peaks)

    if len(tones) < 3:
        print(f"  ⚠ Only {len(tones)} tones detected, need at least 3")
        return None

    print(f"\n  🔍 Detected {len(tones)} tones")

    # Step 2: Find intro pattern (2 beeps at ~3000 Hz followed by lower frequency)
    sweep_start_idx = 0

    # Look for intro: first 2 tones should be at ~3000 Hz (intro beeps)
    # Then tone 3+ should be at lower frequency (sweep starts at 2400 Hz)
    if len(tones) >= 3:
        tone1_freq = tones[0]['avg_freq']
        tone2_freq = tones[1]['avg_freq']
        tone3_freq = tones[2]['avg_freq']

        # Check if first two tones are intro beeps (~3000 Hz, short duration)
        is_intro1 = (2800 <= tone1_freq <= 3200) and (tones[0]['duration'] < 1.0)
        is_intro2 = (2800 <= tone2_freq <= 3200) and (tones[1]['duration'] < 1.0)
        is_sweep_start = (2300 <= tone3_freq <= 2700)  # First sweep tone ~2400 Hz

        if is_intro1 and is_intro2 and is_sweep_start:
            sweep_start_idx = 2
            print(f"  ✓ Detected intro beeps, sweep starts at tone #{sweep_start_idx + 1}")
        elif is_intro1 and is_sweep_start:
            # Only one intro beep detected
            sweep_start_idx = 1
            print(f"  ⚠ Only 1 intro beep detected, sweep starts at tone #{sweep_start_idx + 1}")
        else:
            print(f"  ⚠ No intro pattern detected (tones: {tone1_freq:.0f}, {tone2_freq:.0f}, {tone3_freq:.0f} Hz)")
            print(f"     Assuming recording started during sweep")

    # Step 3: Map sweep tones to expected frequencies by order
    sweep_tones = tones[sweep_start_idx:]
    num_expected = int((FREQ_MAX - FREQ_MIN) / FREQ_STEP) + 1

    print(f"  📊 Mapping {len(sweep_tones)} sweep tones to {num_expected} expected frequencies")

    results = []
    for i, tone in enumerate(sweep_tones):
        if i >= num_expected:
            break  # Beyond one sweep cycle

        expected_freq = FREQ_MIN + i * FREQ_STEP

        # Aggregate harmonics
        harmonic_summary = {}
        for h_list in tone['harmonics']:
            for h in h_list:
                n = h['n']
                if n not in harmonic_summary:
                    harmonic_summary[n] = []
                harmonic_summary[n].append(h['db'])

        harmonics_avg = {}
        for n, db_list in harmonic_summary.items():
            harmonics_avg[n] = np.mean(db_list)

        results.append({
            'expected_freq': expected_freq,
            'avg_db': tone['avg_db'],
            'max_db': tone['max_db'],
            'detected_freq': tone['avg_freq'],
            'samples': tone['samples'],
            'duration': tone['duration'],
            'harmonics': harmonics_avg
        })

    return results


def print_results(results, output_file=None):
    """Print and optionally save sweep analysis results"""
    if not results:
        print("\n❌ No valid data recorded. Make sure buzzer is running during recording.")
        return

    print("\n" + "=" * 65)
    print("BUZZER SWEEP ANALYSIS RESULTS")
    print("=" * 65)

    # Find best frequency
    best = max(results, key=lambda x: x['max_db'])

    print(f"\n🏆 BEST FREQUENCY: {best['expected_freq']:.0f} Hz")
    print(f"   Max dB: {best['max_db']:.1f} dB")
    print(f"   Detected at: {best['detected_freq']:.0f} Hz")

    print("\n📊 All frequencies ranked by loudness:")
    print("-" * 75)
    print(f"{'Freq (Hz)':>10} {'Max dB':>10} {'Avg dB':>10} {'Detected':>12} {'Δ':>6} {'Samples':>8}")
    print("-" * 75)

    # Sort by max_db descending
    for r in sorted(results, key=lambda x: x['max_db'], reverse=True):
        marker = " 🔊" if r == best else ""
        delta = abs(r['detected_freq'] - r['expected_freq'])
        delta_str = f"{delta:+.0f}" if delta < 100 else "!!!"
        print(f"{r['expected_freq']:>10.0f} {r['max_db']:>10.1f} {r['avg_db']:>10.1f} "
              f"{r['detected_freq']:>12.0f} {delta_str:>6} {r['samples']:>8}{marker}")

    print("-" * 75)

    # Harmonics analysis
    print("\n🎵 Harmonics Analysis (Top 5 frequencies):")
    print("-" * 65)
    top5 = sorted(results, key=lambda x: x['max_db'], reverse=True)[:5]
    for r in top5:
        h = r.get('harmonics', {})
        if h:
            h_str = "  ".join(f"H{n}:{db:.0f}dB" for n, db in sorted(h.items()) if n > 1)
            if h_str:
                print(f"  {r['expected_freq']:4.0f} Hz: {h_str}")
            else:
                print(f"  {r['expected_freq']:4.0f} Hz: (no harmonics detected)")
        else:
            print(f"  {r['expected_freq']:4.0f} Hz: (no harmonics data)")

    # Recommendations
    print("\n💡 Recommendations:")

    # Top 3 frequencies
    top3 = sorted(results, key=lambda x: x['max_db'], reverse=True)[:3]
    top3_str = ', '.join(f"{r['expected_freq']:.0f} Hz" for r in top3)
    print(f"   • Top 3 loudest: {top3_str}")

    # Check for low frequency options (better grass penetration)
    low_freq = [r for r in results if r['expected_freq'] <= 3000]
    if low_freq:
        best_low = max(low_freq, key=lambda x: x['max_db'])
        diff = best['max_db'] - best_low['max_db']
        if diff < 3:
            print(f"   • For grass penetration: {best_low['expected_freq']:.0f} Hz "
                  f"(only {diff:.1f} dB quieter, but better range)")
        else:
            print(f"   • Low freq option: {best_low['expected_freq']:.0f} Hz "
                  f"({diff:.1f} dB quieter than peak)")

    # Harmonics recommendation
    best_harmonics = None
    best_h_count = 0
    for r in results:
        h = r.get('harmonics', {})
        h_count = sum(1 for n, db in h.items() if n > 1 and db > -50)
        if h_count > best_h_count:
            best_h_count = h_count
            best_harmonics = r

    if best_harmonics and best_h_count >= 2:
        print(f"   • Best harmonics: {best_harmonics['expected_freq']:.0f} Hz "
              f"({best_h_count} audible harmonics - helps localization)")

    print("\n" + "=" * 65)

    # Save to file
    if output_file:
        import csv
        # Flatten harmonics for CSV export
        csv_results = []
        for r in results:
            row = {
                'expected_freq': r['expected_freq'],
                'max_db': r['max_db'],
                'avg_db': r['avg_db'],
                'detected_freq': r['detected_freq'],
                'delta_freq': abs(r['detected_freq'] - r['expected_freq']),
                'samples': r['samples'],
                'duration': r.get('duration', 0)
            }
            # Add harmonics columns
            for n in range(2, 6):
                row[f'H{n}_db'] = r.get('harmonics', {}).get(n, None)
            csv_results.append(row)

        fieldnames = ['expected_freq', 'max_db', 'avg_db', 'detected_freq', 'delta_freq',
                      'samples', 'duration', 'H2_db', 'H3_db', 'H4_db', 'H5_db']
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_results)
        print(f"\n📁 Results saved to: {output_file}")


def live_monitor(analyzer, duration=None, device=None):
    """Live spectrum monitoring with terminal display"""
    print("\n🎤 Live Spectrum Monitor")
    print("   Range: 2400-4500 Hz | Press Ctrl+C to stop")
    print("-" * 70)

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    start_time = time.time()

    def audio_callback(indata, frames, time_info, status):
        if status:
            pass  # Ignore overflow warnings
        analyzer.process_audio(indata)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                        blocksize=BLOCK_SIZE, callback=audio_callback,
                        device=device):
        while running:
            if duration and (time.time() - start_time) > duration:
                break

            # Clear line and print spectrum
            bar = analyzer.get_spectrum_bar(40)
            freq_str = f"{analyzer.peak_freq:4.0f} Hz"
            db_str = f"{analyzer.peak_db:5.1f} dB"

            # Get harmonics info
            harmonics = analyzer.find_harmonics(analyzer.peak_freq)
            h_str = ""
            if harmonics and len(harmonics) > 1:
                h_count = sum(1 for h in harmonics if h['n'] > 1 and h['db'] > -50)
                if h_count > 0:
                    h_str = f" H:{h_count}"

            # Color coding for terminal (ANSI)
            if analyzer.peak_db > -20:
                color = "\033[92m"  # Green - loud
            elif analyzer.peak_db > -35:
                color = "\033[93m"  # Yellow - medium
            else:
                color = "\033[91m"  # Red - quiet
            reset = "\033[0m"

            print(f"\r{color}Peak: {freq_str} | {db_str}{h_str}{reset} | [{bar}]", end="", flush=True)

            time.sleep(0.1)

    print("\n")


def record_sweep(analyzer, sweep_duration=50, device=None):
    """Record a complete calibration sweep"""
    print("\n🔴 RECORDING MODE")
    print("=" * 65)
    print(f"   Expected sweep duration: ~{sweep_duration} seconds")
    print("   Range: 2400-4500 Hz, step 100 Hz")
    print("\n   1. Connect buzzer (don't power on yet)")
    print("   2. Short PB1 to GND for calibration mode")
    print("   3. Power on buzzer")
    print("   4. Press Enter when ready to start recording...")

    input()

    print("\n🎤 Recording... Press Ctrl+C when sweep completes")
    print("-" * 65)

    analyzer.start_recording()
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False

    old_handler = signal.signal(signal.SIGINT, signal_handler)

    def audio_callback(indata, frames, time_info, status):
        analyzer.process_audio(indata)

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                            blocksize=BLOCK_SIZE, callback=audio_callback,
                            device=device):
            start = time.time()
            while running:
                elapsed = time.time() - start
                bar = analyzer.get_spectrum_bar(40)
                print(f"\r  {elapsed:5.1f}s | Peak: {analyzer.peak_freq:4.0f} Hz "
                      f"| {analyzer.peak_db:5.1f} dB | [{bar}]", end="", flush=True)
                time.sleep(0.1)
    finally:
        signal.signal(signal.SIGINT, old_handler)

    print("\n\n⏹ Recording stopped")

    peaks = analyzer.stop_recording()
    print(f"   Recorded {len(peaks)} samples over {peaks[-1][0]:.1f} seconds")

    return peaks


def main():
    parser = argparse.ArgumentParser(
        description="Real-time buzzer frequency analyzer for macOS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python buzzer_analyzer.py              # Live monitoring
  python buzzer_analyzer.py --record     # Record calibration sweep
  python buzzer_analyzer.py --record -o results.csv  # Save to file
        """
    )

    parser.add_argument('--record', '-r', action='store_true',
                        help='Record calibration sweep and analyze')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Output CSV file for results')
    parser.add_argument('--duration', '-d', type=float, default=None,
                        help='Recording/monitoring duration in seconds')
    parser.add_argument('--list-devices', action='store_true',
                        help='List available audio input devices')
    parser.add_argument('--device', '-D', type=int, default=None,
                        help='Input device index (see --list-devices)')

    args = parser.parse_args()

    if args.list_devices:
        print("\n📱 Available audio INPUT devices:")
        print("-" * 50)
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                marker = " (default)" if dev == sd.query_devices(kind='input') else ""
                print(f"  [{i}] {dev['name']}{marker}")
        print("\nUsage: python buzzer_analyzer.py -D <index>")
        return

    print("\n" + "=" * 65)
    print("  🔊 BUZZER FREQUENCY ANALYZER")
    print("=" * 65)
    print(f"  Sample rate: {SAMPLE_RATE} Hz")
    print(f"  FFT size: {BLOCK_SIZE} ({BLOCK_SIZE/SAMPLE_RATE*1000:.0f} ms)")
    print(f"  Frequency resolution: {SAMPLE_RATE/BLOCK_SIZE:.1f} Hz")
    print(f"  Buzzer range: {FREQ_MIN}-{FREQ_MAX} Hz")

    # Check microphone access
    try:
        sd.query_devices(kind='input')
    except Exception as e:
        print(f"\n❌ Error accessing microphone: {e}")
        print("   Make sure Terminal has microphone access in System Preferences")
        return 1

    # Select device
    device = args.device
    if device is not None:
        try:
            dev_info = sd.query_devices(device)
            print(f"  Using device: [{device}] {dev_info['name']}")
        except Exception as e:
            print(f"\n❌ Invalid device index {device}: {e}")
            return 1
    else:
        default_dev = sd.query_devices(kind='input')
        print(f"  Using device: {default_dev['name']} (default)")

    analyzer = SpectrumAnalyzer()

    if args.record:
        # Record and analyze sweep
        peaks = record_sweep(analyzer, args.duration or 50, device=device)
        results = analyze_sweep(peaks)

        output_file = args.output
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"buzzer_analysis_{timestamp}.csv"

        print_results(results, output_file)
    else:
        # Live monitoring
        live_monitor(analyzer, args.duration, device=device)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
