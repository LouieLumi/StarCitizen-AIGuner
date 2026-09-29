// AI Crew Controller firmware: USB CDC (commands in) + HID mouse, keyboard and joystick (input out).
//
// Safety: every output is released (buttons and keys up, no motion, joystick centred) when
// the host goes quiet for HOST_TIMEOUT_US, closes the serial port, or the USB
// bus is suspended / unplugged.

#include <stdio.h>
#include <string.h>

#include "pico/bootrom.h"
#include "pico/stdlib.h"
#include "tusb.h"

#include "protocol.h"
#include "usb_descriptors.h"

#define FW_VERSION "0.3.0"

#ifndef FW_BOARD
#define FW_BOARD "unknown"
#endif

// Release all outputs if no command arrives for this long.
#define HOST_TIMEOUT_US (100 * 1000)

// Cap on queued-but-unsent motion so a command burst can't keep the
// cursor moving long after the host stopped.
#define MAX_PENDING_MOTION 2048

static line_parser_t parser;

static int32_t pending_dx;
static int32_t pending_dy;
static uint8_t buttons;      // state requested by the host
static uint8_t sent_buttons; // state last reported to the PC

static uint8_t key_mods, key_code;           // keyboard state requested by the host
static uint8_t sent_key_mods, sent_key_code; // state last reported to the PC

static joystick_report_t joy;      // state requested by the host
static joystick_report_t joy_sent; // state last reported to the PC
static bool joy_sent_valid;        // false until the first report after (re)mount

static bool host_active;
static absolute_time_t last_cmd_time;

static struct {
    uint32_t cmds;
    uint32_t errors;
    uint32_t timeouts;
    uint32_t reports;
    uint32_t joy_reports;
    uint32_t key_reports;
} stats;

static void release_all(void) {
    pending_dx = 0;
    pending_dy = 0;
    buttons = 0;
    key_mods = 0;
    key_code = 0;
    memset(&joy, 0, sizeof(joy));
}

static int32_t clamp_i32(int32_t v, int32_t lo, int32_t hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static void cdc_reply(const char *s) {
    tud_cdc_write_str(s);
    tud_cdc_write_str("\n");
    tud_cdc_write_flush();
}

static void reboot_to_bootsel(void) {
    release_all();
    cdc_reply("OK BOOTSEL");
    // Let the reply and a final zero HID report leave before USB drops.
    for (int i = 0; i < 50; i++) {
        tud_task();
        sleep_ms(1);
    }
    reset_usb_boot(0, 0);
}

static void handle_command(const cmd_t *cmd) {
    char msg[128];

    if (cmd->type == CMD_INVALID) {
        stats.errors++;
        cdc_reply("ERR");
        return;
    }

    stats.cmds++;
    last_cmd_time = get_absolute_time();
    host_active = true;

    switch (cmd->type) {
    case CMD_MOVE:
        pending_dx = clamp_i32(pending_dx + cmd->dx, -MAX_PENDING_MOTION, MAX_PENDING_MOTION);
        pending_dy = clamp_i32(pending_dy + cmd->dy, -MAX_PENDING_MOTION, MAX_PENDING_MOTION);
        buttons = cmd->buttons;
        break;
    case CMD_KEY:
        key_mods = cmd->key_modifiers;
        key_code = cmd->key;
        break;
    case CMD_JOYSTICK:
        memcpy(joy.axes, cmd->axes, sizeof(joy.axes));
        joy.buttons = cmd->joy_buttons;
        break;
    case CMD_STOP:
        release_all();
        cdc_reply("OK STOP");
        break;
    case CMD_PING:
        cdc_reply("PONG");
        break;
    case CMD_VER:
        cdc_reply("AI-CREW-FW " FW_VERSION " " FW_BOARD);
        break;
    case CMD_STAT:
        snprintf(msg, sizeof(msg), "STAT cmds=%lu errors=%lu timeouts=%lu reports=%lu joy_reports=%lu key_reports=%lu",
                 (unsigned long)stats.cmds, (unsigned long)stats.errors, (unsigned long)stats.timeouts,
                 (unsigned long)stats.reports, (unsigned long)stats.joy_reports, (unsigned long)stats.key_reports);
        cdc_reply(msg);
        break;
    case CMD_BOOTSEL:
        reboot_to_bootsel();
        break;
    case CMD_INVALID:
        break;
    }
}

static void cdc_task(void) {
    uint8_t buf[64];
    while (tud_cdc_available()) {
        uint32_t n = tud_cdc_read(buf, sizeof(buf));
        for (uint32_t i = 0; i < n; i++) {
            cmd_t cmd;
            if (protocol_feed(&parser, (char)buf[i], &cmd)) {
                handle_command(&cmd);
            }
        }
    }
}

static void host_timeout_task(void) {
    if (host_active && absolute_time_diff_us(last_cmd_time, get_absolute_time()) > HOST_TIMEOUT_US) {
        host_active = false;
        stats.timeouts++;
        release_all();
    }
}

static void mouse_task(void) {
    if (!tud_hid_n_ready(HID_INST_MOUSE)) {
        return;
    }
    if (pending_dx == 0 && pending_dy == 0 && buttons == sent_buttons) {
        return;
    }

    // A report carries at most +/-127 counts per axis; larger moves are
    // spread over consecutive 1 ms reports.
    int8_t dx = (int8_t)clamp_i32(pending_dx, -127, 127);
    int8_t dy = (int8_t)clamp_i32(pending_dy, -127, 127);
    if (tud_hid_n_mouse_report(HID_INST_MOUSE, REPORT_ID_MOUSE, buttons, dx, dy, 0, 0)) {
        pending_dx -= dx;
        pending_dy -= dy;
        sent_buttons = buttons;
        stats.reports++;
    }
}

// Keyboard shares the mouse interface (report ID 2); report only on changes (the PC keeps
// the key down until told otherwise). Returns true when it used the endpoint.
static bool keyboard_task(void) {
    if (key_mods == sent_key_mods && key_code == sent_key_code) {
        return false;
    }
    if (!tud_hid_n_ready(HID_INST_MOUSE)) {
        return false;
    }
    uint8_t keycodes[6] = {key_code, 0, 0, 0, 0, 0};
    if (tud_hid_n_keyboard_report(HID_INST_MOUSE, REPORT_ID_KEYBOARD, key_mods, keycodes)) {
        sent_key_mods = key_mods;
        sent_key_code = key_code;
        stats.key_reports++;
        return true;
    }
    return false;
}

// The joystick is absolute: report only when the state changes (the PC keeps the last value).
static void joystick_task(void) {
    if (!tud_hid_n_ready(HID_INST_JOYSTICK)) {
        return;
    }
    if (joy_sent_valid && memcmp(&joy, &joy_sent, sizeof(joy)) == 0) {
        return;
    }
    if (tud_hid_n_report(HID_INST_JOYSTICK, 0, &joy, sizeof(joy))) {
        joy_sent = joy;
        joy_sent_valid = true;
        stats.joy_reports++;
    }
}

static void hid_task(void) {
    if (!tud_mounted() || tud_suspended()) {
        return;
    }
    if (!keyboard_task()) { // key changes first; the mouse report goes out next millisecond
        mouse_task();
    }
    joystick_task();
}

int main(void) {
    protocol_init(&parser);
    tud_init(BOARD_TUD_RHPORT);

    while (true) {
        tud_task();
        cdc_task();
        host_timeout_task();
        hid_task();
    }
}

//--------------------------------------------------------------------+
// TinyUSB callbacks
//--------------------------------------------------------------------+

void tud_mount_cb(void) {
    release_all();
    sent_buttons = 0;
    sent_key_mods = sent_key_code = 0;
    joy_sent_valid = false;
}

void tud_umount_cb(void) {
    release_all();
    sent_buttons = 0;
    sent_key_mods = sent_key_code = 0;
    joy_sent_valid = false;
}

void tud_suspend_cb(bool remote_wakeup_en) {
    (void)remote_wakeup_en;
    release_all();
}

// Host closed the port (or the program holding it died): release now
// instead of waiting for the timeout.
void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts) {
    (void)itf;
    (void)rts;
    if (!dtr) {
        release_all();
        host_active = false;
    }
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)report_id;
    if (instance == HID_INST_JOYSTICK && report_type == HID_REPORT_TYPE_INPUT && reqlen >= sizeof(joy)) {
        memcpy(buffer, &joy, sizeof(joy));
        return sizeof(joy);
    }
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}
