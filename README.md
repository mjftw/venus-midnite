# venus-midnite

Integrates a **MidNite Classic charge controller** (with WhizBang Jr shunt) into **Victron VenusOS** as two first-class devices:

- **Hydro Turbine** (`com.victronenergy.solarcharger`) — shows turbine input, charge state, daily yield, and extended telemetry in VRM and on the CCGX screen.
- **Battery Monitor** (`com.victronenergy.battery`) — shows state of charge, net shunt current (signed, so charge and discharge), temperature, and thermals.

Both devices are driven by a **single Modbus TCP connection** per poll cycle. This is important: the MidNite Classic has a fragile network stack that can lock up if two processes connect simultaneously.

---

## Installation

### Requirements

- VenusOS device with SSH access
- MidNite Classic reachable on the network from VenusOS
- WhizBang Jr shunt fitted and enabled in the Classic

### Quick install

Edit `config.py` with your MidNite's IP address, then run:

```bash
./install.sh <cerbo-ip>
```

The script copies files, sets up the runit service, and reboots the Cerbo. Done.

### Manual install

### 1. Copy files to VenusOS

```bash
scp -r venus-midnite/ root@<venus-ip>:/data/midnite
```

Or clone directly on the device:

```bash
ssh root@<venus-ip>
git clone https://github.com/youruser/venus-midnite /data/midnite
```

### 2. Edit config.py

```bash
nano /data/midnite/config.py
```

```python
MIDNITE_IP       = "192.168.x.x"   # Static IP of your MidNite Classic
MIDNITE_INTERVAL = 5               # Poll interval in seconds
```

### 3. Make scripts executable

```bash
chmod +x /data/midnite/midnite_classic.sh
chmod +x /data/midnite/service/run
chmod +x /data/midnite/service/log/run
```

### 4. Register the service

```bash
cat /data/midnite/rcS.local >> /data/rcS.local
```

This creates the log directory and symlinks the runit service so VenusOS starts it on every boot.

### 5. Reboot

```bash
reboot
```

The MidNite Classic will appear in VRM and on the CCGX/GX Touch screen as both a solar charger and a battery monitor.

### Verifying it works

```bash
svstat /service/midnite                                              # service running?
tail -f /var/log/midnite/current                                     # live log
dbus -y com.victronenergy.solarcharger.midnite /ProductName GetValue # charger on dbus?
dbus -y com.victronenergy.battery.midnite /ProductName GetValue      # battery on dbus?
```

### Uninstalling

```bash
svc -d /service/midnite   # stop service
rm /service/midnite
rm -rf /data/midnite
```

Remove the lines added to `/data/rcS.local` and reboot.

---

## Hardware

- MidNite Classic charge controller (any model)
- WhizBang Jr battery shunt (required for accurate SOC and signed current)
- VenusOS device (Cerbo GX, Raspberry Pi, etc.)
- Direct Ethernet link or local network connection to the Classic

## Files

```
venus-midnite/
├── install.sh          # Installs onto a Cerbo GX over SSH and reboots
├── midnite_classic.py    # Main script — registers both D-Bus services
├── midnite_classic.sh    # Shell wrapper called by the runit service
├── config.py           # IP address, poll interval, state code mappings
├── service/
│   ├── run             # runit service definition
│   └── log/
│       └── run         # runit log definition (writes to /var/log/midnite)
└── rcS.local           # Snippet to append to /data/rcS.local on VenusOS
```

## Telemetry paths published

### Hydro Turbine (`solarcharger`)

| Path                          | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `/Pv/V`, `/Pv/I`, `/Pv/Power` | Raw turbine input voltage, current, power           |
| `/Dc/0/Voltage`, `/Dc/0/Current` | Battery voltage and charge current               |
| `/Yield/Power`                | Actual power delivered to battery bank              |
| `/Yield/User`                 | Daily kWh (resets at midnight)                      |
| `/Yield/Lifetime`             | Lifetime kWh                                        |
| `/Yield/AmpHours`             | Daily Ah                                            |
| `/State`                      | Victron charge state (Bulk / Absorb / Float…)       |
| `/Temps/Battery`              | Battery temperature (external sensor)               |
| `/Temps/FET`                  | MidNite FET temperature                             |
| `/Temps/PCB`                  | MidNite PCB temperature                             |
| `/Soc`                        | State of charge %                                   |
| `/Dc/0/ShuntCurrent`          | Net shunt current (negative = discharging)          |
| `/WasteNot/Pwm`               | AUX2 PWM duty cycle — power dumped to thermal store |
| `/Midnite/RawState`           | Raw MidNite state code                              |
| `/Midnite/RestReasonCode`     | Why the controller is resting                       |
| `/Alerts/OverTemperature`     | Hardware alert flag                                 |
| `/Alerts/CurrentLimit`        | Hardware alert flag                                 |

### Battery Monitor (`battery`)

All paths from the charger service are also mirrored here so Grafana dashboards
can query either service without breakage.

| Path                      | Description                                 |
|---------------------------|---------------------------------------------|
| `/Soc`                    | State of charge %                           |
| `/Dc/0/Voltage`           | Battery voltage                             |
| `/Dc/0/Current`           | Net shunt current (negative = discharging)  |
| `/Dc/0/Power`             | Net battery power                           |
| `/Dc/0/Temperature`       | Battery temperature (external sensor)       |
| `/Temps/FET`              | MidNite FET temperature                     |
| `/Temps/PCB`              | MidNite PCB temperature                     |
| `/Yield/User`             | Daily kWh (resets at midnight)              |
| `/Yield/Lifetime`         | Lifetime kWh                                |
| `/Yield/AmpHours`         | Daily Ah                                    |
| `/WasteNot/Pwm`           | AUX2 PWM duty cycle                         |
| `/Midnite/RawState`       | Raw MidNite state code                      |
| `/Midnite/RestReasonCode` | Why the controller is resting               |
| `/Alerts/OverTemperature` | Hardware alert flag                         |
| `/Alerts/CurrentLimit`    | Hardware alert flag                         |
