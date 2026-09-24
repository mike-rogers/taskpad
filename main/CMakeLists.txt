idf_component_register(SRCS "main.c"
                            "wifi_conn.c"
                            "taskpad_mqtt.c"
                            "ui.c"
                            "input.c"
                       PRIV_REQUIRES esp_wifi
                                     nvs_flash
                                     esp_lcd
                                     esp_driver_spi
                                     esp_driver_gpio
                                     esp_netif
                                     lwip
                       INCLUDE_DIRS ".")
