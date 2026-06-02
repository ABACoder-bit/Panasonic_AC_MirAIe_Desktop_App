import asyncio

asyncio.set_event_loop_policy(
    asyncio.WindowsSelectorEventLoopPolicy()
)

from miraie_ac import MirAIeHub, MirAIeBroker
from miraie_ac.enums import ConvertiMode


PHONE = "+91XXXXXXXXXX"
PASSWORD = "XXXXXXXXXXX"


async def wait_for_client(broker, timeout=30):

    for i in range(timeout):

        if hasattr(broker, "client"):
            print(f"MQTT connected after {i} seconds")
            return True

        print(f"Waiting for MQTT connection... {i+1}")
        await asyncio.sleep(1)

    return False


async def main():

    broker = MirAIeBroker()
    hub = MirAIeHub()

    await hub.init(
        PHONE,
        PASSWORD,
        broker
    )

    connected = await wait_for_client(broker)

    if not connected:
        print("MQTT never connected")
        return

    device = hub.home.devices[0]

    print("Sending C55 command")

    await device.set_converti_mode(
        ConvertiMode.C40
    )

    print("Command sent")

    await asyncio.sleep(10)


asyncio.run(main())