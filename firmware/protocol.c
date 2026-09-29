#include "protocol.h"

#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

void protocol_init(line_parser_t *p) {
    p->len = 0;
    p->overflow = false;
}

// Parse a decimal integer in [min, max] that must be followed by `terminator`.
// Advances *s past the terminator on success.
static bool parse_int(const char **s, long min, long max, char terminator, long *out) {
    char *end;
    errno = 0;
    long v = strtol(*s, &end, 10);
    if (end == *s || errno != 0 || v < min || v > max || *end != terminator) {
        return false;
    }
    *out = v;
    *s = (terminator == '\0') ? end : end + 1;
    return true;
}

// Same for an unsigned 32-bit value (long is only 32 bits on the RP2350).
static bool parse_u32(const char **s, char terminator, uint32_t *out) {
    char *end;
    if (!isdigit((unsigned char)**s)) {
        return false; // strtoul would silently accept and negate "-1"
    }
    errno = 0;
    unsigned long v = strtoul(*s, &end, 10);
    if (errno != 0 || v > 0xFFFFFFFFUL || *end != terminator) {
        return false;
    }
    *out = (uint32_t)v;
    *s = (terminator == '\0') ? end : end + 1;
    return true;
}

static bool parse_joystick(const char *s, cmd_t *out) {
    for (int i = 0; i < JOY_AXES; i++) {
        long v;
        if (!parse_int(&s, -PROTOCOL_AXIS_MAX, PROTOCOL_AXIS_MAX, ',', &v)) {
            return false;
        }
        out->axes[i] = (int16_t)v;
    }
    return parse_u32(&s, '\0', &out->joy_buttons);
}

void protocol_parse_line(const char *line, cmd_t *out) {
    memset(out, 0, sizeof(*out));
    out->type = CMD_INVALID;

    if (line[0] == 'J' && line[1] == ',') {
        if (parse_joystick(line + 2, out)) {
            out->type = CMD_JOYSTICK;
        }
    } else if (line[0] == 'M' && line[1] == ',') {
        const char *s = line + 2;
        long dx, dy, buttons;
        if (parse_int(&s, -PROTOCOL_MAX_DELTA, PROTOCOL_MAX_DELTA, ',', &dx) &&
            parse_int(&s, -PROTOCOL_MAX_DELTA, PROTOCOL_MAX_DELTA, ',', &dy) &&
            parse_int(&s, 0, 7, '\0', &buttons)) {
            out->type = CMD_MOVE;
            out->dx = (int32_t)dx;
            out->dy = (int32_t)dy;
            out->buttons = (uint8_t)buttons;
        }
    } else if (line[0] == 'K' && line[1] == ',') {
        const char *s = line + 2;
        long mods, key;
        if (parse_int(&s, 0, 255, ',', &mods) && parse_int(&s, 0, 255, '\0', &key)) {
            out->type = CMD_KEY;
            out->key_modifiers = (uint8_t)mods;
            out->key = (uint8_t)key;
        }
    } else if (strcmp(line, "STOP") == 0) {
        out->type = CMD_STOP;
    } else if (strcmp(line, "PING") == 0) {
        out->type = CMD_PING;
    } else if (strcmp(line, "VER") == 0) {
        out->type = CMD_VER;
    } else if (strcmp(line, "STAT") == 0) {
        out->type = CMD_STAT;
    } else if (strcmp(line, "BOOTSEL") == 0) {
        out->type = CMD_BOOTSEL;
    }
}

bool protocol_feed(line_parser_t *p, char c, cmd_t *out) {
    if (c != '\n') {
        if (p->len < PROTOCOL_MAX_LINE - 1) {
            p->buf[p->len++] = (char)toupper((unsigned char)c);
        } else {
            p->overflow = true;
        }
        return false;
    }

    // Strip trailing CR / whitespace.
    while (p->len > 0 && isspace((unsigned char)p->buf[p->len - 1])) {
        p->len--;
    }
    p->buf[p->len] = '\0';

    bool overflow = p->overflow;
    bool empty = (p->len == 0);
    if (!overflow && !empty) {
        protocol_parse_line(p->buf, out);
    }
    protocol_init(p);

    if (overflow) {
        out->type = CMD_INVALID;
        return true;
    }
    return !empty;
}
