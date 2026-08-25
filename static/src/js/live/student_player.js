/**
 * Live realtime games — student player.
 *
 * Standalone OWL 2 app mounted on /educational_games/live/play?code=XXXX.
 * Join by game code, wait in the lobby, answer questions one at a time,
 * watch your avatar race around the screen perimeter.
 */

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { createLiveGameClient } from "./live_bus";
import { createTrack } from "./track";

export class LiveGamePlayer extends Component {
    static template = "educational_games.LiveGamePlayer";
    static props = {
        defaultCode: { type: String, optional: true },
    };

    setup() {
        this.state = useState({
            phase: "join", // join | loading | playing
            error: "",
            code: this.props.defaultCode || "",
            snapshot: null,
            question: null,
            selected: [],
            feedback: null, // {correct, correct_answer_ids, points_earned}
            submitting: false,
        });
        this.client = null;
        this.track = null;
        this._onResize = () => this.track?.layout();

        onWillStart(async () => {
            // Nothing async needed before first render; join happens on click.
        });

        onMounted(() => {
            window.addEventListener("resize", this._onResize);
        });

        onWillUnmount(() => {
            window.removeEventListener("resize", this._onResize);
            this.client?.stop();
        });
    }

    _ensureTrack() {
        if (this.track) {
            return;
        }
        const container = document.querySelector(".lg-mini-track-container");
        if (container) {
            this.track = createTrack(container);
        }
    }

    _syncTrack() {
        this._ensureTrack();
        if (this.track && this.state.snapshot) {
            this.track.render(this.participants);
        }
    }

    get me() {
        return this.state.snapshot?.me || null;
    }

    get participants() {
        return this.state.snapshot?.participants || [];
    }

    get isLobby() {
        return this.state.snapshot?.state === "lobby";
    }

    get isRunning() {
        return this.state.snapshot?.state === "running";
    }

    get isFinished() {
        return this.state.snapshot?.state === "finished";
    }

    get leaderboard() {
        return [...this.participants].sort(
            (a, b) => b.score - a.score || b.position - a.position
        );
    }

    get myRank() {
        const rank = this.leaderboard.findIndex((p) => p.id === this.me?.id);
        return rank >= 0 ? rank + 1 : null;
    }

    // Actions --------------------------------------------------------------
    async doJoin() {
        if (!this.state.code.trim()) {
            this.state.error = "Please enter a game code.";
            return;
        }
        this.state.phase = "loading";
        try {
            this.client = await createLiveGameClient({});
            await this.client.join(this.state.code.trim().toUpperCase());
            this._wireEvents();
            this.state.snapshot = this.client.snapshot;
            this.state.phase = "playing";
            if (this.isRunning) {
                await this.loadQuestion();
            }
        } catch (error) {
            this.state.phase = "join";
            this.state.error =
                error.message || "Could not join the game. Check the code and try again.";
        }
    }

    _wireEvents() {
        this.client.on("lg_snapshot", () => {
            this.state.snapshot = this.client.snapshot;
            this._syncTrack();
        });
        this.client.on("lg_state", () => {
            this.state.snapshot = { ...this.client.snapshot };
            this._syncTrack();
            if (this.isRunning && !this.state.question && !this.state.feedback) {
                this.loadQuestion();
            }
        });
        this.client.on("lg_progress", () => {
            this.state.snapshot = { ...this.client.snapshot };
            this._syncTrack();
        });
    }

    async loadQuestion() {
        try {
            const result = await this.client.gameRpc("get_question");
            this.state.question = result.question;
            this.state.selected = [];
            this.state.feedback = null;
        } catch (error) {
            this.state.error = error.message || "Could not load the next question.";
        }
    }

    toggleAnswer(answerId) {
        if (this.state.submitting || this.state.feedback) {
            return;
        }
        if (this.state.question.allow_multiple) {
            const index = this.state.selected.indexOf(answerId);
            if (index >= 0) {
                this.state.selected.splice(index, 1);
            } else {
                this.state.selected.push(answerId);
            }
        } else {
            this.state.selected = [answerId];
            this.doSubmit();
        }
    }    async doSubmit() {
        if (this.state.submitting || !this.state.selected.length || this.state.feedback) {
            return;
        }
        this.state.submitting = true;
        try {
            const result = await this.client.gameRpc("submit_answer", {
                answer_ids: [...this.state.selected],
                asked_at: this.state.question.asked_at,
            });
            this.state.feedback = result;
            this.state.snapshot = { ...this.client.snapshot };
            this._syncTrack();
        } catch (error) {
            this.state.error = error.message || "Could not submit the answer.";
        } finally {
            this.state.submitting = false;
        }
    }

    async doNext() {
        this.state.feedback = null;
        await this.loadQuestion();
    }
}
