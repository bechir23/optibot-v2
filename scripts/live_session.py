"""Production-like live session: ngrok tunnel + LiveKit room + real audio.

Creates a LiveKit room, dispatches the agent, starts ngrok tunnel,
and provides a web URL where you can talk to the agent in real time
through your browser microphone — exactly like a production call.

Also exposes webhook endpoints for Twilio callbacks if needed.

Usage:
    python scripts/live_session.py                          # outbound scenario
    python scripts/live_session.py --scenario hold           # hold test
    python scripts/live_session.py --scenario ivr            # IVR navigation
    python scripts/live_session.py --scenario inbound        # inbound receptionist
    python scripts/live_session.py --concurrent 3            # 3 rooms simultaneously
    python scripts/live_session.py --tunnel                  # start ngrok tunnel for Twilio
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
load_dotenv()

SCENARIOS = {
    "outbound": {
        "description": "Standard outbound mutuelle reimbursement call",
        "metadata": {
            "tenant_id": "live-outbound",
            "local_loopback": True,
            "dossier": {
                "mutuelle": "Harmonie Mutuelle",
                "patient_name": "Jean Dupont",
                "patient_dob": "15/03/1985",
                "dossier_ref": "BRD-LIVE-001",
                "montant": 779.91,
                "nir": "1850375012345",
                "dossier_type": "optique",
            },
        },
    },
    "hold": {
        "description": "Test hold detection and resume behavior",
        "metadata": {
            "tenant_id": "live-hold",
            "local_loopback": True,
            "dossier": {
                "mutuelle": "MGEN",
                "patient_name": "Marie Martin",
                "dossier_ref": "BRD-LIVE-HOLD",
                "montant": 250.0,
                "dossier_type": "optique",
            },
        },
    },
    "ivr": {
        "description": "IVR menu navigation simulation",
        "metadata": {
            "tenant_id": "live-ivr",
            "local_loopback": True,
            "dossier": {
                "mutuelle": "AXA",
                "patient_name": "Pierre Bernard",
                "dossier_ref": "BRD-LIVE-IVR",
                "montant": 500.0,
                "dossier_type": "optique",
            },
        },
    },
    "inbound": {
        "description": "Inbound receptionist (agent speaks first)",
        "metadata": {
            "tenant_id": "live-inbound",
        },
    },
}

# Minimal web page for voice testing
HTML = """<!DOCTYPE html>
<html><head><title>OptiBot Live Session</title>
<style>
body{font-family:system-ui;max-width:900px;margin:40px auto;padding:20px;background:#111;color:#eee}
h1{color:#e94560}h2{color:#0f9}
.box{background:#1a1a2e;padding:15px;border-radius:8px;margin:10px 0}
button{background:#e94560;color:#fff;border:none;padding:12px 24px;font-size:16px;border-radius:8px;cursor:pointer;margin:5px}
button:hover{background:#c81d4e}
.status{font-size:1.2em;padding:10px;border-radius:8px;margin:10px 0}
.on{background:#1b998b}.off{background:#333}
#log{background:#0a0a1a;padding:10px;border-radius:8px;height:300px;overflow-y:auto;font-family:monospace;font-size:12px}
</style></head><body>
<h1>OptiBot Live Session</h1>
<div class="box"><strong>Room:</strong> ROOM_NAME<br><strong>Scenario:</strong> SCENARIO_DESC</div>
<div class="status off" id="status">Click Connect to start</div>
<div>
<button onclick="connect()">Connect & Talk</button>
<button onclick="disconnect()">Disconnect</button>
<button onclick="toggleMute()">Mute/Unmute</button>
</div>
<h2>Instructions</h2>
<div class="box">
INSTRUCTIONS
</div>
<h2>Live Event Log</h2>
<div id="log"></div>
<script src="https://unpkg.com/livekit-client/dist/livekit-client.umd.js"></script>
<script>
const T='JOIN_TOKEN',U='WS_URL';let room,muted=false;
function log(m){const e=document.getElementById('log');e.innerHTML+=new Date().toLocaleTimeString()+' '+m+'\\n';e.scrollTop=e.scrollHeight}
async function connect(){
try{log('Connecting...');room=new LivekitClient.Room();
room.on('participantConnected',p=>log('+ '+p.identity));
room.on('participantDisconnected',p=>log('- '+p.identity));
room.on('trackSubscribed',(t,p,part)=>{log('Track: '+t.kind+' from '+part.identity);if(t.kind==='audio'){const e=t.attach();document.body.appendChild(e);log('Agent audio playing')}});
room.on('transcriptionReceived',(segs,part)=>{segs.forEach(s=>{if(s.text)log('['+part.identity+'] '+s.text)})});
room.on('disconnected',()=>{log('Disconnected');document.getElementById('status').className='status off';document.getElementById('status').textContent='Disconnected'});
await room.connect(U,T);log('Connected: '+room.name);
document.getElementById('status').className='status on';document.getElementById('status').textContent='LIVE - Speak now!';
await room.localParticipant.setMicrophoneEnabled(true);log('Microphone ON')
}catch(e){log('ERROR: '+e.message)}}
function disconnect(){if(room){room.disconnect();log('Disconnecting...')}}
function toggleMute(){if(room){muted=!muted;room.localParticipant.setMicrophoneEnabled(!muted);log(muted?'MUTED':'UNMUTED')}}
</script></body></html>"""


async def create_session(scenario_name: str, agent_name: str):
    """Create room, dispatch agent, generate token, return (room_name, token, ws_url)."""
    from livekit import api

    lk_url = os.environ["LIVEKIT_URL"]
    lk_http = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    lk_key = os.environ["LIVEKIT_API_KEY"]
    lk_secret = os.environ["LIVEKIT_API_SECRET"]

    config = SCENARIOS[scenario_name]
    room_name = f"live-{scenario_name}-{int(time.time()) % 100000}"

    lk = api.LiveKitAPI(url=lk_http, api_key=lk_key, api_secret=lk_secret)

    # Dispatch agent
    dispatch = await lk.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata=json.dumps(config["metadata"]),
        )
    )

    # Generate join token
    token = (
        api.AccessToken(api_key=lk_key, api_secret=lk_secret)
        .with_identity(f"user-{int(time.time()) % 10000}")
        .with_name("Live Tester")
        .with_grants(api.VideoGrants(
            room_join=True, room=room_name, can_publish=True, can_subscribe=True,
        ))
        .to_jwt()
    )

    await lk.aclose()
    return room_name, token, lk_url, dispatch.id


def build_instructions(scenario_name: str) -> str:
    instructions = {
        "outbound": (
            "You are the mutuelle agent. The OptiBot agent will call you about a reimbursement.<br>"
            "1. Say 'Bonjour, Harmonie Mutuelle, service remboursements'<br>"
            "2. When asked for patient, say 'C'est pour quel patient?'<br>"
            "3. Give status: 'Le remboursement est en cours, comptez 15 jours'<br>"
            "4. Ask 'Autre chose?' to let agent end"
        ),
        "hold": (
            "Test hold detection:<br>"
            "1. Greet normally<br>"
            "2. Say 'Veuillez patienter un instant' — agent should go SILENT<br>"
            "3. Wait 5-10 seconds in silence<br>"
            "4. Say 'Désolé pour l'attente, je reprends' — agent should resume<br>"
            "5. Give info: 'Le dossier est traité, le virement part demain'"
        ),
        "ivr": (
            "Pretend to be an IVR menu:<br>"
            "1. Say 'Bienvenue chez AXA. Pour les remboursements, tapez 1. Pour les adhésions, tapez 2.'<br>"
            "2. Then say 'Service remboursements optique. Toutes nos lignes sont occupées.'<br>"
            "3. Then switch to human: 'Bonjour, service remboursement AXA, je vous écoute.'"
        ),
        "inbound": (
            "The agent will speak first (receptionist mode).<br>"
            "1. Wait for agent greeting<br>"
            "2. Say 'Bonjour, je voudrais des renseignements sur un remboursement de lunettes'<br>"
            "3. Provide details when asked"
        ),
    }
    return instructions.get(scenario_name, "Follow the agent's lead.")


async def run_live(scenario: str, agent_name: str, use_tunnel: bool, port: int):
    config = SCENARIOS[scenario]

    print(f"\n{'='*60}")
    print(f"LIVE SESSION: {scenario}")
    print(f"Description: {config['description']}")
    print(f"{'='*60}\n")

    # Create room + dispatch agent + token
    room_name, token, ws_url, dispatch_id = await create_session(scenario, agent_name)
    print(f"  Room: {room_name}")
    print(f"  Dispatch: {dispatch_id}")

    # Build HTML
    instructions = build_instructions(scenario)
    html = (HTML
            .replace("ROOM_NAME", room_name)
            .replace("SCENARIO_DESC", config["description"])
            .replace("INSTRUCTIONS", instructions)
            .replace("JOIN_TOKEN", token)
            .replace("WS_URL", ws_url))

    # Start local HTTP server
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
        def log_message(self, *a): pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    local_url = f"http://localhost:{port}"
    public_url = local_url

    # Start ngrok tunnel if requested
    if use_tunnel:
        try:
            from pyngrok import ngrok
            tunnel = ngrok.connect(port, "http")
            public_url = tunnel.public_url
            print(f"\n  NGROK TUNNEL: {public_url}")
            print(f"  Share this URL for remote testing!")
        except Exception as e:
            print(f"\n  ngrok failed: {e}")
            print(f"  Using local URL only")

    print(f"\n  LOCAL URL: {local_url}")
    print(f"\n  Open in browser, click 'Connect & Talk', speak in French.")
    print(f"  The agent will hear you and respond through your speakers.")

    # Also print lk CLI join command
    print(f"\n  Alternative: lk room join {room_name} --identity tester --open meet")

    print(f"\n  Press Ctrl+C to stop.\n")

    # Monitor room
    from livekit import api as lkapi
    lk = lkapi.LiveKitAPI(
        url=ws_url.replace("wss://", "https://"),
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    try:
        last = -1
        while True:
            try:
                rooms = await lk.room.list_rooms(lkapi.ListRoomsRequest(names=[room_name]))
                if rooms.rooms:
                    r = rooms.rooms[0]
                    if r.num_participants != last:
                        print(f"  [{time.strftime('%H:%M:%S')}] Participants: {r.num_participants}")
                        last = r.num_participants
                elif last > 0:
                    print(f"  Room closed.")
                    break
            except Exception:
                pass
            await asyncio.sleep(3)
    except KeyboardInterrupt:
        print("\n  Stopping...")
    finally:
        await lk.aclose()
        server.shutdown()
        if use_tunnel:
            try:
                from pyngrok import ngrok
                ngrok.kill()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Production-like live voice session")
    parser.add_argument("--scenario", default="outbound", choices=list(SCENARIOS.keys()))
    parser.add_argument("--agent-name", default=os.environ.get("AGENT_NAME", "optibot"))
    parser.add_argument("--tunnel", action="store_true", help="Start ngrok tunnel")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--concurrent", type=int, default=0)
    args = parser.parse_args()

    if args.concurrent > 0:
        # Run multiple scenarios on different ports
        async def multi():
            tasks = []
            scenarios = list(SCENARIOS.keys())[:args.concurrent]
            for i, s in enumerate(scenarios):
                tasks.append(run_live(s, args.agent_name, args.tunnel and i == 0, args.port + i))
            await asyncio.gather(*tasks)
        asyncio.run(multi())
    else:
        asyncio.run(run_live(args.scenario, args.agent_name, args.tunnel, args.port))


if __name__ == "__main__":
    main()
