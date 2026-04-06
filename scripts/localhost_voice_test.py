"""Localhost voice test — talk to the agent from your browser, no phone needed.

Creates a LiveKit room, dispatches the agent, generates a join token,
and opens a web page where you speak through your microphone.

The agent hears you, responds in French, and you have a real conversation.

Usage:
    python scripts/localhost_voice_test.py                          # basic conversation
    python scripts/localhost_voice_test.py --scenario hold          # test hold detection
    python scripts/localhost_voice_test.py --scenario ivr           # test IVR navigation
    python scripts/localhost_voice_test.py --scenario inbound       # test inbound greeting
    python scripts/localhost_voice_test.py --concurrent 3           # 3 rooms simultaneously
    python scripts/localhost_voice_test.py --web                    # open browser automatically
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

from dotenv import load_dotenv
load_dotenv()


CONVERSATION_SCRIPTS = {
    "outbound": {
        "description": "Standard outbound reimbursement call",
        "agent_metadata": {
            "tenant_id": "localhost_test",
            "dossier": {
                "mutuelle": "Harmonie Mutuelle",
                "patient_name": "Jean Dupont",
                "patient_dob": "15/03/1985",
                "dossier_ref": "BRD-TEST-0001",
                "montant": 779.91,
                "nir": "1850375012345",
                "dossier_type": "optique",
            },
        },
        "script": [
            "YOU: 'Bonjour, Harmonie Mutuelle, service remboursements.'",
            "AGENT: Should identify itself and ask about a dossier.",
            "YOU: 'C'est pour quel patient?'",
            "AGENT: Should provide patient name (Jean Dupont).",
            "YOU: 'Oui je vois. Le remboursement est en cours, comptez 15 jours.'",
            "AGENT: Should acknowledge and ask for details.",
            "YOU: 'Autre chose?'",
            "AGENT: Should thank and end call.",
        ],
    },
    "hold": {
        "description": "Test hold detection and resume",
        "agent_metadata": {
            "tenant_id": "localhost_hold_test",
            "dossier": {
                "mutuelle": "MGEN",
                "patient_name": "Marie Martin",
                "dossier_ref": "BRD-HOLD-0001",
                "montant": 250.00,
                "dossier_type": "optique",
            },
        },
        "script": [
            "YOU: 'Bonjour, MGEN.'",
            "AGENT: Should greet and explain purpose.",
            "YOU: 'Veuillez patienter un instant.'",
            "AGENT: Should detect HOLD and go silent.",
            "YOU: (wait 5 seconds in silence)",
            "YOU: 'Desole pour l'attente, je reprends.'",
            "AGENT: Should resume conversation.",
            "YOU: 'Le dossier est traite.'",
            "AGENT: Should acknowledge.",
        ],
    },
    "ivr": {
        "description": "Test IVR menu navigation (simulated)",
        "agent_metadata": {
            "tenant_id": "localhost_ivr_test",
            "dossier": {
                "mutuelle": "AXA",
                "patient_name": "Pierre Bernard",
                "dossier_ref": "BRD-IVR-0001",
                "montant": 500.00,
                "dossier_type": "optique",
            },
        },
        "script": [
            "YOU: 'Bienvenue chez AXA. Pour les remboursements, tapez 1. Pour les adhesions, tapez 2.'",
            "AGENT: Should press 1 (DTMF) or say 'un'.",
            "YOU: 'Service remboursements. Pour l'optique, tapez 3.'",
            "AGENT: Should press 3.",
            "YOU: 'Un instant, je vous transfere a un conseiller.'",
            "YOU: 'Bonjour, service optique AXA.'",
            "AGENT: Should now switch to conversation mode.",
        ],
    },
    "inbound": {
        "description": "Test inbound receptionist greeting",
        "agent_metadata": {
            "tenant_id": "localhost_inbound_test",
        },
        "script": [
            "YOU: (just join — agent speaks first)",
            "AGENT: Should greet you in French as receptionist.",
            "YOU: 'Bonjour, je voudrais des renseignements sur mes lunettes.'",
            "AGENT: Should help and ask questions.",
        ],
    },
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<title>OptiBot Voice Test</title>
<style>
body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background: #1a1a2e; color: #eee; }
h1 { color: #e94560; }
.info { background: #16213e; padding: 15px; border-radius: 8px; margin: 10px 0; }
.script { background: #0f3460; padding: 15px; border-radius: 8px; white-space: pre-line; line-height: 1.8; }
.status { font-size: 1.2em; padding: 10px; border-radius: 8px; margin: 10px 0; }
.connected { background: #1b998b; }
.connecting { background: #e94560; }
button { background: #e94560; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 8px; cursor: pointer; margin: 5px; }
button:hover { background: #c81d4e; }
#log { background: #0a0a1a; padding: 10px; border-radius: 8px; height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; }
</style>
</head>
<body>
<h1>OptiBot Localhost Voice Test</h1>
<div class="info">
<strong>Scenario:</strong> SCENARIO_NAME<br>
<strong>Room:</strong> ROOM_NAME<br>
<strong>Description:</strong> SCENARIO_DESC
</div>
<div class="status connecting" id="status">Connecting...</div>
<div>
<button onclick="connect()">Connect & Start Talking</button>
<button onclick="disconnect()">Disconnect</button>
<button onclick="toggleMute()">Mute/Unmute</button>
</div>
<h3>Conversation Script:</h3>
<div class="script">SCRIPT_LINES</div>
<h3>Event Log:</h3>
<div id="log"></div>

<script src="https://unpkg.com/livekit-client/dist/livekit-client.umd.js"></script>
<script>
const TOKEN = 'JOIN_TOKEN';
const WS_URL = 'WS_URL';
let room = null;
let muted = false;

function log(msg) {
    const el = document.getElementById('log');
    el.innerHTML += new Date().toLocaleTimeString() + ' ' + msg + '\\n';
    el.scrollTop = el.scrollHeight;
}

async function connect() {
    try {
        log('Connecting to LiveKit...');
        room = new LivekitClient.Room();

        room.on('participantConnected', (p) => log('Participant joined: ' + p.identity));
        room.on('participantDisconnected', (p) => log('Participant left: ' + p.identity));
        room.on('trackSubscribed', (track) => {
            log('Track subscribed: ' + track.kind);
            if (track.kind === 'audio') {
                const el = track.attach();
                document.body.appendChild(el);
                log('Audio playing from agent');
            }
        });
        room.on('disconnected', () => {
            log('Disconnected');
            document.getElementById('status').className = 'status connecting';
            document.getElementById('status').textContent = 'Disconnected';
        });

        await room.connect(WS_URL, TOKEN);
        log('Connected to room: ' + room.name);
        document.getElementById('status').className = 'status connected';
        document.getElementById('status').textContent = 'Connected - Speak now!';

        await room.localParticipant.setMicrophoneEnabled(true);
        log('Microphone enabled - speak in French');
    } catch (e) {
        log('Error: ' + e.message);
    }
}

function disconnect() {
    if (room) { room.disconnect(); log('Disconnecting...'); }
}

function toggleMute() {
    if (room) {
        muted = !muted;
        room.localParticipant.setMicrophoneEnabled(!muted);
        log(muted ? 'Muted' : 'Unmuted');
    }
}
</script>
</body>
</html>"""


async def create_room_and_token(room_name: str, agent_name: str, metadata: dict):
    """Create room, dispatch agent, generate join token."""
    from livekit import api

    lk_url = os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace("ws://", "http://")
    lk = api.LiveKitAPI(
        url=lk_url,
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    # Dispatch agent to room
    dispatch = await lk.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata=json.dumps(metadata),
        )
    )
    print(f"  Agent dispatched: {dispatch.id} -> {room_name}")

    # Generate participant token
    token = (
        api.AccessToken(
            api_key=os.environ["LIVEKIT_API_KEY"],
            api_secret=os.environ["LIVEKIT_API_SECRET"],
        )
        .with_identity(f"tester-{int(time.time()) % 10000}")
        .with_name("Voice Tester")
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ))
        .to_jwt()
    )

    await lk.aclose()
    return token


async def monitor_room_events(room_name: str, duration: int = 120):
    """Monitor room for participant and call events."""
    from livekit import api

    lk = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"].replace("wss://", "https://"),
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    start = time.monotonic()
    last_count = -1
    while (time.monotonic() - start) < duration:
        try:
            rooms = await lk.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
            if rooms.rooms:
                r = rooms.rooms[0]
                if r.num_participants != last_count:
                    print(f"  [{time.monotonic()-start:.0f}s] Room {r.name}: {r.num_participants} participants")
                    last_count = r.num_participants
                if r.num_participants == 0 and (time.monotonic() - start) > 10:
                    print("  Room empty — test complete")
                    break
            elif (time.monotonic() - start) > 5:
                print("  Room closed — test complete")
                break
        except Exception:
            pass
        await asyncio.sleep(2)

    await lk.aclose()


def serve_html(html: str, port: int = 8089):
    """Serve the test HTML page on localhost."""
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(html.encode())
        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def run_test(scenario: str, agent_name: str, open_browser: bool, monitor_sec: int):
    config = CONVERSATION_SCRIPTS.get(scenario)
    if not config:
        print(f"Unknown scenario: {scenario}. Available: {list(CONVERSATION_SCRIPTS.keys())}")
        return

    room_name = f"localhost-{scenario}-{int(time.time()) % 100000}"
    ws_url = os.environ["LIVEKIT_URL"]

    print(f"\n{'='*60}")
    print(f"LOCALHOST VOICE TEST: {scenario}")
    print(f"{'='*60}")
    print(f"  Description: {config['description']}")
    print(f"  Room: {room_name}")
    print()

    # Create room + dispatch agent + get token
    token = await create_room_and_token(room_name, agent_name, config["agent_metadata"])

    # Build HTML
    script_lines = "\n".join(config["script"])
    html = (HTML_TEMPLATE
            .replace("SCENARIO_NAME", scenario)
            .replace("ROOM_NAME", room_name)
            .replace("SCENARIO_DESC", config["description"])
            .replace("SCRIPT_LINES", script_lines)
            .replace("JOIN_TOKEN", token)
            .replace("WS_URL", ws_url))

    # Serve HTML
    port = 8089
    serve_html(html, port)
    url = f"http://localhost:{port}"

    print(f"  Open in browser: {url}")
    print(f"  Click 'Connect & Start Talking', then follow the script.")
    print()
    print("  CONVERSATION SCRIPT:")
    for line in config["script"]:
        print(f"    {line}")
    print()

    if open_browser:
        webbrowser.open(url)

    # Monitor room
    print("  Monitoring room events...")
    await monitor_room_events(room_name, monitor_sec)


async def run_concurrent(count: int, agent_name: str, open_browser: bool, monitor_sec: int):
    scenarios = list(CONVERSATION_SCRIPTS.keys())[:count]
    print(f"\n{'='*60}")
    print(f"CONCURRENT LOCALHOST TEST: {count} rooms")
    print(f"{'='*60}")

    tasks = []
    for i, scenario in enumerate(scenarios):
        tasks.append(run_test(scenario, agent_name, open_browser and i == 0, monitor_sec))

    await asyncio.gather(*tasks)


def main():
    parser = argparse.ArgumentParser(description="Localhost voice test — no phone needed")
    parser.add_argument("--scenario", default="outbound", choices=list(CONVERSATION_SCRIPTS.keys()),
                        help="Test scenario")
    parser.add_argument("--agent-name", default="optibot", help="Agent name")
    parser.add_argument("--web", action="store_true", help="Auto-open browser")
    parser.add_argument("--concurrent", type=int, default=0, help="Run N scenarios concurrently")
    parser.add_argument("--monitor-seconds", type=int, default=120, help="How long to monitor")
    args = parser.parse_args()

    if args.concurrent > 0:
        asyncio.run(run_concurrent(args.concurrent, args.agent_name, args.web, args.monitor_seconds))
    else:
        asyncio.run(run_test(args.scenario, args.agent_name, args.web, args.monitor_seconds))


if __name__ == "__main__":
    main()
