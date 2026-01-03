# Makefile for ATtiny13A Buzzer
# ==============================

# Target MCU
MCU = attiny13a

# CPU frequency (1.2 MHz with CKDIV8 enabled - factory default)
F_CPU = 1200000UL

# Programmer
PROGRAMMER = usbasp

# Files
TARGET = buzzer
SRC = main.c

# Tools
CC = avr-gcc
OBJCOPY = avr-objcopy
OBJDUMP = avr-objdump
SIZE = avr-size
AVRDUDE = avrdude

# Compiler flags
CFLAGS = -mmcu=$(MCU) -DF_CPU=$(F_CPU) -Os -Wall -Wextra
CFLAGS += -ffunction-sections -fdata-sections
CFLAGS += -Wl,--gc-sections
CFLAGS += -std=c99

# Fuse bits
# Low Fuse:  0x7A = Internal 9.6MHz RC, no CKDIV8
# High Fuse: 0xFF = default (no code protection, no brown-out)
LFUSE = 0x7A
HFUSE = 0xFF

# ========== Targets ==========

.PHONY: all clean flash fuses size disasm

all: $(TARGET).hex size

# Compile
$(TARGET).elf: $(SRC)
	$(CC) $(CFLAGS) -o $@ $^

# Create HEX file
$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

# Show size
size: $(TARGET).elf
	@echo ""
	@echo "===== Firmware Size ====="
	$(SIZE) -C --mcu=$(MCU) $<
	@echo ""

# Disassembly (for debugging)
disasm: $(TARGET).elf
	$(OBJDUMP) -d -S $< > $(TARGET).lss

# Flash firmware
flash: $(TARGET).hex
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -U flash:w:$<:i

# Set fuse bits
fuses:
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -U lfuse:w:$(LFUSE):m -U hfuse:w:$(HFUSE):m

# Read fuse bits
read-fuses:
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -U lfuse:r:-:h -U hfuse:r:-:h

# Check connection to chip
check:
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -v

# Backup current firmware
backup:
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -U flash:r:backup_flash.hex:i
	$(AVRDUDE) -c $(PROGRAMMER) -p $(MCU) -U eeprom:r:backup_eeprom.hex:i

# Clean
clean:
	rm -f $(TARGET).elf $(TARGET).hex $(TARGET).lss

# Full build and flash
install: all fuses flash
	@echo ""
	@echo "===== Flashing Complete! ====="

# ========== Help ==========

help:
	@echo ""
	@echo "ATtiny13A Buzzer - Makefile"
	@echo "==========================="
	@echo ""
	@echo "Available commands:"
	@echo "  make          - Compile firmware"
	@echo "  make flash    - Upload firmware to chip"
	@echo "  make fuses    - Set fuse bits"
	@echo "  make install  - All at once (compile + fuses + flash)"
	@echo "  make check    - Check connection to chip"
	@echo "  make backup   - Backup current firmware"
	@echo "  make size     - Show firmware size"
	@echo "  make clean    - Remove temporary files"
	@echo ""
	@echo "Requirements:"
	@echo "  - avr-gcc, avr-libc"
	@echo "  - avrdude"
	@echo "  - USBasp programmer"
	@echo ""
