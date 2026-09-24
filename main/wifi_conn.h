#pragma once

// Connect to the configured Wi-Fi network as a station. Blocks until an IP
// address is obtained; retries indefinitely on disconnect.
void wifi_conn_start(void);
