idf_component_register(
    SRCS "main.c" "ui.c" "io.c" "link_usb.c" "link_uart.c"
    INCLUDE_DIRS "."
    REQUIRES core esp_driver_gpio esp_driver_uart esp_driver_i2c esp_timer
)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
