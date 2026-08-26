"""Constants for the 2N Intercom integration."""

DOMAIN = "SL"
SL_MANUFACTURER = "Steinway Lyngdorf"
SL_TITLE = "Steinway Lyngdorf Processor"
SL_EVENT = "SL_processor_event"

SL_CONNECT_TIMEOUT = 20
SL_LOGIN_TIMEOUT = 5
SL_ZEROCONF_TIMEOUT = 5
SL_PORT = 84

# Reconnect / liveness handling.
SL_RECONNECT_DELAY = 5  # first retry after a dropped connection (s)
SL_RECONNECT_DELAY_MAX = 300  # backoff ceiling (s)
SL_KEEPALIVE_INTERVAL = 60  # probe an idle link this often (s)
SL_KEEPALIVE_TIMEOUT = 10  # a probe must be answered within this (s)
SL_WRITE_TIMEOUT = 10  # drain() must complete within this (s)
