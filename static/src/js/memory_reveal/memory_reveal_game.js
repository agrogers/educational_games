/**
 * memory_reveal_game.js
 *
 * Student game viewer for Memory Reveal quizzes.
 * Extends ImageViewerDialog to reuse zoom/pan/image loading.
 * Adds: blur overlays, click-to-reveal, traffic light self-assessment, scoring.
 */
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ImageViewerDialog } from "@aui_enhancements/js/image_viewer_dialog";
import {
    APS_SUBMISSION_MODEL,
    saveToApsSubmission,
} from "@educational_games/js/utils/aps_submission";

const ZOOM_STEP = 0.08;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 5;
const HIGHLIGHT_COLORS = [
    "#ef4444",
    "#f97316",
    "#facc15",
    "#22c55e",
    "#06b6d4",
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
];

function decodeHtmlText(value) {
    const element = document.createElement("textarea");
    element.innerHTML = value || "";
    return element.value;
}

function getMemoryRevealQuizId(action) {
    const sources = [action?.params, action?.context];
    for (const source of sources) {
        for (const key of ["quiz_id", "default_quiz_id", "active_id", "res_id"]) {
            const value = Number.parseInt(source?.[key], 10);
            if (Number.isInteger(value) && value > 0) {
                return value;
            }
        }
    }

    // Client-action routing can preserve the record path while dropping the
    // action params/context. Recover the quiz ID from /quiz.quiz/<id>/...
    const match = window.location.pathname.match(/(?:^|\/)quiz\.quiz\/(\d+)(?:\/|$)/i);
    return match ? Number.parseInt(match[1], 10) : 0;
}

export class MemoryRevealGame extends ImageViewerDialog {
    static template = "educational_games.MemoryRevealGame";
    // Override props: accept client-action keys, make dialog keys optional
    static props = {
        ...ImageViewerDialog.props,
        close: { type: Function, optional: true },
        imageConfig: { type: Object, optional: true },
        action: { type: Object, optional: true },
        actionId: { type: [Number, String], optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        console.log("[MemoryRevealGame] setup() called, props keys:", Object.keys(this.props));
        console.log("[MemoryRevealGame] quiz_id from params:", this.props.action?.params?.quiz_id, "context:", this.props.action?.context?.quiz_id);

        // Provide safe defaults for dialog props when used as a client action
        if (!this.props.imageConfig) {
            this.props.imageConfig = { directUrl: "" };
        }
        if (!this.props.close) {
            this.props.close = () => {};
        }

        // Call super.setup() for zoom/pan/drawing infrastructure
        super.setup();

        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        // Game state — read quiz_id and submission params from action context/params
        const context = this.props.action?.context || {};
        const actionParams = this.props.action?.params || {};

        Object.assign(this.state, {
            quizId: getMemoryRevealQuizId(this.props.action),
            submissionId: parseInt(actionParams.active_id || context.active_id, 10) || 0,
            submissionModel: actionParams.active_model || context.active_model || APS_SUBMISSION_MODEL,
            quizName: "",
            regions: [],        // [{id, name, x1, y1, x2, y2, question_id, answers}]
            revealed: {},       // { questionId: true } — which regions are revealed
            assessments: {},    // { questionId: answerId } — self-assessment selections
            activeRegionId: null, // currently active region (showing traffic light)
            activeRegionAnswers: [], // answers for the currently active region
            activeRegionName: "",   // name of the currently active region
            score: 0,
            totalPossible: 0,
            completed: false,
            blurMode: true,     // true = blur, false = orange outline
            highlightedRegionId: null,
            highlightColor: "",
            attemptToken: "",
            loading: false,
        });

        this._highlightInterval = null;
        this._highlightTimeout = null;

        this._onKeydown = async (ev) => {
            if (ev.key === "Escape") {
                await this.closeViewer();
            }
        };
    }

    async mounted() {
        console.log("[MemoryRevealGame] mounted() called");
        console.log("[MemoryRevealGame] currentUrl:", this.state.currentUrl, "directUrl:", this.state.directUrl);
        await super.mounted?.();
        console.log("[MemoryRevealGame] super.mounted done");
        window.addEventListener("keydown", this._onKeydown);
        setTimeout(() => this.fitWholeImage(), 300);
    }

    async willUnmount() {
        this._stopRegionHighlight();
        await super.willUnmount?.();
        window.removeEventListener("keydown", this._onKeydown);
    }

    // ── Quiz data loading ──────────────────────────────────────────────────

    /**
     * Override loadCurrentImage to ensure quiz data (including the correct
     * image URL) is loaded BEFORE the parent runs the image-loading pipeline.
     * This prevents the parent's fallback branch from constructing "1.jpg"
     * when directUrl has not yet been populated.
     */
    async loadCurrentImage() {
        if (!this._quizDataLoaded) {
            await this._loadQuizData();
            this._quizDataLoaded = true;
        }
        // Do not allow the generic viewer to construct its default "/1.jpg"
        // URL when the quiz has no configured image.
        if (!this.state.directUrl) {
            this.state.currentUrl = "";
            this.state.errorMessage = _t("No image is configured for this quiz.");
            return;
        }
        return super.loadCurrentImage();
    }

    async _loadQuizData() {
        console.log("[MemoryRevealGame] _loadQuizData() called, quizId:", this.state.quizId);
        if (!this.state.quizId) {
            console.warn("[MemoryRevealGame] No quizId, aborting");
            return;
        }
        this.state.loading = true;
        try {
            console.log("[MemoryRevealGame] ORM reading quiz.quiz id:", this.state.quizId);
            const [quiz] = await this.orm.read("quiz.quiz", [this.state.quizId], [
                "name", "quiz_type", "question_ids",
            ]);
            console.log("[MemoryRevealGame] ORM result:", JSON.stringify(quiz));
            this.state.quizName = quiz.name || "";

            const imageUrl = await this.orm.call(
                "quiz.quiz",
                "get_memory_reveal_image_url",
                [this.state.quizId],
            );
            if (imageUrl) {
                console.log("[MemoryRevealGame] Setting image URL:", imageUrl);
                this.state.currentUrl = imageUrl;
                this.state.directUrl = imageUrl;
            } else {
                console.warn("[MemoryRevealGame] No image URL returned from ORM");
            }

            if (quiz.question_ids && quiz.question_ids.length > 0) {
                const questions = await this.orm.read("quiz.question", quiz.question_ids, [
                    "id", "question_text", "marks", "region_x1", "region_y1", "region_x2", "region_y2",
                    "answer_ids",
                ]);

                // Load answers for each question
                const allAnswerIds = questions.flatMap(q => q.answer_ids || []);
                let answerMap = {};
                if (allAnswerIds.length > 0) {
                    const answers = await this.orm.read("quiz.answer", allAnswerIds, [
                        "id", "answer_text", "is_correct", "marks",
                    ]);
                    answerMap = Object.fromEntries(answers.map(a => [a.id, a]));
                }

                this.state.regions = questions.map((q, idx) => ({
                    id: q.id,
                    name: decodeHtmlText(
                        (q.question_text || "").replace(/<[^>]+>/g, "").trim()
                    ) || `Region ${idx + 1}`,
                    x1: q.region_x1,
                    y1: q.region_y1,
                    x2: q.region_x2,
                    y2: q.region_y2,
                    question_id: q.id,
                    marks: q.marks,
                    answers: (q.answer_ids || []).map(aId => answerMap[aId]).filter(Boolean),
                    index: idx,
                }));
            }

            // Generate attempt token
            this.state.attemptToken = Date.now().toString(36) + Math.random().toString(36).slice(2);
        } catch (e) {
            console.error("[MemoryRevealGame] Failed to load quiz data:", e);
            this.notification.add(_t("Failed to load quiz"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // ── Region interaction ─────────────────────────────────────────────────

    onRegionClick(region) {
        if (this.state.revealed[region.id]) {
            // Already revealed — toggle traffic light visibility
            this.state.activeRegionId = this.state.activeRegionId === region.id ? null : region.id;
        } else {
            // Reveal the region
            this.state.revealed[region.id] = true;
            this.state.activeRegionId = region.id;
            this._updateTotalPossible();
        }
        this._updateActiveRegionInfo();
    }

    onSidebarRegionClick(region) {
        // Sidebar indicators locate a region without revealing its answer.
        this._highlightRegion(region);
    }

    _getRegionMaxMarks(region) {
        const answerMarks = (region.answers || [])
            .map(answer => Number(answer.marks))
            .filter(Number.isFinite);
        return answerMarks.length
            ? Math.max(...answerMarks)
            : Math.max(Number(region.marks) || 0, 0);
    }

    _updateTotalPossible() {
        this.state.totalPossible = this.state.regions
            .filter(region => this.state.revealed[region.id])
            .reduce((total, region) => total + this._getRegionMaxMarks(region), 0);
    }

    _highlightRegion(region) {
        this._stopRegionHighlight();
        this.state.highlightedRegionId = region.id;

        let colorIndex = 0;
        this.state.highlightColor = HIGHLIGHT_COLORS[colorIndex];
        this._highlightInterval = setInterval(() => {
            colorIndex = (colorIndex + 1) % HIGHLIGHT_COLORS.length;
            this.state.highlightColor = HIGHLIGHT_COLORS[colorIndex];
        }, 180);
        this._highlightTimeout = setTimeout(() => {
            this._stopRegionHighlight();
        }, 5000);
    }

    _stopRegionHighlight() {
        if (this._highlightInterval) {
            clearInterval(this._highlightInterval);
            this._highlightInterval = null;
        }
        if (this._highlightTimeout) {
            clearTimeout(this._highlightTimeout);
            this._highlightTimeout = null;
        }
        if (this.state) {
            this.state.highlightedRegionId = null;
            this.state.highlightColor = "";
        }
    }

    async onAssess(region, answer) {
        if (this.state.assessments[region.id]) return; // already assessed

        this.state.assessments[region.id] = answer.id;

        // Update score
        this.state.score += answer.marks;

        try {
            await this.orm.call("quiz.quiz", "submit_memory_reveal_assessment", [
                this.state.quizId,
                region.question_id,
                answer.id,
            ], {
                attempt_token: this.state.attemptToken,
            });
        } catch (e) {
            console.error("[MemoryRevealGame] Failed to save assessment:", e);
        }

        // Check if all regions are assessed
        if (Object.keys(this.state.assessments).length === this.state.regions.length) {
            this.state.completed = true;
            this.state.activeRegionId = null;
            await this._submitScore();
        } else {
            // Move to next unassessed region
            const nextRegion = this.state.regions.find(
                r => !this.state.assessments[r.id] && r.id !== region.id
            );
            if (nextRegion) {
                this.state.activeRegionId = nextRegion.id;
            }
        }
    }

    async _submitScore() {
        if (!this.state.submissionId || !this.state.submissionModel) return;
        try {
            const htmlReport = this._buildReportHtml();
            await saveToApsSubmission(
                this.orm,
                this.notification,
                this.state.submissionId,
                this.state.score,
                htmlReport,
                this.state.totalPossible,
            );
        } catch (e) {
            console.error("[MemoryRevealGame] Failed to submit score:", e);
        }
    }

    _buildReportHtml() {
        const regions = this.state.regions;
        const assessed = this.state.assessments;
        let rows = regions.map(r => {
            const answer = r.answers.find(a => a.id === assessed[r.id]);
            const label = answer ? (answer.answer_text || "").replace(/<[^>]+>/g, "").trim() : "—";
            const color = answer?.marks === 2 ? "green" : answer?.marks === 1 ? "orange" : "red";
            return `<tr>
                <td>${r.index + 1}</td>
                <td>${r.name}</td>
                <td style="color:${color};font-weight:bold;">${label}</td>
                <td>${answer?.marks ?? 0}</td>
            </tr>`;
        }).join("");

        return `<div class="memory-reveal-report">
            <h3>Memory Reveal: ${this.state.quizName}</h3>
            <p>Score: <strong>${this.state.score} / ${this.state.totalPossible}</strong></p>
            <table class="table table-sm">
                <thead><tr><th>#</th><th>Region</th><th>Assessment</th><th>Marks</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
    }

    // ── Toggle blur mode ──────────────────────────────────────────────────

    toggleBlurMode() {
        this.state.blurMode = !this.state.blurMode;
    }

    onBlurStyleClick() {
        if (!this.state.blurMode) {
            this.toggleBlurMode();
        }
    }

    onOutlineStyleClick() {
        if (this.state.blurMode) {
            this.toggleBlurMode();
        }
    }

    onAssessActiveRegion(answer) {
        const region = this.state.regions.find(r => r.id === this.state.activeRegionId);
        if (region) {
            this.onAssess(region, answer);
        }
    }

    regionAssessmentStyle(region) {
        // Place the controls below the region where possible; use the space
        // above it when the region is close to the bottom of the image.
        const left = Math.min(Math.max(region.x1, 1), 78);
        const top = region.y2 <= 84
            ? region.y2 + 1
            : Math.max(region.y1 - 9, 1);

        return `position:absolute;left:${left}%;top:${top}%;display:flex;` +
            "gap:8px;z-index:30;pointer-events:auto;";
    }

    regionNumberStyle(region) {
        const left = Math.min(Math.max(region.x1, 1), 96);
        const top = Math.max(region.y1, 1);
        // Size the marker from the image's natural width so it remains
        // proportional across images with different resolutions. The scene
        // applies the same zoom transform to the image and this marker.
        const markerSize = this.state.imageWidth
            ? this.state.imageWidth * 0.02
            : 28;
        const fontSize = markerSize * 0.46;
        const borderWidth = Math.max(2, markerSize * 0.07);
        const highlightStyle = this.state.highlightedRegionId === region.id
            ? `background:${this.state.highlightColor};transform:translate(-50%, calc(-50% - 5px)) scale(1.8);`
            : "transform:translate(-50%, calc(-50% - 5px));";
        return `position:absolute;left:${left}%;top:${top}%;z-index:25;` +
            `width:${markerSize}px;height:${markerSize}px;font-size:${fontSize}px;` +
            `border-width:${borderWidth}px;` +
            `${highlightStyle}pointer-events:none;`;
    }

    _updateActiveRegionInfo() {
        if (!this.state.activeRegionId) {
            this.state.activeRegionAnswers = [];
            this.state.activeRegionName = "";
            return;
        }
        const region = this.state.regions.find(r => r.id === this.state.activeRegionId);
        this.state.activeRegionAnswers = region ? region.answers || [] : [];
        this.state.activeRegionName = region ? region.name : "";
    }

    // ── Region styling helpers ─────────────────────────────────────────────

    regionOverlayStyle(region) {
        const left = region.x1;
        const top = region.y1;
        const width = region.x2 - region.x1;
        const height = region.y2 - region.y1;
        const isRevealed = !!this.state.revealed[region.id];
        const isActive = region.id === this.state.activeRegionId;
        const assessment = this.state.assessments[region.id];

        if (isRevealed && !assessment) {
            // Revealed but not yet assessed — no overlay, clean image
            return "display:none;";
        }
        if (assessment) {
            // Assessed — show color based on marks
            const answer = region.answers.find(a => a.id === assessment);
            const color = answer?.marks === 2 ? "#22c55e" : answer?.marks === 1 ? "#f59e0b" : "#ef4444";
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `border:5px solid ${color};background:transparent;pointer-events:none;`;
        }
        // Not revealed — blur or outline
        if (this.state.blurMode) {
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `backdrop-filter:blur(12px);` +
                `-webkit-backdrop-filter:blur(12px);` +
                `border-radius:12px;` +
                `background: rgba(255, 255, 255, 0.01);` + // Use a light white tint instead of gray
                `border: 4px solid rgba(255, 255, 255, 0.45);` +
                `cursor:pointer;`;
        } else {
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `border:5px solid #f97316;border-radius:12px;background:rgba(249,115,22,0.15);cursor:pointer;`;
        }
    }

    regionClickStyle(region) {
        const left = region.x1;
        const top = region.y1;
        const width = region.x2 - region.x1;
        const height = region.y2 - region.y1;
        return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;cursor:pointer;z-index:10;`;
    }

    // ── Sidebar helpers ───────────────────────────────────────────────────

    get remainingCount() {
        return this.state.regions.length - Object.keys(this.state.assessments).length;
    }

    get isComplete() {
        return this.state.completed;
    }

    indicatorClass(region) {
        const assessment = this.state.assessments[region.id];
        if (assessment) {
            const answer = region.answers.find(a => a.id === assessment);
            if (answer?.marks === 2) return "bg-success";
            if (answer?.marks === 1) return "bg-warning";
            return "bg-danger";
        }
        if (this.state.revealed[region.id]) return "bg-info";
        return "bg-secondary";
    }

    assessmentLabel(region) {
        const assessment = this.state.assessments[region.id];
        if (!assessment) return "";
        const answer = region.answers.find(a => a.id === assessment);
        return (answer?.answer_text || "").replace(/<[^>]+>/g, "").trim();
    }

    // ── Close ─────────────────────────────────────────────────────────────

    async closeViewer() {
        if (this.state.quizId) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "quiz.quiz",
                res_id: this.state.quizId,
                views: [[false, "form"]],
                target: "current",
            });
        } else {
            await this.props.close();
        }
    }
}

import { registry } from "@web/core/registry";
registry.category("actions").add("action_memory_reveal_game_js", MemoryRevealGame);
