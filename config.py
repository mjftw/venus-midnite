#!/usr/bin/env python

# Name:     config.py
# Purpose:  Configuration details Midnite Classic (Hydro/Grafana Setup)
# Date:     06-05-2026
# Version:  2.6

VERSION             = "v2.6"

# The static IP assigned to the MidNite Classic on the direct Ethernet link
MIDNITE_IP          = "192.168.100.10"
MIDNITE_INTERVAL    = 5

# Translation matrix: MidNite State Codes -> Victron DBus State Codes
MIDNITE_VICTRON = {
	0:  0,  # Midnite Resting:      Victron Off
	3:  4,  # Midnite Absorb:       Victron Absorption
	4:  3,  # Midnite BulkMPPT:     Victron Bulk
	5:  5,  # Midnite Float:        Victron Float
	6:  5,  # Midnite FloatMPPT:    Victron Float
	7:  7,  # Midnite Equalize:     Victron Equalize
	10: 3,  # HyperVOC:             Victron Bulk
	18: 7,  # EqualizeMPPT:         Victron Equalize
}

# Disabled. Relying on Venus OS native Mosquitto broker for Grafana ingestion.
MQTT_ENABLED        = False
MQTT_IP             = "192.168.1.101"
MQTT_PREFIX         = "classic"