# ProxyProof

ProxyProof is a mobile-first Bluetooth attendance MVP. Organisers open timed sessions; students are marked present when the server accepts a fresh rotating token, their approved device identity, and a nearby RSSI reading. Organisers can correct marks, close sessions, review attendance, and export CSV. Students can review their attendance history and percentage.

## Run locally

Requires Python 3.10 or newer. No third-party packages are needed.

```sh
python app.py
```

Open [http://localhost:8000](http://localhost:8000). The database is created as `proxyproof.sqlite3` in the project directory on first run.

### Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Organiser | `organizer@proxyproof.app` | `organizer123` |
| Student | `maya@proxyproof.app` | `student123` |
| Student | `arjun@proxyproof.app` | `student123` |
| Student | `leah@proxyproof.app` | `student123` |

Seeded accounts have approved demo device IDs. In a real deployment, replace these credentials, configure TLS, and use a secure device enrolment process.

## What is implemented

- Separate organiser and student dashboards with session-based login.
- Timed sessions with 5-second HMAC-derived rotating tokens.
- Server-side attendance checks for session state, token freshness, account role, approved device, duplicate device marks, and RSSI threshold.
- Automatic session expiry, live dashboard refresh, and organiser add/remove controls.
- Device change requests and organiser approval/rejection.
- Student attendance history and percentage; organiser CSV export.
- Responsive interface and a proximity simulator for local demonstrations.

## BLE integration boundary

The web app provides the authenticated `/api/proximity` check and the organiser dashboard exposes the current beacon payload for a companion beacon client. Browser BLE support varies, and standard Web Bluetooth does not provide a portable API for a web page to advertise rotating manufacturer data. The included **Simulate nearby device** action exercises the real server checks with a demo RSSI value; it does not claim to scan or advertise radio signals. To deploy in a classroom, add a native Android/iOS BLE adapter that advertises the session payload from the organiser device and scans/submits it from student devices. Treat device IDs and RSSI as signals, not cryptographic proof of a person's identity or exact location.

## API overview

- `POST /api/login`, `POST /api/logout`, `GET /api/me`
- `GET /api/dashboard`, `GET /api/history`
- `POST /api/sessions`, `POST /api/sessions/{id}/close`
- `POST /api/sessions/{id}/attendance` (organiser manual correction)
- `POST /api/proximity` (student device proximity mark)
- `POST /api/device/request`, `GET /api/devices`, `POST /api/devices/{student_id}`
- `GET /api/export.csv`

This is a local MVP, not a production-ready identity or anti-spoofing system. Production use should add TLS, rate limiting, account provisioning, durable secret management, audit logging, stronger device attestation, and native BLE integration.
