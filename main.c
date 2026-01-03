/*
 * ATtiny13A Smart Buzzer for Betaflight FC
 * =========================================
 *
 * Lost Model Buzzer adapter for Betaflight FC.
 * Listens to BUZ- signal and generates square wave at optimal
 * frequency for piezo element. Auto-calibration via frequency sweep.
 *
 * Pinout:
 *   PB1 (pin 6) - Input from FC BUZ- pad (also calibration entry)
 *   PB3 (pin 2) - Output to transistor -> piezo
 *   VCC (pin 8) - 5V from FC
 *   GND (pin 4) - Ground
 *
 * Operation:
 *   BUZ- LOW  = beep (square wave at calibrated frequency)
 *   BUZ- HIGH = silence
 *
 * Calibration (short PB1 to GND at power-on):
 *   1. Two beeps confirm calibration mode
 *   2. Sweep: 2400-3000 Hz, step 100 Hz (~12 sec)
 *   3. Each frequency saved to EEPROM before playing
 *   4. Power off when you hear the best tone - it's saved!
 *
 * See README.md for full documentation.
 *
 * License: MIT
 */

#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/eeprom.h>
#include <avr/wdt.h>
#include <util/delay.h>

/* ========== F_CPU Validation ========== */
#if F_CPU != 1200000UL && F_CPU != 9600000UL
    #error "F_CPU must be 1200000 (1.2 MHz with CKDIV8) or 9600000 (9.6 MHz)"
#endif

/* ========== Pin Configuration ========== */
#define BUZZER_PIN      PB3     // Output to transistor/piezo (software PWM)
#define SIGNAL_PIN      PB1     // Input from FC BUZ- (also used for calibration entry)

#define BUZZER_DDR      DDRB
#define BUZZER_PORT     PORTB
#define SIGNAL_PINR     PINB

/*
 * NOTE: PB3 has no hardware PWM (OC0A/OC0B).
 * Using Timer0 interrupt for software toggle.
 *
 * PB1 dual purpose:
 * - At startup: if LOW (shorted to GND) -> enter calibration
 * - Normal operation: FC signal input (LOW = beep, HIGH = silent)
 */

/* ========== Default Settings ========== */
#define DEFAULT_FREQ    2500    // Default frequency (Hz) - optimal for this piezo (mode #2)
#define EEPROM_FREQ_ADDR 0      // Frequency address in EEPROM (2 bytes)
#define EEPROM_MAGIC_ADDR 2     // Magic byte address
#define EEPROM_MAGIC    0xAB    // Magic byte for validity check

/* ========== Calibration Range ========== */
/*
 * Calibration sweep: 2400-3000 Hz, step 100 Hz
 * Based on spectrum analysis:
 *   - Piezo has discrete resonance modes spaced ~90 Hz apart
 *   - 100 Hz step matches the natural mode spacing
 *   - Finer steps don't help (piezo locks to nearest mode)
 *
 * Total sweep time: 6 steps × 2 sec = ~12 seconds
 */
#define FREQ_MIN        2400    // Minimum sweep frequency (Hz)
#define FREQ_MAX        3000    // Maximum sweep frequency (Hz) - focused range
#define FREQ_STEP       100     // Sweep step (Hz) - matches piezo mode spacing

/* ========== Timing ========== */
#define BEEP_SHORT_MS   100     // Short beep (ms)
#define BEEP_LONG_MS    400     // Long beep (ms)
#define PAUSE_SHORT_MS  100     // Short pause (ms)
#define PAUSE_LONG_MS   300     // Long pause (ms)

#define CALIB_TONE_MS   1500    // Calibration tone duration (ms)
#define CALIB_PAUSE_MS  500     // Pause between calibration tones (ms)

/* ========== Global Variables ========== */
volatile uint16_t current_freq = DEFAULT_FREQ;

/* ========== Sound Generation Functions ========== */

/*
 * Timer0 Compare Match ISR - toggles PB3 for software PWM
 */
ISR(TIM0_COMPA_vect) {
    BUZZER_PORT ^= (1 << BUZZER_PIN);  // Toggle PB3
}

/*
 * Start tone generation at specified frequency
 * Uses Timer0 in CTC mode with interrupt for software toggle on PB3
 */
void tone_start(uint16_t freq) {
    if (freq == 0) return;

    // Calculate OCR0A value for given frequency
    // Formula: OCR0A = F_CPU / (2 * prescaler * freq) - 1
    // With prescaler = 8:
    //   9.6 MHz: OCR0A = 9600000 / (2 * 8 * freq) - 1 = 600000 / freq - 1
    //   1.2 MHz: OCR0A = 1200000 / (2 * 8 * freq) - 1 = 75000 / freq - 1

    #if F_CPU == 9600000UL
    uint16_t ocr_val = (600000UL / freq) - 1;
    #else
    uint16_t ocr_val = (75000UL / freq) - 1;
    #endif

    // Limit OCR0A value (8-bit register)
    if (ocr_val > 255) ocr_val = 255;
    if (ocr_val < 1) ocr_val = 1;

    OCR0A = (uint8_t)ocr_val;

    // PB3 as output
    BUZZER_DDR |= (1 << BUZZER_PIN);

    // Timer0 configuration:
    // - CTC mode (WGM01=1, WGM00=0)
    // - No hardware output (COM0A = 00) - using interrupt instead
    // - Prescaler = 8 (CS01=1)
    TCCR0A = (1 << WGM01);
    TCCR0B = (1 << CS01);

    // Enable Timer0 Compare Match A interrupt
    TIMSK0 |= (1 << OCIE0A);
    sei();
}

/*
 * Stop tone generation
 */
void tone_stop(void) {
    // Disable Timer0 interrupt
    TIMSK0 &= ~(1 << OCIE0A);

    // Stop timer
    TCCR0A = 0;
    TCCR0B = 0;

    // PB3 = LOW (silence)
    BUZZER_PORT &= ~(1 << BUZZER_PIN);
}

/*
 * Play beep with specified duration
 */
void beep(uint16_t freq, uint16_t duration_ms) {
    tone_start(freq);

    // Delay in 10ms blocks (saves flash)
    while (duration_ms >= 10) {
        _delay_ms(10);
        wdt_reset();
        duration_ms -= 10;
    }

    tone_stop();
}

/*
 * Silent pause
 */
void pause(uint16_t duration_ms) {
    while (duration_ms >= 10) {
        _delay_ms(10);
        wdt_reset();
        duration_ms -= 10;
    }
}

/* ========== EEPROM Functions ========== */

/*
 * Load frequency from EEPROM
 * Returns DEFAULT_FREQ if EEPROM is empty or corrupted
 */
uint16_t load_freq_from_eeprom(void) {
    uint8_t magic = eeprom_read_byte((uint8_t*)EEPROM_MAGIC_ADDR);

    if (magic != EEPROM_MAGIC) {
        // EEPROM not initialized
        return DEFAULT_FREQ;
    }

    uint16_t freq = eeprom_read_word((uint16_t*)EEPROM_FREQ_ADDR);

    // Validate range (accept full piezo range for backwards compatibility)
    if (freq < 2400 || freq > 4500) {
        return DEFAULT_FREQ;
    }

    return freq;
}

/*
 * Save frequency to EEPROM
 */
void save_freq_to_eeprom(uint16_t freq) {
    eeprom_write_word((uint16_t*)EEPROM_FREQ_ADDR, freq);
    eeprom_write_byte((uint8_t*)EEPROM_MAGIC_ADDR, EEPROM_MAGIC);
}

/* ========== Calibration Functions ========== */

/*
 * Auto-sweep calibration mode
 * Saves each frequency to EEPROM before playing.
 * User just powers off when hearing the best tone - it's already saved!
 */
void auto_sweep_mode(void) {
    // 2 long beeps = entering auto-sweep
    beep(DEFAULT_FREQ, BEEP_LONG_MS);
    pause(PAUSE_LONG_MS);
    beep(DEFAULT_FREQ, BEEP_LONG_MS);
    pause(500);

    // Loop forever (user powers off to exit)
    while (1) {
        // Play all frequencies, saving each before playing
        for (uint16_t freq = FREQ_MIN; freq <= FREQ_MAX; freq += FREQ_STEP) {
            save_freq_to_eeprom(freq);  // Save BEFORE playing
            current_freq = freq;
            beep(freq, CALIB_TONE_MS);
            pause(CALIB_PAUSE_MS);
        }
        // Short pause before repeating sweep
        pause(1000);
    }
}

/* ========== Main Program ========== */

/*
 * Initialization
 */
void init(void) {
    // PB3 - output (buzzer via software PWM)
    BUZZER_DDR |= (1 << BUZZER_PIN);
    BUZZER_PORT &= ~(1 << BUZZER_PIN);  // LOW by default

    // PB1 - input with pull-up (FC signal / calibration entry)
    BUZZER_DDR &= ~(1 << SIGNAL_PIN);
    BUZZER_PORT |= (1 << SIGNAL_PIN);   // Pull-up enabled

    // Load frequency from EEPROM
    current_freq = load_freq_from_eeprom();

    // Enable watchdog (250ms timeout)
    wdt_enable(WDTO_250MS);
}

/*
 * Check FC signal
 * BUZ- = LOW means "sound requested"
 */
uint8_t fc_wants_sound(void) {
    return !(SIGNAL_PINR & (1 << SIGNAL_PIN));
}

int main(void) {
    init();

    // Short delay for stabilization
    _delay_ms(100);

    // Check calibration mode (PB1/BUZ- shorted to GND at startup)
    if (fc_wants_sound()) {
        // PB1 is LOW = enter calibration
        auto_sweep_mode();  // Never returns, user powers off
    }

    // Normal start: 2 short beeps
    beep(current_freq, BEEP_SHORT_MS);
    pause(PAUSE_SHORT_MS);
    beep(current_freq, BEEP_SHORT_MS);

    pause(200);

    // Main loop
    uint8_t sound_on = 0;

    while (1) {
        if (fc_wants_sound()) {
            // FC wants sound
            if (!sound_on) {
                tone_start(current_freq);
                sound_on = 1;
            }
        } else {
            // FC wants silence
            if (sound_on) {
                tone_stop();
                sound_on = 0;
            }
        }

        // Reset watchdog
        wdt_reset();

        // Small delay for power saving and polling stability (~10000 times/sec)
        _delay_us(100);
    }

    return 0;
}
