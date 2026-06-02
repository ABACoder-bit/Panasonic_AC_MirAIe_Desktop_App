import ssl
import certifi
import asyncio
from aiomqtt import Client, MqttError
from miraie_ac import MirAIeBroker
from logging_manager import get_logger

logger = get_logger("mqtt_manager")

class CustomBroker(MirAIeBroker):
    """
    Subclasses the library's MirAIeBroker to add hooks for tracking MQTT connection status,
    allowing the UI and notification engine to react to connection state changes.
    """
    def __init__(self, on_state_change=None):
        super().__init__()
        self.on_state_change = on_state_change
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def on_connect(self):
        self._connected = True
        logger.info("MQTT Broker connection successfully established.")
        if self.on_state_change:
            self.on_state_change(True)
        # Continue with subscription logic of parent broker
        await super().on_connect()

    async def connect(self, username: str, access_token, get_token):
        password = access_token
        context = None

        if self.use_ssl:
            context = ssl.create_default_context(cafile=certifi.where())

        while True:
            try:
                # If we entered this loop, we are trying to connect
                logger.info("Attempting to connect to MirAIe MQTT broker at %s:%d...", self.host, self.port)
                
                async with Client(
                    hostname=self.host,
                    port=self.port,
                    username=username,
                    password=password,
                    tls_context=context,
                ) as client:
                    self.client = client
                    await self.on_connect()
                    
                    # Process messages as they arrive
                    async for message in client.messages:
                        self.on_message(message)

            except MqttError as error:
                self._handle_disconnect()
                logger.error("MQTT Error: '%s'. Reconnecting in %d seconds.", error, self.reconnect_interval)
                try:
                    password = await get_token()
                except Exception as token_err:
                    logger.error("Failed to retrieve new access token: %s", token_err)
                await asyncio.sleep(self.reconnect_interval)
                
            except Exception as e:
                self._handle_disconnect()
                logger.error("Unexpected broker error: %s. Reconnecting in %d seconds.", e, self.reconnect_interval)
                await asyncio.sleep(self.reconnect_interval)

    def _handle_disconnect(self):
        if self._connected:
            self._connected = False
            logger.warning("MQTT Broker connection lost.")
            if self.on_state_change:
                self.on_state_change(False)
