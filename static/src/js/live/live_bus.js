/**
 * Live realtime games — shared bus client.
 *
 * Wraps Odoo's websocket bus service and the /live_game JSON API into a
 * small game-agnostic client used by both the host console and student
 * player pages:
 *
 *   const client = await createLiveGameClient({ sessionId });
 *   client.on("lg_progress", (payload) => ...);
 *   await client.join("ABCDE");          // students
 *   await client.hostAction("start");    // teacher
 *
 * The client keeps a merged snapshot of the session state, transparently
 * reconnects (websocket + heartbeat fallback) and re-emits bus events.
 */

import { makeEnv, startServices } from "@web/env";

const HEARTBEAT_INTERVAL_MS = 10000;
const RECONNECT_DELAY_MS = 3000;

/** JSON-RPC style POST to one of our /live_game endpoints. */
async function rpc(endpoint, params) {
    const response = await fetch(`/live_game/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            jsonrpc: "2.0",
            params,
            id: Math.floor(Math.random() * 1e9),
        }),
        credentials: "same-origin",
    });
    const data = await response.json();
    if (data.error) {
        // Odoo wraps UserError/AccessError in error.data
        const err = new Error(data.error.data?.message || data.error.message || "Server error");
        err.name = data.error.data?.name || "RpcError";
        throw err;
    }
    return data.result;
}

export class LiveGameClient {
    constructor({ sessionId = null } = {}) {
        this.sessionId = sessionId;
        this.snapshot = null;
        this.listeners = new Map(); // notification type -> Set<callback>
        this.heartbeatTimer = null;
        this.reconnectTimer = null;
        this.stopped = false;
        this.busService = null;
        this._envPromise = null;
    }

    /**
     * Lazily boot a minimal Odoo env with all services (including the
     * websocket bus service) started.  Standalone pages have no web client,
     * so we create the env ourselves.
     */
    async _getEnv() {
        if (!this._envPromise) {
            this._envPromise = (async () => {
                const env = await makeEnv();
                await startServices(env);
                return env;
            })();
        }
        return this._envPromise;
    }

    // ------------------------------------------------------------------
    // Event handling
    // ------------------------------------------------------------------
    on(notificationType, callback) {
        if (!this.listeners.has(notificationType)) {
            this.listeners.set(notificationType, new Set());
        }
        this.listeners.get(notificationType).add(callback);
        return () => this.off(notificationType, callback);
    }

    off(notificationType, callback) {
        this.listeners.get(notificationType)?.delete(callback);
    }

    _emit(type, payload) {
        for (const callback of this.listeners.get(type) || []) {
            try {
                callback(payload);
            } catch (error) {
                console.error(`live_game handler for ${type} failed`, error);
            }
        }
        // Convenience: also emit "*" for logging/debug UIs.
        for (const callback of this.listeners.get("*") || []) {
            callback({ type, payload });
        }
    }

    // ------------------------------------------------------------------
    // Snapshot helpers
    // ------------------------------------------------------------------
    get me() {
        return this.snapshot?.me || null;
    }

    get participants() {
        return this.snapshot?.participants || [];
    }

    get state() {
        return this.snapshot?.state || null;
    }

    /** Merge an incoming snapshot; returns true when something changed. */
    _mergeSnapshot(snapshot) {
        if (!snapshot) {
            return false;
        }
        const changed =
            !this.snapshot ||
            this.snapshot.state !== snapshot.state ||
            JSON.stringify(this.snapshot.participants) !== JSON.stringify(snapshot.participants);
        this.snapshot = snapshot;
        if (snapshot.session_id && !this.sessionId) {
            this.sessionId = snapshot.session_id;
        }
        return changed;
    }

    _applySnapshot(snapshot, { silent = false } = {}) {
        const changed = this._mergeSnapshot(snapshot);
        if (!silent) {
            this._emit("lg_snapshot", snapshot);
            if (changed) {
                this._emit("lg_state", { state: snapshot.state });
            }
        }
    }

    // ------------------------------------------------------------------
    // Connection lifecycle
    // ------------------------------------------------------------------
    async _subscribeBus() {
        const channel = this.snapshot?.bus_channel;
        if (!channel || this.busService) {
            return;
        }
        const env = await this._getEnv();
        this.busService = env.services.bus;
        if (!this.busService) {
            console.warn("live_game: bus service unavailable, falling back to heartbeat only");
            return;
        }
        this.busService.addChannel(channel);
        for (const type of ["lg_state", "lg_progress"]) {
            this.busService.subscribe(type, (payload) => {
                if (payload?.session_id !== this.snapshot?.session_id) {
                    return;
                }
                if (type === "lg_progress") {
                    this._applyProgress(payload);
                } else {
                    this._applyBusState(payload);
                }
                this._emit(type, payload);
            });
        }
    }

    _applyProgress(payload) {
        if (!this.snapshot || !payload.participant) {
            return;
        }
        const participants = [...(this.snapshot.participants || [])];
        const index = participants.findIndex((p) => p.id === payload.participant.id);
        if (index >= 0) {
            participants[index] = { ...participants[index], ...payload.participant };
        } else {
            participants.push(payload.participant);
        }
        this.snapshot = { ...this.snapshot, participants };
    }

    _applyBusState(payload) {
        if (!this.snapshot) {
            return;
        }
        this.snapshot = {
            ...this.snapshot,
            state: payload.state,
            access_code: payload.access_code ?? this.snapshot.access_code,
        };
    }

    async _startHeartbeat() {
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = setInterval(async () => {
            if (this.stopped || !this.sessionId) {
                return;
            }
            try {
                const result = await rpc("heartbeat", { session_id: this.sessionId });
                this._applySnapshot(result.snapshot);
            } catch {
                // Network hiccup — the next tick will retry.
            }
        }, HEARTBEAT_INTERVAL_MS);
    }

    async _scheduleReconnect(retryJoin) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(async () => {
            if (this.stopped) {
                return;
            }
            try {
                if (retryJoin && this.snapshot?.access_code) {
                    await this.join(this.snapshot.access_code);
                } else {
                    const result = await rpc("state", { session_id: this.sessionId });
                    this._applySnapshot(result.snapshot);
                    await this._subscribeBus();
                }
            } catch (error) {
                console.warn("live_game reconnect failed, retrying…", error);
                this._scheduleReconnect(retryJoin);
            }
        }, RECONNECT_DELAY_MS);
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------
    /**
     * Connect using an existing session membership (host console or page
     * reload).  Resolves with the initial snapshot.
     */
    async connect() {
        const result = await rpc("state", { session_id: this.sessionId });
        this._applySnapshot(result.snapshot, { silent: true });
        await this._subscribeBus();
        await this._startHeartbeat();
        this._emit("lg_snapshot", this.snapshot);
        return this.snapshot;
    }

    /**
     * Join a session by its human code (students).  Resolves with the
     * snapshot containing `me`.
     */
    async join(accessCode) {
        const result = await rpc("join", { access_code: accessCode });
        this._applySnapshot(result.snapshot, { silent: true });
        await this._subscribeBus();
        await this._startHeartbeat();
        this._emit("lg_snapshot", this.snapshot);
        return this.snapshot;
    }

    /** Host controls. */
    async hostAction(action) {
        const result = await rpc("host_action", {
            session_id: this.sessionId,
            action,
        });
        this._applySnapshot(result.snapshot);
        return this.snapshot;
    }

    /** Game-specific RPC dispatched to the engine on the server. */
    async gameRpc(method, params = {}) {
        return rpc("game_rpc", {
            session_id: this.sessionId,
            method,
            params,
        });
    }

    stop() {
        this.stopped = true;
        clearInterval(this.heartbeatTimer);
        clearTimeout(this.reconnectTimer);
        if (this.snapshot?.bus_channel && this.busService) {
            this.busService.deleteChannel(this.snapshot.bus_channel);
        }
    }
}

/**
 * Create and connect a client.
 *
 * @param {Object} options
 * @param {number|null} options.sessionId  known session (host/reconnect)
 * @param {string|null} options.accessCode join code (students)
 */
export async function createLiveGameClient(options = {}) {
    const client = new LiveGameClient(options);
    if (options.accessCode) {
        await client.join(options.accessCode);
    } else {
        await client.connect();
    }
    return client;
}
