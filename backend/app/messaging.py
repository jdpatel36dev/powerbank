from __future__ import annotations

import json
import logging
import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


@dataclass
class ChargeCommand:
    device_id: str
    duration_minutes: int
    payment_reference: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "command": "start_charge",
            "device_id": self.device_id,
            "duration_minutes": self.duration_minutes,
            "payment_reference": self.payment_reference,
        }


class ChargePublisher:
    """Thin wrapper around paho-mqtt for publishing charge commands."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        topic_prefix: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._topic_prefix = topic_prefix.rstrip("/")
        self._client = mqtt.Client()
        if username:
            self._client.username_pw_set(username, password=password or "")

        self._host = host
        self._port = port
        self._lock = threading.Lock()

    def connect(self) -> None:
        with self._lock:
            if self._client.is_connected():
                return
            logger.info("Connecting to MQTT broker %s:%s", self._host, self._port)
            self._client.connect(self._host, self._port, keepalive=60)
            self._client.loop_start()

    def disconnect(self) -> None:
        with self._lock:
            if not self._client.is_connected():
                return
            logger.info("Disconnecting from MQTT broker")
            with suppress(Exception):
                self._client.loop_stop()
                self._client.disconnect()

    def publish_charge(self, command: ChargeCommand) -> None:
        payload = json.dumps(command.to_payload())
        topic = f"{self._topic_prefix}/charges/{command.device_id}"
        logger.info(
            "Publishing charge command to %s (duration=%s)", topic, command.duration_minutes
        )
        result = self._client.publish(topic, payload, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Failed to publish MQTT message: {result.rc}")



