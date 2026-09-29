cmake_minimum_required(VERSION 3.13)

# Third-party Type-C boards that match the reference Pico 2 W use pico2_w.
# Override with -DPICO_BOARD=pico2 for a board without the wireless chip.
set(PICO_BOARD pico2_w CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(ai_crew_fw C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

add_executable(ai_crew_fw
    main.c
    usb_descriptors.c
    protocol.c
)

# tusb_config.h lives next to the sources.
target_include_directories(ai_crew_fw PRIVATE ${CMAKE_CURRENT_LIST_DIR})

target_compile_definitions(ai_crew_fw PRIVATE FW_BOARD="${PICO_BOARD}")
target_compile_options(ai_crew_fw PRIVATE -Wall -Wextra)

target_link_libraries(ai_crew_fw PRIVATE
    pico_stdlib
    pico_unique_id
    pico_bootrom
    tinyusb_device
)

# USB is owned by our own TinyUSB descriptors, not stdio.
pico_enable_stdio_usb(ai_crew_fw 0)
pico_enable_stdio_uart(ai_crew_fw 0)

pico_add_extra_outputs(ai_crew_fw)
