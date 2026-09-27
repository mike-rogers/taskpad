idf_component_register(SRCS "main.c"
                            "wifi_conn.c"
                            "taskpad_mqtt.c"
                            "device_cfg.c"
                            "adopt_server.c"
                            "improv_ble.c"
                            "ota_update.c"
                            "ui.c"
                            "input.c"
                       PRIV_REQUIRES esp_wifi
                                     nvs_flash
                                     esp_http_server
                                     bt
                                     esp_https_ota
                                     app_update
                                     esp_lcd
                                     esp_driver_spi
                                     esp_driver_gpio
                                     esp_netif
                                     lwip
                       INCLUDE_DIRS ".")
