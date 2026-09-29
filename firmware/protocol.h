#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

// Host -> Pico text protocol. One command per line, "\n" or "\r\n".
//
//   M,<dx>,<dy>,<buttons>   relative mouse move; buttons is a level, not an edge
//                           (bit0 left, bit1 right, bit2 middle)
//   K,<modifiers>,<key>     keyboard: modifier bits (HID: bit0 LCtrl .. bit7 RGui) and one
//                           HID usage (0x04 = A, 0x17 = T, 0 = none); held until changed
//   J,<x>,<y>,<z>,<rx>,<ry>,<rz>,<slider>,<buttons>
//                           joystick state: axes -32767..32767 (0 = centre),
//                           buttons = 32-bit bitmask (bit0 = button 1); held until changed
//   STOP                    release everything, centre the joystick -> "OK STOP"
//   PING                                                  -> "PONG"
//   VER                     firmware version              -> "AI-CREW-FW <ver> <board>"
//   STAT                    counters                      -> "STAT k=v ..."
//   BOOTSEL                 reboot into the UF2 bootloader -> "OK BOOTSEL"
//
// Malformed lines get "ERR". M, K and J produce no reply so they can be sent at 100+ Hz.

#define PROTOCOL_MAX_LINE 96
#define PROTOCOL_MAX_DELTA 32767
#define PROTOCOL_AXIS_MAX 32767
#define JOY_AXES 7

typedef enum {
    CMD_MOVE,
    CMD_JOYSTICK,
    CMD_KEY,
    CMD_STOP,
    CMD_PING,
    CMD_VER,
    CMD_STAT,
    CMD_BOOTSEL,
    CMD_INVALID,
} cmd_type_t;

typedef struct {
    cmd_type_t type;
    // CMD_MOVE
    int32_t dx;
    int32_t dy;
    uint8_t buttons;
    // CMD_JOYSTICK
    int16_t axes[JOY_AXES];
    uint32_t joy_buttons;
    // CMD_KEY
    uint8_t key_modifiers;
    uint8_t key;
} cmd_t;

typedef struct {
    char buf[PROTOCOL_MAX_LINE];
    uint32_t len;
    bool overflow;
} line_parser_t;

void protocol_init(line_parser_t *p);

// Feed one received byte. Returns true when a non-empty line has been
// completed; *out then holds the parsed command (CMD_INVALID if malformed).
bool protocol_feed(line_parser_t *p, char c, cmd_t *out);

void protocol_parse_line(const char *line, cmd_t *out);

#endif
