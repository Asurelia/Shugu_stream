# Scene Editor — WebSocket `/ws/editor` (Phase D)

## Overview

Realtime collaboration endpoint for the Unity-style Scene Editor. Multiple
operators can be simultaneously subscribed to a scene; gestures (avatar
drag, FOV slider, camera moves) broadcast as ephemeral deltas without
touching the database. Permanent commits still go through the CRUD API
(`POST /api/scene-editor/scenes/{id}/drafts`).

## Architecture

```
┌──────────────────┐                   ┌──────────────────┐
│  Operator A WS   │                   │  Operator B WS   │
│ (alice)          │                   │ (bob)            │
└────────┬─────────┘                   └────────┬─────────┘
         │                                      │
         │ subscribe(scene-123)                 │ subscribe(scene-123)
         │ draft.update(delta)                  │
         │                                      │
         ▼                                      ▼
     ┌───────────────────────────────────────────┐
     │       /ws/editor handler (FastAPI)        │
     │       - auth via cookie shugu_access      │
     │       - per-connection state + heartbeat  │
     └────────────────┬──────────────────────────┘
                      │ publish / subscribe
                      ▼
              ┌───────────────────┐
              │ RedisEventBus     │ topic: "editor:broadcast"
              │ (cross-worker)    │ envelope: {scene_id, origin, payload}
              └──────┬────────────┘
                     │
          ┌──────────┴──────────┐
          │ filter by scene_id  │
          │ filter by self-echo │
          │ (connection_id)     │
          └──────────┬──────────┘
                     ▼
                back to peers
```

For visitors: `preview.push` also re-emits as `scene.preview` on the
existing `stage` topic, so the current `ShuguClient` (visitor WS) picks it
up without any change.

## Event contract v1

### Envelope

All messages are JSON UTF-8 text frames. Every message has a `type`
discriminator; unknown types reply with an `error` event.

### Client → Server

| Type            | Fields                                                          | Notes                                                              |
| --------------- | --------------------------------------------------------------- | ------------------------------------------------------------------ |
| `subscribe`     | `scene_id: string`                                              | Replace any previous subscription. One WS = one scene at a time.   |
| `unsubscribe`   | —                                                               | Optional. `close()` also triggers `peer.left`.                     |
| `draft.update`  | `scene_id: string`, `delta: object`, `nonce: string`            | Not persisted. Broadcast to peers minus origin.                    |
| `preview.push`  | `scene_id: string`, `payload: object`                           | Broadcast to peers + relay on `stage` topic as `scene.preview`.    |
| `ping`          | `nonce: string`                                                 | Application-level keepalive. Server replies `pong` with same nonce.|
| `pong`          | —                                                               | Reply to server heartbeat ping (see Heartbeat section below).      |

### Server → Client

| Type            | Fields                                                             | Notes                                               |
| --------------- | ------------------------------------------------------------------ | --------------------------------------------------- |
| `hello`         | `operator: string`, `protocol_version: number`                     | Sent immediately after `accept()`.                  |
| `subscribed`    | `scene_id: string`, `peers: string[]`                              | ACK. `peers` excludes self.                         |
| `unsubscribed`  | —                                                                  | ACK for `unsubscribe`.                              |
| `peer.joined`   | `scene_id: string`, `operator: string`                             | A new operator joined your scene.                   |
| `peer.left`     | `scene_id: string`, `operator: string`                             | Operator unsubscribed OR disconnected.              |
| `draft.update`  | `scene_id`, `delta`, `origin: string`, `nonce`                     | Relayed from another operator.                      |
| `preview.push`  | `scene_id`, `payload`, `origin`                                    | Relayed from another operator.                      |
| `ping`          | `t: number`                                                        | Server heartbeat. Client must reply `pong` or close. |
| `pong`          | `nonce`                                                            | Reply to client `ping`.                             |
| `error`         | `code`, `message`                                                  | Error discriminated by `code`.                      |

### Error codes

| Code              | Cause                                                    |
| ----------------- | -------------------------------------------------------- |
| `invalid_payload` | Malformed JSON / unknown type / missing required field.  |
| `not_subscribed`  | `draft.update` / `preview.push` without prior subscribe. |
| `unauthorized`    | Reserved — currently auth happens pre-accept (close 4401). |

## Auth

Same as `/ws/operator`:

1. Cookie `shugu_access` (HS256 JWT, role=`operator`) — preferred.
2. Query fallback `?token=...` for browsers that strip cookies on upgrade.

No auth / invalid / revoked → `close(code=4401, reason="no token" | "auth: ...")`
**before** accepting the socket. Browsers can inspect `event.code` on the
close event to redirect to login.

## Heartbeat

Bidirectional, **asymmetric** semantics:

- **Server → Client** (enforced): every 20s the server sends
  `{type: "ping", t: <monotonic>}`. The client **must** reply with
  `{type: "pong"}` within 40s cumulative or the server closes with
  `code=1011 reason="heartbeat timeout"`.
- **Client → Server** (optional): any client can send `{type: "ping", nonce: "..."}`
  at any time; the server replies `{type: "pong", nonce: "..."}` immediately.
  Does not participate in the watchdog — purely a latency probe.

The frontend `EditorWebSocket` handles server pings automatically (sends
pong without waking the consumer). The `onEvent` callback still observes
the `ping` so apps can surface a latency indicator.

## Peer registry (per-worker)

The in-process `_peer_registry: dict[scene_id, set[operator]]` is
**per-worker** and not strictly consistent across uvicorn workers. The
initial `subscribed.peers` list reflects only what the subscribing worker
sees; however, `peer.joined`/`peer.left` events go through the Redis bus
so UIs converge in a few hundred ms. Phase E may introduce a Redis-backed
membership set if deterministic initial peer lists become necessary.

## Bus topic

A **single** topic `editor:broadcast` carries all scenes. Envelopes on
the bus look like:

```json
{
  "scene_id": "uuid",
  "origin": "alice",
  "connection_id": "hex-uuid",
  "payload": { "type": "draft.update", "scene_id": "uuid", "delta": {...}, ... }
}
```

Subscribers filter by `scene_id` and drop self-echoes by matching
`connection_id`. This avoids the need to enumerate per-scene topics
upfront in `RedisEventBus.broadcast_topics` (which is a `frozenset` fixed
at construction time).

## What is **not** in this PR

Explicitly deferred to Phase E/F:

- **lock / unlock** — per-node editing lock (prevent concurrent avatar
  drag conflicts).
- **timeline.transport** — play / pause / seek sync across operators.
- **pattern.record** — "macro" mode where one operator's gestures are
  captured into a reusable pattern.
- **bidirectional live-sync** — the current frontend hook is
  receive-only. Sending deltas from operator gestures will be Phase F
  once the provenance tracking (local-vs-remote) is added to the Zustand
  store.

## Test coverage

- `backend/tests/unit/test_editor_ws.py` — 16 tests (TestClient WebSocket,
  InProcessEventBus).
- `backend/tests/integration/test_editor_ws.py` — 3 tests (2 apps sharing
  a `fakeredis.FakeServer`, validates cross-instance fanout).
- `frontend/src/lib/__tests__/editorWebSocket.test.ts` — 13 tests (mocked
  `WebSocket` ctor, connect/subscribe/reconnect/heartbeat).
- `frontend/src/stores/__tests__/useSceneEditorStore.test.ts` — 6 new
  tests for Phase D peers + remoteDraftDeltas actions.
- `frontend/e2e/scene-editor-multi-operator.spec.ts` — Playwright multi-
  tab smoke test, gracefully skips if backend is unreachable.
