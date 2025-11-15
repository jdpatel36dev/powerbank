from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


try:  # pragma: no cover - hardware dependency
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover
    logger.warning("RPi.GPIO not available; using mock mode")

    class MockGPIO:
        BCM = 11
        BOARD = 10
        OUT = 0
        LOW = 0
        HIGH = 1

        def setmode(self, *_args, **_kwargs):
            logger.info("GPIO mock: setmode")

        def setup(self, *_args, **_kwargs):
            logger.info("GPIO mock: setup")

        def output(self, *_args, **_kwargs):
            logger.info("GPIO mock: output %s %s", _args, _kwargs)

        def cleanup(self):
            logger.info("GPIO mock: cleanup")

    GPIO = MockGPIO()  # type: ignore


@dataclass
class HardwareConfig:
    relay_pin: int = 17
    active_high: bool = False
    allow_overlap: bool = False


class ChargeController:
    def __init__(self, hardware: HardwareConfig):
        self._hardware = hardware
        self._lock = threading.Lock()
        self._active_session: threading.Timer | None = None
        self._active_reference: str | None = None

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._hardware.relay_pin, GPIO.OUT, initial=self._inactive_state)

    @property
    def _active_state(self):
        return GPIO.HIGH if self._hardware.active_high else GPIO.LOW

    @property
    def _inactive_state(self):
        return GPIO.LOW if self._hardware.active_high else GPIO.HIGH

    def _switch_on(self):
        GPIO.output(self._hardware.relay_pin, self._active_state)
        logger.info("Relay ON")

    def _switch_off(self):
        GPIO.output(self._hardware.relay_pin, self._inactive_state)
        logger.info("Relay OFF")

    def start_session(self, duration_minutes: int, reference: str) -> None:
        with self._lock:
            if self._active_session and not self._hardware.allow_overlap:
                logger.warning(
                    "Charge already in progress (ref=%s); ignoring new request %s",
                    self._active_reference,
                    reference,
                )
                return

            self._cancel_locked()
            self._switch_on()
            self._active_reference = reference

            duration_seconds = max(duration_minutes * 60, 1)
            timer = threading.Timer(duration_seconds, self._stop_session)
            self._active_session = timer
            timer.start()
            logger.info("Charging started for %s minutes (ref=%s)", duration_minutes, reference)

    def _stop_session(self):
        with self._lock:
            self._switch_off()
            ref = self._active_reference
            self._active_session = None
            self._active_reference = None
        logger.info("Charging session completed (ref=%s)", ref)

    def _cancel_locked(self):
        if self._active_session:
            self._active_session.cancel()
            self._active_session = None
            self._active_reference = None
            self._switch_off()

    def cleanup(self):
        with self._lock:
            if self._active_session:
                self._active_session.cancel()
            self._switch_off()
        GPIO.cleanup()


class MQTTChargeListener:
    def __init__(
        self,
        *,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        topic_prefix: str = "powerbank",
        device_id: str = "bay-1",
        hardware: HardwareConfig | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self._topic = f"{topic_prefix}/charges/{device_id}"
        self._controller = ChargeController(hardware or HardwareConfig())
        self._client = mqtt.Client()
        if username:
            self._client.username_pw_set(username=username, password=password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._host = broker_host
        self._port = broker_port

    def _on_connect(self, client, _userdata, _flags, rc):  # pragma: no cover - callback
        if rc == 0:
            logger.info("Connected to MQTT broker, subscribing to %s", self._topic)
            client.subscribe(self._topic, qos=1)
        else:
            logger.error("MQTT connection failed with code %s", rc)

    def _parse_payload(self, payload: bytes) -> Dict[str, Any]:
        try:
            message = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

        if message.get("command") != "start_charge":
            raise ValueError(f"Unsupported command: {message.get('command')}")

        duration = int(message.get("duration_minutes", 0))
        reference = str(message.get("payment_reference", "unknown"))

        if duration <= 0:
            raise ValueError("Duration must be > 0")

        return {"duration": duration, "reference": reference}

    def _on_message(self, _client, _userdata, msg):  # pragma: no cover - callback
        try:
            data = self._parse_payload(msg.payload)
        except ValueError as exc:
            logger.error("Malformed MQTT message: %s", exc)
            return

        self._controller.start_session(data["duration"], data["reference"])

    def run_forever(self):
        logger.info("Connecting to MQTT broker %s:%s", self._host, self._port)
        self._client.connect(self._host, self._port, keepalive=60)
        try:
            self._client.loop_forever()
        finally:
            logger.info("Cleaning up GPIO")
            self._controller.cleanup()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    listener = MQTTChargeListener()
    try:
        listener.run_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        time.sleep(0.2)  # allow logs to flush


if __name__ == "__main__":
    main()


