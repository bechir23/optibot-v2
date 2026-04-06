# Localhost Real-Time Voice Runbook (No Phone Dial)

This runbook tests inbound and outbound behavior in real time without dialing any external phone number.

## 1) Start worker and verify health

```powershell
& .\.venv\Scripts\Activate.ps1
$py="C:\Users\bechi\AppData\Local\Programs\Python\Python312\python.exe"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## 2) Localhost outbound session (no SIP dial)

```powershell
& .\.venv\Scripts\Activate.ps1
$py="C:\Users\bechi\AppData\Local\Programs\Python\Python312\python.exe"
& $py scripts/test_live_call.py --localhost-mode outbound --agent-name optibot --tenant demo-local --monitor-seconds 240
```

The command prints a room join command. Open it in another terminal:

```powershell
$lk="$env:USERPROFILE\bin\livekit-cli\lk.exe"
& $lk room join <ROOM_NAME_FROM_DISPATCH> --identity local-tester --open meet
```

## 3) Localhost inbound session (no SIP dial)

```powershell
& .\.venv\Scripts\Activate.ps1
$py="C:\Users\bechi\AppData\Local\Programs\Python\Python312\python.exe"
& $py scripts/test_live_call.py --localhost-mode inbound --agent-name optibot --tenant demo-inbound --monitor-seconds 240
```

Join using the printed room command the same way as outbound.

## 4) Localhost IVR navigation simulation (no SIP dial)

This forces the IVR navigator in outbound loopback mode so you can validate navigation logic in real time.

```powershell
& .\.venv\Scripts\Activate.ps1
$py="C:\Users\bechi\AppData\Local\Programs\Python\Python312\python.exe"
& $py scripts/test_live_call.py --localhost-mode outbound --force-ivr --ivr-path 1,3 --target-service "remboursements optiques" --agent-name optibot --tenant demo-ivr --monitor-seconds 240
```

## 5) TwiML localhost audio flow (optional, Twilio path)

If you explicitly want Twilio callback + audio playback tests:

```powershell
& .\.venv\Scripts\Activate.ps1
$py="C:\Users\bechi\AppData\Local\Programs\Python\Python312\python.exe"
$env:PUBLIC_BASE_URL="https://<your-ngrok-domain>"
$env:TWIML_ENABLE_PLAY="1"
$env:TWIML_AUDIO_FILE="test_audio.wav"
& $py scripts/localhost_twiml_server.py --port 8088
```

Important checks:
- `PUBLIC_BASE_URL` must exactly match the active `https://...` ngrok URL.
- Twilio cannot fetch `http://` localhost URLs directly.

## 6) Real-time conversation script (speak this live)

Use this script while connected in the room.

### Scenario A: normal reimbursement follow-up

1. Human: "Bonjour, service remboursements, je vous ecoute."
2. Agent should identify and ask status.
3. Human: "Je retrouve le dossier, il est en cours de traitement."
4. Agent should ask delay and possibly reference.
5. Human: "Le delai est de dix jours ouvres, reference RBT-78412."
6. Agent should confirm and close politely.

Expected:
- Agent asks one question at a time.
- Agent extracts delay and reference before ending.

### Scenario B: hold music / wait handling

1. Human: "Un instant, je verifie le dossier."
2. Human (or playback): "Veuillez patienter, votre appel est important."
3. Wait 8-12 seconds.
4. Human: "Merci d avoir patiente, je reprends votre dossier."

Expected:
- During hold phrases, agent remains silent.
- Agent resumes only when human-like phrase returns.

### Scenario C: IVR navigation simulation (with --force-ivr)

1. Human: "Bienvenue. Tapez 1 pour les remboursements, 2 pour les devis."
2. Agent should choose digit according to path.
3. Human: "Tapez 3 pour le tiers payant optique."
4. Agent should continue navigation and then hand off on human answer.
5. Human: "Bonjour, conseillere remboursements."

Expected:
- IVR tool actions happen before conversational handoff.
- Once human answers, agent switches to reimbursement conversation.

## 7) Evidence to collect after each run

- Dispatch id and room name from tester output.
- Participant counts over time from room monitor lines.
- Worker logs from:

```powershell
$lk="$env:USERPROFILE\bin\livekit-cli\lk.exe"
& $lk agent logs --id CA_wxpZPdSc5Ebu
```

- For TwiML path, callback events:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/twilio/last | ConvertTo-Json -Depth 8
```
