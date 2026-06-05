#!/usr/bin/env python

# Name:     midnite_classic.py
# Purpose:  Present BOTH a Hydro Generator and a Battery Monitor to VenusOS
#           using a SINGLE safe Modbus connection to prevent MidNite network lockups.
# Date:     06-05-2026
# Version:  3.0 (Unified Dual-DBus Architecture)
# Author:   Jan Bakuwel (Original) / Unified for Hydro & Grafana Telemetry
# License:  GNU General Public License v3.0

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import sys
import os
import time
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
import paho.mqtt.client

# VenusOS packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService
from logger import setup_logging

import config


def update_mqtt(broker, topic, soc, batt_v, shunt_a, batt_t, input_v, input_a, batt_p):
	mqtt_client = paho.mqtt.client.Client()
	if mqtt_client.connect(broker) == 0:
		try:
			mqtt_client.publish(topic + 'Battery/Voltage',     '{:0.2f}'.format(batt_v),          retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Battery/Current',     '{:0.2f}'.format(shunt_a),          retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Battery/Power',       '{:0.2f}'.format(batt_v * shunt_a), retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Battery/Temperature', '{:0.1f}'.format(batt_t),           retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Battery/SOC',         '{:d}'.format(soc),                 retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Turbine/Voltage',     '{:0.2f}'.format(input_v),          retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Turbine/Current',     '{:0.2f}'.format(input_a),          retain=True)
			time.sleep(0.1)
			mqtt_client.publish(topic + 'Turbine/Power',       '{:d}'.format(batt_p),              retain=True)
		except Exception as e:
			logger.info('update_mqtt[%s]: %s' % (topic, repr(e)))
		finally:
			mqtt_client.disconnect()


def twos_complement(value, bits):
	if (value & (1 << (bits - 1))) != 0:
		value = value - (1 << bits)
	return value


class MidniteClassic:

	def __init__(self, ip, frequency):
		self.ip        = ip
		self.frequency = frequency
		self.classic   = ModbusClient(self.ip, port=502)
		self.terminated = False

		logger.info('Initialising Unified Midnite thread: IP=%s, Freq=%d' % (self.ip, self.frequency))

		# =================================================================================
		# DEVICE 1: THE HYDRO TURBINE (Solar Charger Service)
		# =================================================================================
		self.charger = VeDbusService(servicename='com.victronenergy.solarcharger.midnite', register=False)
		self.charger.add_path('/DeviceInstance',         0)
		self.charger.add_path('/ProductName',            'Midnite Classic Hydro Turbine')
		self.charger.add_path('/Mgmt/ProcessName',       'midnite_classic.py')
		self.charger.add_path('/Mgmt/ProcessVersion',    config.VERSION)
		self.charger.add_path('/Mgmt/Connection',        'dbus')
		self.charger.add_path('/FirmwareVersion',        config.VERSION)
		self.charger.add_path('/HardwareVersion',        config.VERSION)
		self.charger.add_path('/State',                  None, writeable=True)

		# Standard Turbine Paths
		self.charger.add_path('/Pv/V',               None, writeable=True, gettextcallback=lambda a, x: '{:.0f}V'.format(x))
		self.charger.add_path('/Pv/I',               None, writeable=True, gettextcallback=lambda a, x: '{:.1f}A'.format(x))
		self.charger.add_path('/Pv/Power',           None, writeable=True, gettextcallback=lambda a, x: '{:.0f}W'.format(x))
		self.charger.add_path('/Yield/Power',        None, writeable=True, gettextcallback=lambda a, x: '{:.0f}W'.format(x))
		self.charger.add_path('/Dc/0/Voltage',       None, writeable=True, gettextcallback=lambda a, x: '{:.1f}V'.format(x))
		self.charger.add_path('/Dc/0/Current',       None, writeable=True, gettextcallback=lambda a, x: '{:.1f}A'.format(x))
		self.charger.add_path('/Yield/User',         None, writeable=True, gettextcallback=lambda a, x: '{:.1f}kWh'.format(x))

		# Extended Grafana Paths
		self.charger.add_path('/Yield/Lifetime',         None, writeable=True, gettextcallback=lambda a, x: '{:.0f}kWh'.format(x))
		self.charger.add_path('/Yield/AmpHours',         None, writeable=True, gettextcallback=lambda a, x: '{:.0f}Ah'.format(x))
		self.charger.add_path('/Temps/Battery',          None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.charger.add_path('/Temps/FET',              None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.charger.add_path('/Temps/PCB',              None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.charger.add_path('/Soc',                    None, writeable=True, gettextcallback=lambda a, x: '{:.0f}%'.format(x))
		self.charger.add_path('/Dc/0/ShuntCurrent',      None, writeable=True, gettextcallback=lambda a, x: '{:.1f}A'.format(x))
		self.charger.add_path('/WasteNot/Pwm',           None, writeable=True, gettextcallback=lambda a, x: '{:.0f}%'.format(x))
		self.charger.add_path('/Midnite/RawState',       None, writeable=True)
		self.charger.add_path('/Midnite/RestReasonCode', None, writeable=True)
		self.charger.add_path('/Alerts/OverTemperature', None, writeable=True)
		self.charger.add_path('/Alerts/CurrentLimit',    None, writeable=True)
		self.charger.add_path('/Connected',              1)
		self.charger.register()

		# =================================================================================
		# DEVICE 2: THE BATTERY MONITOR (WhizBang Jr Service)
		# =================================================================================
		self.battery = VeDbusService(servicename='com.victronenergy.battery.midnite', register=False)
		self.battery.add_path('/DeviceInstance',         0)
		self.battery.add_path('/ProductName',            'Midnite Classic Battery Monitor')
		self.battery.add_path('/Mgmt/ProcessName',       'midnite_classic.py')
		self.battery.add_path('/Mgmt/ProcessVersion',    config.VERSION)
		self.battery.add_path('/Mgmt/Connection',        'dbus')
		self.battery.add_path('/FirmwareVersion',        config.VERSION)
		self.battery.add_path('/HardwareVersion',        config.VERSION)

		# Core Battery Paths
		self.battery.add_path('/Soc',                    None, writeable=True, gettextcallback=lambda a, x: '{:d}%'.format(x))
		self.battery.add_path('/Dc/0/Voltage',           None, writeable=True, gettextcallback=lambda a, x: '{:.2f}V'.format(x))
		self.battery.add_path('/Dc/0/Current',           None, writeable=True, gettextcallback=lambda a, x: '{:.2f}A'.format(x))
		self.battery.add_path('/Dc/0/Power',             None, writeable=True, gettextcallback=lambda a, x: '{:.0f}W'.format(x))
		self.battery.add_path('/Dc/0/Temperature',       None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.battery.add_path('/Temps/FET',              None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.battery.add_path('/Temps/PCB',              None, writeable=True, gettextcallback=lambda a, x: '{:.1f}C'.format(x))
		self.battery.add_path('/Yield/User',             None, writeable=True, gettextcallback=lambda a, x: '{:.1f}kWh'.format(x))
		self.battery.add_path('/Yield/Lifetime',         None, writeable=True, gettextcallback=lambda a, x: '{:.0f}kWh'.format(x))
		self.battery.add_path('/Yield/AmpHours',         None, writeable=True, gettextcallback=lambda a, x: '{:.0f}Ah'.format(x))
		self.battery.add_path('/WasteNot/Pwm',           None, writeable=True, gettextcallback=lambda a, x: '{:.0f}%'.format(x))
		self.battery.add_path('/Midnite/RawState',       None, writeable=True)
		self.battery.add_path('/Midnite/RestReasonCode', None, writeable=True)
		self.battery.add_path('/Alerts/OverTemperature', None, writeable=True)
		self.battery.add_path('/Alerts/CurrentLimit',    None, writeable=True)
		self.battery.add_path('/Connected',              1)
		self.battery.register()

	def read_modbus(self):
		try:
			if self.classic.connect():
				# ONE safe connection pulls all data
				hr41 = self.classic.read_holding_registers(4100, 100)
				hr42 = self.classic.read_holding_registers(4200, 100)
				hr43 = self.classic.read_holding_registers(4300, 100)
				self.classic.close()

				self.charger['/Connected'] = 1
				self.battery['/Connected'] = 1

				soc          = hr43.registers[72]
				input_v      = float(hr41.registers[15]) / 10
				input_a      = float(hr41.registers[20]) / 10
				input_p      = round(input_v * input_a)
				batt_v       = float(hr41.registers[14]) / 10
				batt_a       = float(hr41.registers[16]) / 10
				batt_p       = hr41.registers[18]
				batt_t       = float(hr41.registers[31]) / 10
				fet_t        = float(hr41.registers[32]) / 10
				pcb_t        = float(hr41.registers[33]) / 10
				charge_state = (hr41.registers[19] & 0xFF00) >> 8
				midnite_state = (hr41.registers[19] & 0x00FF)
				shunt_a      = float(twos_complement(hr43.registers[70], 16)) / 10
				daily_kwh    = float(hr41.registers[17]) / 10
				daily_ah     = hr41.registers[24]
				pwm_percent  = (hr41.registers[40] / 1023.0) * 100
				lifetime_kwh = (hr41.registers[26] << 16) + hr41.registers[25]
				rest_reason  = hr42.registers[74]
				info_flags   = (hr41.registers[30] << 16) + hr41.registers[29]
				over_temp    = 1 if (info_flags & 0x00000001) else 0
				current_limit = 1 if (info_flags & 0x00000200) else 0

				# Update Device 1: The Hydro Turbine
				self.charger['/State']                  = config.MIDNITE_VICTRON[charge_state]
				self.charger['/Pv/V']                   = input_v
				self.charger['/Pv/I']                   = input_a
				self.charger['/Pv/Power']               = input_p
				self.charger['/Yield/Power']            = batt_p
				self.charger['/Yield/User']             = daily_kwh
				self.charger['/Dc/0/Voltage']           = batt_v
				self.charger['/Dc/0/Current']           = batt_a
				self.charger['/Yield/Lifetime']         = lifetime_kwh
				self.charger['/Yield/AmpHours']         = daily_ah
				self.charger['/Temps/Battery']          = batt_t
				self.charger['/Temps/FET']              = fet_t
				self.charger['/Temps/PCB']              = pcb_t
				self.charger['/Soc']                    = soc
				self.charger['/Dc/0/ShuntCurrent']      = shunt_a
				self.charger['/WasteNot/Pwm']           = pwm_percent
				self.charger['/Midnite/RawState']       = midnite_state
				self.charger['/Midnite/RestReasonCode'] = rest_reason
				self.charger['/Alerts/OverTemperature'] = over_temp
				self.charger['/Alerts/CurrentLimit']    = current_limit

				# Update Device 2: The Battery Monitor
				self.battery['/Soc']                    = soc
				self.battery['/Dc/0/Voltage']           = batt_v
				self.battery['/Dc/0/Current']           = shunt_a
				self.battery['/Dc/0/Power']             = round(batt_v * shunt_a)
				self.battery['/Dc/0/Temperature']       = batt_t
				self.battery['/Temps/FET']              = fet_t
				self.battery['/Temps/PCB']              = pcb_t
				self.battery['/Yield/User']             = daily_kwh
				self.battery['/Yield/Lifetime']         = lifetime_kwh
				self.battery['/Yield/AmpHours']         = daily_ah
				self.battery['/WasteNot/Pwm']           = pwm_percent
				self.battery['/Midnite/RawState']       = midnite_state
				self.battery['/Midnite/RestReasonCode'] = rest_reason
				self.battery['/Alerts/OverTemperature'] = over_temp
				self.battery['/Alerts/CurrentLimit']    = current_limit

				if config.MQTT_ENABLED:
					update_mqtt(
						config.MQTT_IP, config.MQTT_PREFIX + '/',
						soc, batt_v, shunt_a, batt_t, input_v, input_a, batt_p,
					)
			else:
				logger.info('Unable to connect to %s' % self.ip)
				self.charger['/Connected'] = 0
				self.battery['/Connected'] = 0

		except Exception as e:
			logger.info('Exception updating values: ' + repr(e))
			self.charger['/Connected'] = 0
			self.battery['/Connected'] = 0
		return True

	def run(self):
		self._timer = GLib.timeout_add(self.frequency * 1000, self.read_modbus)

	def cancel(self):
		GLib.remove_source(self._timer)
		self.terminated = True


logger = setup_logging(debug=False)
DBusGMainLoop(set_as_default=True)
t = MidniteClassic(config.MIDNITE_IP, config.MIDNITE_INTERVAL)
t.run()
logger.info('Connected to dbus, and switching over to GLib.MainLoop() (= event based)')
mainloop = GLib.MainLoop()
mainloop.run()
