#!/usr/bin/env python3
"""
Audio Spectrum Analyzer for Buzzer Calibration
Analyzes Phyphox/Decibel X export data to find optimal frequency

Usage:
    python analyze_spectrum.py <path_to_export_folder>
    python analyze_spectrum.py  # uses latest in ~/Downloads
"""

import sys
import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def find_latest_export(downloads_dir="~/Downloads"):
    """Find the latest Audio Spectrum export folder"""
    downloads = os.path.expanduser(downloads_dir)
    pattern = os.path.join(downloads, "Audio Spectrum*")
    folders = glob.glob(pattern)
    if not folders:
        raise FileNotFoundError(f"No Audio Spectrum exports found in {downloads}")
    return max(folders, key=os.path.getmtime)


def load_fft_spectrum(folder):
    """Load FFT Spectrum data"""
    path = os.path.join(folder, "FFT Spectrum.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df.columns = ['frequency', 'amplitude']
    return df


def load_peak_history(folder):
    """Load Peak History data"""
    path = os.path.join(folder, "Peak History.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df.columns = ['time', 'peak_freq']
    return df


def load_raw_data(folder):
    """Load Raw audio data"""
    path = os.path.join(folder, "Raw data.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df.columns = ['time', 'amplitude']
    return df


def analyze_fft(df, freq_min=2400, freq_max=4500):
    """Analyze FFT spectrum for buzzer frequency range"""
    # Filter to our frequency range
    mask = (df['frequency'] >= freq_min) & (df['frequency'] <= freq_max)
    buzzer_range = df[mask].copy()

    if buzzer_range.empty:
        print(f"No data in {freq_min}-{freq_max} Hz range")
        return None

    # Find peak
    peak_idx = buzzer_range['amplitude'].idxmax()
    peak_freq = buzzer_range.loc[peak_idx, 'frequency']
    peak_amp = buzzer_range.loc[peak_idx, 'amplitude']

    # Calculate energy in different bands
    bands = [
        (2400, 2800, "Low (2.4-2.8 kHz)"),
        (2800, 3200, "Mid-Low (2.8-3.2 kHz)"),
        (3200, 3600, "Mid-High (3.2-3.6 kHz)"),
        (3600, 4500, "High (3.6-4.5 kHz)"),
    ]

    band_energy = []
    for f_low, f_high, name in bands:
        band_mask = (df['frequency'] >= f_low) & (df['frequency'] < f_high)
        energy = df.loc[band_mask, 'amplitude'].sum()
        band_energy.append((name, f_low, f_high, energy))

    return {
        'peak_freq': peak_freq,
        'peak_amp': peak_amp,
        'buzzer_range': buzzer_range,
        'band_energy': band_energy,
        'full_spectrum': df
    }


def find_harmonics(df, fundamental, tolerance=50):
    """Find harmonics of fundamental frequency"""
    harmonics = []
    for n in range(1, 8):  # 1st through 7th harmonic
        target = fundamental * n
        mask = (df['frequency'] >= target - tolerance) & (df['frequency'] <= target + tolerance)
        if mask.any():
            band = df[mask]
            peak_idx = band['amplitude'].idxmax()
            harmonics.append({
                'n': n,
                'expected': target,
                'actual': band.loc[peak_idx, 'frequency'],
                'amplitude': band.loc[peak_idx, 'amplitude']
            })
    return harmonics


def analyze_sweep(peak_history, tone_duration=1.5, pause_duration=0.5,
                  freq_min=2400, freq_max=4500, freq_step=100):
    """Analyze calibration sweep from peak history"""
    if peak_history is None or peak_history.empty:
        return None

    step_duration = tone_duration + pause_duration
    num_steps = int((freq_max - freq_min) / freq_step) + 1

    results = []
    for i in range(num_steps):
        expected_freq = freq_min + i * freq_step
        t_start = i * step_duration
        t_end = t_start + tone_duration

        # Get peaks during this tone
        mask = (peak_history['time'] >= t_start) & (peak_history['time'] < t_end)
        tone_peaks = peak_history[mask]

        if not tone_peaks.empty:
            avg_peak = tone_peaks['peak_freq'].mean()
            max_peak = tone_peaks['peak_freq'].max()
            results.append({
                'expected_freq': expected_freq,
                'time_start': t_start,
                'avg_detected': avg_peak,
                'max_detected': max_peak,
                'samples': len(tone_peaks)
            })

    return pd.DataFrame(results)


def plot_analysis(analysis, output_path=None):
    """Generate analysis plots"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Full spectrum with buzzer range highlighted
    ax1 = axes[0, 0]
    df = analysis['full_spectrum']
    ax1.semilogy(df['frequency'], df['amplitude'], 'b-', alpha=0.7, linewidth=0.5)

    # Highlight buzzer range
    buzzer = analysis['buzzer_range']
    ax1.semilogy(buzzer['frequency'], buzzer['amplitude'], 'r-', linewidth=1.5, label='Buzzer range')
    ax1.axvline(analysis['peak_freq'], color='g', linestyle='--', label=f'Peak: {analysis["peak_freq"]:.0f} Hz')

    ax1.set_xlabel('Frequency (Hz)')
    ax1.set_ylabel('Amplitude (log)')
    ax1.set_title('Full Spectrum')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, 10000)

    # 2. Buzzer range detail
    ax2 = axes[0, 1]
    ax2.plot(buzzer['frequency'], buzzer['amplitude'], 'r-', linewidth=1.5)
    ax2.axvline(analysis['peak_freq'], color='g', linestyle='--',
                label=f'Peak: {analysis["peak_freq"]:.0f} Hz')
    ax2.fill_between(buzzer['frequency'], buzzer['amplitude'], alpha=0.3)
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('Amplitude')
    ax2.set_title('Buzzer Range (2400-4500 Hz)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Band energy comparison
    ax3 = axes[1, 0]
    band_names = [b[0] for b in analysis['band_energy']]
    band_values = [b[3] for b in analysis['band_energy']]
    colors = ['#2ecc71', '#3498db', '#9b59b6', '#e74c3c']
    bars = ax3.bar(range(len(band_names)), band_values, color=colors)
    ax3.set_xticks(range(len(band_names)))
    ax3.set_xticklabels(band_names, rotation=15, ha='right')
    ax3.set_ylabel('Total Energy')
    ax3.set_title('Energy by Frequency Band')
    ax3.grid(True, alpha=0.3, axis='y')

    # Add values on bars
    for bar, val in zip(bars, band_values):
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.2e}', ha='center', va='bottom', fontsize=9)

    # 4. Harmonics (if fundamental detected)
    ax4 = axes[1, 1]
    harmonics = find_harmonics(df, analysis['peak_freq'])
    if harmonics:
        h_n = [h['n'] for h in harmonics]
        h_amp = [h['amplitude'] for h in harmonics]
        ax4.bar(h_n, h_amp, color='purple', alpha=0.7)
        ax4.set_xlabel('Harmonic Number')
        ax4.set_ylabel('Amplitude')
        ax4.set_title(f'Harmonics of {analysis["peak_freq"]:.0f} Hz')
        ax4.set_xticks(h_n)
        ax4.grid(True, alpha=0.3, axis='y')

        # Add frequency labels
        for h in harmonics:
            ax4.text(h['n'], h['amplitude'], f'{h["actual"]:.0f}Hz',
                    ha='center', va='bottom', fontsize=8, rotation=45)
    else:
        ax4.text(0.5, 0.5, 'No harmonics detected', ha='center', va='center',
                transform=ax4.transAxes)
        ax4.set_title('Harmonics Analysis')

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to {output_path}")

    plt.show()


def print_report(analysis):
    """Print analysis report"""
    print("\n" + "="*60)
    print("BUZZER FREQUENCY ANALYSIS REPORT")
    print("="*60)

    print(f"\n📊 Peak Frequency: {analysis['peak_freq']:.1f} Hz")
    print(f"   Peak Amplitude: {analysis['peak_amp']:.4e}")

    print("\n📈 Energy by Band:")
    print("-" * 45)
    total_energy = sum(b[3] for b in analysis['band_energy'])
    for name, f_low, f_high, energy in analysis['band_energy']:
        pct = (energy / total_energy) * 100 if total_energy > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {name:25s} {bar} {pct:5.1f}%")

    print("\n🎵 Harmonics:")
    print("-" * 45)
    harmonics = find_harmonics(analysis['full_spectrum'], analysis['peak_freq'])
    if harmonics:
        for h in harmonics:
            rel_amp = h['amplitude'] / harmonics[0]['amplitude'] * 100
            print(f"  {h['n']}x {h['expected']:6.0f} Hz → {h['actual']:6.0f} Hz ({rel_amp:5.1f}%)")
    else:
        print("  No significant harmonics detected")

    print("\n💡 Recommendations:")
    print("-" * 45)

    # Find band with most energy
    best_band = max(analysis['band_energy'], key=lambda x: x[3])
    print(f"  • Highest energy band: {best_band[0]}")
    print(f"  • Peak frequency: {analysis['peak_freq']:.0f} Hz")

    # Penetration recommendation
    if analysis['peak_freq'] < 3000:
        print("  • Low frequency - good penetration through grass ✓")
    elif analysis['peak_freq'] > 4000:
        print("  • High frequency - may not penetrate grass well ⚠")
    else:
        print("  • Mid frequency - balanced choice")

    # Check for strong harmonics
    if harmonics and len(harmonics) > 3:
        print(f"  • Strong harmonics detected - good for varied hearing ✓")

    print("\n" + "="*60)


def main():
    # Find data folder
    if len(sys.argv) > 1:
        folder = sys.argv[1]
    else:
        try:
            folder = find_latest_export()
            print(f"Using latest export: {folder}")
        except FileNotFoundError as e:
            print(e)
            sys.exit(1)

    # Load data
    print(f"\nLoading data from: {folder}")
    fft_df = load_fft_spectrum(folder)
    peak_history = load_peak_history(folder)

    if fft_df is None:
        print("ERROR: FFT Spectrum.csv not found")
        sys.exit(1)

    print(f"  FFT Spectrum: {len(fft_df)} frequency bins")
    if peak_history is not None:
        print(f"  Peak History: {len(peak_history)} samples over {peak_history['time'].max():.1f}s")

    # Analyze
    analysis = analyze_fft(fft_df)
    if analysis is None:
        print("ERROR: Could not analyze spectrum")
        sys.exit(1)

    # Report
    print_report(analysis)

    # Plot
    output_plot = os.path.join(folder, "analysis_plot.png")
    plot_analysis(analysis, output_plot)

    # Export summary CSV
    summary_path = os.path.join(folder, "analysis_summary.csv")
    summary_df = pd.DataFrame([{
        'peak_freq_hz': analysis['peak_freq'],
        'peak_amplitude': analysis['peak_amp'],
        **{f'energy_{b[0]}': b[3] for b in analysis['band_energy']}
    }])
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    main()
