import asyncio, os, json, time
from dotenv import load_dotenv
from livekit import api

load_dotenv()

async def go():
    lk = None
    try:
        lk_url = os.environ['LIVEKIT_URL']
        lk_http = lk_url.replace('wss://', 'https://')
        lk_key = os.environ['LIVEKIT_API_KEY']
        lk_secret = os.environ['LIVEKIT_API_SECRET']

        lk = api.LiveKitAPI(
            url=lk_http,
            api_key=lk_key,
            api_secret=lk_secret
        )

        room = f'canon-{int(time.time()) % 100000}'

        # ✅ Generate token
        token = (
            api.AccessToken(api_key=lk_key, api_secret=lk_secret)
            .with_identity('caller')
            .with_name('Caller')
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish=True,
                    can_subscribe=True
                )
            )
            .to_jwt()
        )

        # ✅ Generate URL
        url = f'https://meet.livekit.io/custom?liveKitUrl={lk_url}&token={token}'

        # ✅ Print early (important)
        print(f'Room: {room}')
        print(f'\n🔥 JOIN URL:\n{url}\n')

        # ✅ Dispatch agent
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=os.environ.get('AGENT_NAME', 'optibot'),
                room=room,
                metadata=json.dumps({
                    'tenant_id': 'canonical-test',
                    'local_loopback': True,
                }),
            )
        )

        # ✅ Wait for agent
        for i in range(25):
            await asyncio.sleep(3)

            rooms = await lk.room.list_rooms(
                api.ListRoomsRequest(names=[room])
            )

            if rooms.rooms and rooms.rooms[0].num_participants > 0:
                print('Agent ready!')
                break

            print(f'waiting ({i*3}s)...')

    except asyncio.CancelledError:
        print("Task cancelled cleanly")
        raise

    except KeyboardInterrupt:
        print("Stopped by user")

    finally:
        if lk:
            await lk.aclose()
            print("LiveKit session closed ✅")


asyncio.run(go())