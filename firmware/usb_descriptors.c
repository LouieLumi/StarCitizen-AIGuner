#include <string.h>

#include "pico/unique_id.h"
#include "tusb.h"

#include "usb_descriptors.h"

//--------------------------------------------------------------------+
// Device descriptor
//--------------------------------------------------------------------+

enum {
    STRID_LANGID = 0,
    STRID_MANUFACTURER,
    STRID_PRODUCT,
    STRID_SERIAL,
    STRID_CDC,
    STRID_MOUSE,
    STRID_JOYSTICK,
    STRID_COUNT,
};

static tusb_desc_device_t const desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,

    // Interface Association Descriptor: required for CDC inside a composite device.
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,

    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    // Bump when the interface layout changes so Windows re-reads the device.
    .bcdDevice = 0x0300,

    .iManufacturer = STRID_MANUFACTURER,
    .iProduct = STRID_PRODUCT,
    .iSerialNumber = STRID_SERIAL,

    .bNumConfigurations = 1,
};

uint8_t const *tud_descriptor_device_cb(void) {
    return (uint8_t const *)&desc_device;
}

//--------------------------------------------------------------------+
// HID report descriptors
//--------------------------------------------------------------------+

static uint8_t const desc_hid_mouse[] = {
    TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(REPORT_ID_MOUSE)),
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(REPORT_ID_KEYBOARD)),
};

// Generic joystick: 7 x 16-bit absolute axes + 32 buttons (joystick_report_t).
static uint8_t const desc_hid_joystick[] = {
    HID_USAGE_PAGE(HID_USAGE_PAGE_DESKTOP),
    HID_USAGE(HID_USAGE_DESKTOP_JOYSTICK),
    HID_COLLECTION(HID_COLLECTION_APPLICATION),
        HID_USAGE_PAGE(HID_USAGE_PAGE_DESKTOP),
        HID_USAGE(HID_USAGE_DESKTOP_X),
        HID_USAGE(HID_USAGE_DESKTOP_Y),
        HID_USAGE(HID_USAGE_DESKTOP_Z),
        HID_USAGE(HID_USAGE_DESKTOP_RX),
        HID_USAGE(HID_USAGE_DESKTOP_RY),
        HID_USAGE(HID_USAGE_DESKTOP_RZ),
        HID_USAGE(HID_USAGE_DESKTOP_SLIDER),
        HID_LOGICAL_MIN_N(-PROTOCOL_AXIS_MAX, 2),
        HID_LOGICAL_MAX_N(PROTOCOL_AXIS_MAX, 2),
        HID_REPORT_SIZE(16),
        HID_REPORT_COUNT(JOY_AXES),
        HID_INPUT(HID_DATA | HID_VARIABLE | HID_ABSOLUTE),

        HID_USAGE_PAGE(HID_USAGE_PAGE_BUTTON),
        HID_USAGE_MIN(1),
        HID_USAGE_MAX(32),
        HID_LOGICAL_MIN(0),
        HID_LOGICAL_MAX(1),
        HID_REPORT_SIZE(1),
        HID_REPORT_COUNT(32),
        HID_INPUT(HID_DATA | HID_VARIABLE | HID_ABSOLUTE),
    HID_COLLECTION_END,
};

TU_VERIFY_STATIC(sizeof(joystick_report_t) == 2 * JOY_AXES + 4, "joystick report layout");

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance) {
    return instance == HID_INST_JOYSTICK ? desc_hid_joystick : desc_hid_mouse;
}

//--------------------------------------------------------------------+
// Configuration descriptor: CDC (2 interfaces) + HID mouse/keyboard + HID joystick
//--------------------------------------------------------------------+

enum {
    ITF_NUM_CDC = 0,
    ITF_NUM_CDC_DATA,
    ITF_NUM_HID_MOUSE,
    ITF_NUM_HID_JOYSTICK,
    ITF_NUM_TOTAL,
};

#define EPNUM_CDC_NOTIF 0x81
#define EPNUM_CDC_OUT 0x02
#define EPNUM_CDC_IN 0x82
#define EPNUM_HID_MOUSE 0x83
#define EPNUM_HID_JOYSTICK 0x84

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + 2 * TUD_HID_DESC_LEN)

// HID polling interval in ms (full speed: 1 ms is the minimum).
#define HID_POLL_MS 1

static uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, STRID_CDC, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN,
                       CFG_TUD_CDC_EP_BUFSIZE),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_MOUSE, STRID_MOUSE, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_mouse),
                       EPNUM_HID_MOUSE, CFG_TUD_HID_EP_BUFSIZE, HID_POLL_MS),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_JOYSTICK, STRID_JOYSTICK, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_joystick),
                       EPNUM_HID_JOYSTICK, CFG_TUD_HID_EP_BUFSIZE, HID_POLL_MS),
};

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return desc_configuration;
}

//--------------------------------------------------------------------+
// String descriptors
//--------------------------------------------------------------------+

static char const *const string_desc_arr[STRID_COUNT] = {
    [STRID_MANUFACTURER] = "AI Crew",
    [STRID_PRODUCT] = "AI Crew Controller",
    [STRID_SERIAL] = NULL, // flash unique ID, filled at runtime
    [STRID_CDC] = "AI Crew Control Port",
    [STRID_MOUSE] = "AI Crew Mouse+Keyboard",
    [STRID_JOYSTICK] = "AI Crew Joystick",
};

#define MAX_STRING_CHARS 32

static uint16_t desc_str[MAX_STRING_CHARS + 1];
static char serial_str[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    size_t chr_count;

    if (index == STRID_LANGID) {
        desc_str[1] = 0x0409; // English (US)
        chr_count = 1;
    } else {
        if (index >= STRID_COUNT) {
            return NULL;
        }
        char const *str = string_desc_arr[index];
        if (index == STRID_SERIAL) {
            if (serial_str[0] == '\0') {
                pico_get_unique_board_id_string(serial_str, sizeof(serial_str));
            }
            str = serial_str;
        }
        chr_count = strlen(str);
        if (chr_count > MAX_STRING_CHARS) {
            chr_count = MAX_STRING_CHARS;
        }
        for (size_t i = 0; i < chr_count; i++) {
            desc_str[1 + i] = (uint16_t)str[i];
        }
    }

    desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * chr_count + 2));
    return desc_str;
}
