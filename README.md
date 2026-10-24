# rpi_surveillance
Surveillance app for Raspberry pi and Hailo AI Kit

![Logo](rpi_surveillance/assets/logo.png)

# Camera Setup

```bash
sudo apt update && sudo apt upgrade
sudo apt install libcap-dev libatlas-base-dev ffmpeg libopenjp2-7
sudo apt install libcamera-dev
sudo apt install libkms++-dev libfmt-dev libdrm-dev
```

```bash
pip install --upgrade pip
pip install wheel
pip install rpi-libcamera rpi-kms picamera2
```

# Install Hailo SDK

```bash

```



# Gatekeeper

The gatekeeper watches the running camera, and when a person or an animal is
detected it starts recording (saved to the recordings directory) and sends a
Telegram alert with an annotated snapshot. The snapshot is the middle frame of
the first `GATEKEEPER_SNAPSHOT_DELAY_SECONDS` of the event, so the object is
well in view rather than just entering the frame. Recording stops once nothing
has been seen for `GATEKEEPER_HOLD_SECONDS`. Arm it with the **Gatekeeper**
button on the **Live** tab (this also turns on AI detection in the live view),
or via `/api/gatekeeper/start`, `/api/gatekeeper/stop` and `/api/gatekeeper/status`.

Configure it in `.env`:

```bash
# Telegram: create a bot with @BotFather, send it a message, then read your chat id
# from https://api.telegram.org/bot<token>/getUpdates
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789          # comma-separated for several chats

# Optional tuning (defaults shown)
GATEKEEPER_CLASSES=human,animal     # groups "human"/"animal" or any COCO label, e.g. car
GATEKEEPER_MIN_SCORE=0.5
GATEKEEPER_FPS=2                    # detection rate
GATEKEEPER_HOLD_SECONDS=10          # keep recording this long after the last detection
GATEKEEPER_MAX_RECORDING_SECONDS=300
GATEKEEPER_NOTIFY_COOLDOWN_SECONDS=60
GATEKEEPER_SNAPSHOT_DELAY_SECONDS=3   # alert snapshot = middle frame of this window
```

Without Telegram credentials the gatekeeper still records, it just doesn't alert.
