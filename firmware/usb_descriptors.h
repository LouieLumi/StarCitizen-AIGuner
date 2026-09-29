#ifndef USB_DESCRIPTORS_H
#define USB_DESCRIPTORS_H

#include <stdint.h>

#include "tusb.h"

#include "protocol.h"

// Hobbyist test VID (TinyUSB examples use 0xCafe); not a real vendor's ID.
#define USB_VID 0xCAFE
#define USB_PID 0x4143

// HID instances, in configuration-descriptor order.
enum {
    HID_INST_MOUSE = 0,
    HID_INST_JOYSTICK = 1,
};

// The mouse interface carries the keyboard too, told apart by report ID.
enum {
    REPORT_ID_MOUSE = 1,
    REPORT_ID_KEYBOARD = 2,
};

// Joystick input report (no report ID): 7 axes then 32 buttons.
typedef struct TU_ATTR_PACKED {
    int16_t axes[JOY_AXES]; // X, Y, Z, Rx, Ry, Rz, Slider; -32767..32767
    uint32_t buttons;       // bit0 = button 1
} joystick_report_t;

#endif
