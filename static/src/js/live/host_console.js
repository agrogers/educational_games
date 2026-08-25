/**
 * Live realtime games — host console (teacher projector view).
 *
 * Standalone OWL 2 app mounted on /educational_games/live/host/<id>.
 * Shows the join code during the lobby, the live perimeter track with all
 * avatars while running, and the final leaderboard when finished.
 */

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { createLiveGameClient } from "./live_bus";
import { createTrack } from "./track";

export class LiveGameHost extends Component {
    static template = "educational_games.LiveGameHost";
    static props = {
        sessionId: Number,
    };

    setup() {
        this.state = useState({
            loaded: false,
            error: "",
            snapshot: null,
        });
        this.client = null;
        this.track = null;
        this._onResize = () => this.track?.layout();

        onWillStart(async () => {
            try {
                this.client = await createLiveGameClient({ sessionId: this.props.sessionId });
                this.state.snapshot = this.client.snapshot;
                this.state.loaded = true;
                const onSnapshot = () => {
                    this.state.snapshot = { ...this.client.snapshot };
                    this.renderTrack();
                };
                this.client.on("lg_snapshot", onSnapshot);
                this.client.on("lg_state", onSnapshot);
                this.client.on("lg_progress", onSnapshot);
            } catch (error) {
                this.state.error = error.message || "Could not connect to the game.";
            }
        });

        onMounted(() => {
            const container = document.querySelector(".lg-track-container");
            if (container) {
                this.track = createTrack(container);
                this.renderTrack();
            }
            window.addEventListener("resize", this._onResize);
        });

        onWillUnmount(() => {
            window.removeEventListener("resize", this._onResize);
            this.client?.stop();
        });
    }

    renderTrack() {
        if (this.track && this.state.snapshot) {
            this.track.render(this.state.snapshot.participants || []);
        }
    }

    // Render helpers -----------------------------------------------------
    get state_() {
        return this.state.snapshot?.state || "";
    }

    get isLobby() {
        return this.state_ === "lobby";
    }

    get isRunning() {
        return this.state_ === "running";
    }

    get isFinished() {
        return this.state_ === "finished";
    }

    get accessCode() {
        return this.state.snapshot?.access_code || "";
    }

    get playUrl() {
        const base = window.location.origin + "/educational_games/live/play";
        return `${base}?code=${this.accessCode}`;
    }

    get leaderboard() {
        return [...(this.state.snapshot?.participants || [])].sort(
            (a, b) => b.score - a.score || b.position - a.position
        );
    }

    // Actions --------------------------------------------------------------
    async doOpenLobby() {
        await this.client.hostAction("open_lobby");
        this.state.snapshot = this.client.snapshot;
    }

    async doStart() {
        await this.client.hostAction("start");
        this.state.snapshot = this.client.snapshot;
    }

    async doFinish() {
        await this.client.hostAction("finish");
        this.state.snapshot = this.client.snapshot;
    }
}
