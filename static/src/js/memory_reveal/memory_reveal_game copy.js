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

function getUrlQueryParams() {
    const params = new URLSearchParams(window.location?.search || "");
    const result = Object.fromEntries(params.entries());
    console.log("[MemoryRevealGame][launch] URL params", result);
    return result;
}

function loadStoredLaunchParams(key) {
    try {
        const raw = window.sessionStorage.getItem(key);
        const result = raw ? JSON.parse(raw) || {} : {};
        console.log("[MemoryRevealGame][launch] session storage", key, result);
        return result;
    } catch {
        console.error("[MemoryRevealGame][launch] failed to read session storage", key);
        return {};
    }
}

function loadPendingSubmissionParams() {
    return loadStoredLaunchParams("educational_games.pending_submission_context");
}

function getLaunchParam(action, storedParams, key) {
    const sources = [
        getUrlQueryParams(),
        action?.params,
        action?.context,
        storedParams,
    ];
    for (const [index, source] of sources.entries()) {
        const value = source?.[key];
        if (value !== undefined && value !== null && value !== "") {
            console.log("[MemoryRevealGame][launch] resolved parameter", {
                key,
                value,
                sourceIndex: index,
            });
            return value;
        }
    }
    console.warn("[MemoryRevealGame][launch] missing parameter", key);
    return undefined;
}

function getQuizIdFromRoute() {
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
        console.group("[MemoryRevealGame] setup");
        console.log("props", this.props);
        console.log("action", this.props.action);
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

        // Use the same launch contract as quiz_game.js.  quiz_id identifies the
        // quiz; active_id identifies a submission only when active_model says
        // that it is an aps.resource.submission record.
        const storageKey = this._getLaunchStorageKey();
        const storedParams = loadStoredLaunchParams(storageKey);
        const pendingSubmission = loadPendingSubmissionParams();
        const immediateLaunchSources = [
            getUrlQueryParams(),
            this.props.action?.params,
            this.props.action?.context,
        ];
        const hasImmediateQuizId = immediateLaunchSources.some(
            source => source?.quiz_id !== undefined && source?.quiz_id !== null && source?.quiz_id !== "",
        );
        const hasImmediateSubmissionContext = immediateLaunchSources.some(
            source => (
                source?.submission_id !== undefined && source?.submission_id !== null && source?.submission_id !== ""
            ) || (
                source?.active_model === APS_SUBMISSION_MODEL &&
                source?.active_id !== undefined && source?.active_id !== null && source?.active_id !== ""
            ),
        );
        // A fresh preview action contains quiz_id but no submission context.
        // Do not let an older submission stored for this route leak into it.
        const hasPendingSubmission = pendingSubmission.submission_model === APS_SUBMISSION_MODEL &&
            Number.parseInt(pendingSubmission.submission_id || pendingSubmission.active_id, 10) > 0;
        const contextStorage = hasPendingSubmission
            ? pendingSubmission
            : hasImmediateQuizId || hasImmediateSubmissionContext
                ? {}
                : storedParams;
        console.log("[MemoryRevealGame][launch] action sources", {
            urlParams: getUrlQueryParams(),
            actionParams: this.props.action?.params || {},
            actionContext: this.props.action?.context || {},
            storedParams,
            pendingSubmission,
            contextStorage,
        });
        const quizId = Number.parseInt(
            getLaunchParam(this.props.action, storedParams, "quiz_id"),
            10,
        ) || getQuizIdFromRoute();
        const explicitSubmissionModel = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_model",
        );
        const submissionModel = explicitSubmissionModel || getLaunchParam(
            this.props.action,
            contextStorage,
            "active_model",
        ) || "";
        const explicitSubmissionId = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_id",
        );
        const submissionId = submissionModel === APS_SUBMISSION_MODEL
            ? Number.parseInt(
                explicitSubmissionId || getLaunchParam(
                    this.props.action,
                    contextStorage,
                    "active_id",
                ),
                10,
            ) || 0
            : 0;
        const submissionState = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_state",
        ) || "";
        const isSubmissionContext = submissionModel === APS_SUBMISSION_MODEL && !!submissionId;
        const launchSubmissionId = Number.parseInt(
            getLaunchParam(this.props.action, contextStorage, "submission_id"),
            10,
        ) || 0;
        console.log("[MemoryRevealGame][launch] computed IDs", {
            quizId,
            submissionId,
            submissionModel,
            submissionState,
            isSubmissionContext,
            launchSubmissionId,
        });

        Object.assign(this.state, {
            quizId,
            submissionId,
            submissionModel,
            submissionState,
            isSubmissionContext,
            quizName: "",
            regions: [],        // [{id, name, x1, y1, x2, y2, question_id, answers}]
            revealed: {},       // { questionId: true } — which regions are revealed
            assessments: {},    // { questionId: answerId } — self-assessment selections
            activeRegionId: null, // currently active region (showing traffic light)
            activeRegionAnswers: [], // answers for the currently active region
            activeRegionName: "",   // name of the currently active region
            score: 0,
            totalPossible: 0,
            fullTotalMarks: 0,
            knownAttemptThreshold: 0,
            knownWeightedThreshold: 0,
            answeredMaximum: 0,
            progressSummary: {},
            progressExpanded: false,
            submissionSubmitted: false,
            completed: false,
            blurMode: true,     // true = blur, false = orange outline
            highlightedRegionId: null,
            highlightColor: "",
            attemptToken: "",
            saving: false,
            loading: false,
        });

        const normalizedLaunchParams = {
            quiz_id: quizId,
            ...(isSubmissionContext ? {
                active_id: submissionId,
                active_model: submissionModel,
                submission_id: submissionId,
                submission_model: submissionModel,
                submission_state: submissionState,
            } : {}),
        };
        this._persistLaunchParams(storageKey, normalizedLaunchParams);
        this._syncActionRouteState(normalizedLaunchParams);
        console.log("[MemoryRevealGame][launch] state after initialization", {
            quizId: this.state.quizId,
            submissionId: this.state.submissionId,
            submissionModel: this.state.submissionModel,
            submissionState: this.state.submissionState,
            isSubmissionContext: this.state.isSubmissionContext,
        });
        console.groupEnd();

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
        console.log("[MemoryRevealGame][load] loadCurrentImage", {
            quizDataLoaded: this._quizDataLoaded,
            quizId: this.state.quizId,
            directUrl: this.state.directUrl,
        });
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
        console.log("[MemoryRevealGame][load] _loadQuizData start", {
            quizId: this.state.quizId,
            isSubmissionContext: this.state.isSubmissionContext,
        });
        if (!this.state.quizId) {
            console.warn("[MemoryRevealGame] No quizId, aborting");
            return;
        }
        this.state.loading = true;
        try {
            console.log("[MemoryRevealGame] ORM reading quiz.quiz id:", this.state.quizId);
            const data = await this.orm.call(
                "quiz.quiz",
                "get_memory_reveal_data",
                [this.state.quizId],
            );
            console.log("[MemoryRevealGame][load] quiz data received", data);
            this.state.quizName = data.quiz_name || "";
            this.state.fullTotalMarks = data.full_total_marks || 0;
            this.state.knownAttemptThreshold = data.filter_student_attempts || 0;
            this.state.knownWeightedThreshold = data.filter_student_weighted_score_pct || 0;
            this.state.progressSummary = data.progress_summary || {};

            const imageUrl = await this.orm.call(
                "quiz.quiz",
                "get_memory_reveal_image_url",
                [this.state.quizId],
            );
            console.log("[MemoryRevealGame][load] image URL received", imageUrl);
            if (imageUrl) {
                console.log("[MemoryRevealGame] Setting image URL:", imageUrl);
                this.state.currentUrl = imageUrl;
                this.state.directUrl = imageUrl;
            } else {
                console.warn("[MemoryRevealGame] No image URL returned from ORM");
            }

            this.state.regions = (data.regions || []).map((q, idx) => ({
                    id: q.id,
                    name: decodeHtmlText(
                        (q.name || "").replace(/<[^>]+>/g, "").trim()
                    ) || `Region ${idx + 1}`,
                    x1: q.x1,
                    y1: q.y1,
                    x2: q.x2,
                    y2: q.y2,
                    question_id: q.id,
                    marks: q.marks,
                    answers: q.answers || [],
                    index: q.index ?? idx,
                    attemptCount: q.attempt_count || 0,
                    weightedScorePct: q.weighted_score_pct,
                    lastAnsweredAt: q.last_answered_at,
                    category: q.category || "not_tried",
                }));

            // Generate attempt token
            this.state.attemptToken = Date.now().toString(36) + Math.random().toString(36).slice(2);
        } catch (e) {
            console.error("[MemoryRevealGame][load] failed to load quiz data", e);
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
        this.state.fullTotalMarks = this.state.regions
            .reduce((total, region) => total + this._getRegionMaxMarks(region), 0);
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
        console.log("[MemoryRevealGame][assessment] onAssess", {
            regionId: region?.id,
            questionId: region?.question_id,
            answerId: answer?.id,
            beforeAssessments: { ...this.state.assessments },
        });
        if (this.state.assessments[region.id]) return; // already assessed

        this.state.assessments[region.id] = answer.id;

        // Update score
        this.state.score += answer.marks;

        try {
            const response = await this.orm.call("quiz.quiz", "submit_memory_reveal_assessment", [
                this.state.quizId,
                region.question_id,
                answer.id,
            ], {
                attempt_token: this.state.attemptToken,
            });
            console.log("[MemoryRevealGame][assessment] server response", response);
        } catch (e) {
            console.error("[MemoryRevealGame][assessment] failed to save assessment", e);
        }

        this._updateAnsweredMaximum();
        this._refreshProgressFromSession();
        console.log("[MemoryRevealGame][assessment] state after assessment", {
            assessments: { ...this.state.assessments },
            score: this.state.score,
            answeredMaximum: this.state.answeredMaximum,
            canSubmitResults: this.canSubmitResults,
            isSubmissionContext: this.state.isSubmissionContext,
            submissionId: this.state.submissionId,
            submissionState: this.state.submissionState,
        });

        // Check if all regions are assessed
        if (Object.keys(this.state.assessments).length === this.state.regions.length) {
            this.state.completed = true;
            this.state.activeRegionId = null;
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

    async submitResults() {
        console.log("[MemoryRevealGame][submit] submitResults clicked", {
            isSubmissionContext: this.state.isSubmissionContext,
            submissionId: this.state.submissionId,
            submissionModel: this.state.submissionModel,
            submissionState: this.state.submissionState,
            assessments: { ...this.state.assessments },
            score: this.state.score,
            answeredMaximum: this.state.answeredMaximum,
        });
        if (!this.state.isSubmissionContext) {
            console.warn("[MemoryRevealGame][submit] aborted: not a submission context");
            this.notification.add(_t("This game was opened in preview mode and cannot submit results."), { type: "info" });
            return;
        }
        if (!Object.keys(this.state.assessments).length) {
            this.notification.add(_t("Assess at least one region before submitting."), { type: "warning" });
            return;
        }
        if (this.state.submissionState && this.state.submissionState !== "assigned") {
            console.warn("[MemoryRevealGame][submit] aborted: submission is not assigned", this.state.submissionState);
            this.notification.add(_t("This submission has already been submitted."), { type: "info" });
            return;
        }
        if (this.state.saving) {
            return;
        }
        this.state.saving = true;
        try {
            const htmlReport = this._buildReportHtml();
            const saved = await saveToApsSubmission(
                this.orm,
                this.notification,
                this.state.submissionId,
                this.state.score,
                htmlReport,
                this.state.answeredMaximum,
            );
            console.log("[MemoryRevealGame][submit] save helper result", saved);
            if (saved) {
                this.state.submissionSubmitted = true;
                this.state.submissionState = "submitted";
            }
        } catch (e) {
            console.error("[MemoryRevealGame][submit] failed to submit score", e);
        } finally {
            this.state.saving = false;
        }
    }

    _updateAnsweredMaximum() {
        this.state.answeredMaximum = this.state.regions
            .filter(region => this.state.assessments[region.id])
            .reduce((total, region) => total + this._getRegionMaxMarks(region), 0);
        this.state.totalPossible = this.state.answeredMaximum;
    }

    _refreshProgressFromSession() {
        const summary = {
            known_questions: 0,
            not_known_questions: 0,
            new_above_threshold: 0,
            new_below_threshold: 0,
            not_tried_questions: 0,
        };
        for (const region of this.state.regions) {
            const selectedId = this.state.assessments[region.id];
            if (selectedId) {
                const answer = region.answers.find(item => item.id === selectedId);
                region.attemptCount = Math.max(region.attemptCount || 0, 1);
                region.weightedScorePct = answer
                    ? (Number(answer.marks) / Math.max(this._getRegionMaxMarks(region), 1)) * 100
                    : 0;
                region.lastAnsweredAt = new Date().toISOString();
                const meetsScore = !this.state.knownWeightedThreshold ||
                    region.weightedScorePct >= this.state.knownWeightedThreshold;
                const meetsAttempts = !this.state.knownAttemptThreshold ||
                    region.attemptCount >= this.state.knownAttemptThreshold;
                region.category = meetsScore && meetsAttempts
                    ? "known"
                    : region.weightedScorePct < 50
                        ? "not_known"
                        : "middle";
            }
            const categoryKey = region.category === "not_known"
                ? "not_known_questions"
                : `${region.category || "not_tried"}_questions`;
            summary[categoryKey] += 1;
        }
        this.state.progressSummary = {
            ...this.state.progressSummary,
            ...summary,
        };
    }

    _buildReportHtml() {
        const regions = this.state.regions;
        const assessed = this.state.assessments;
        let rows = regions.map(r => {
            const answer = r.answers.find(a => a.id === assessed[r.id]);
            const label = answer ? this._escapeHtml(answer.answer_text || "") : "—";
            const name = this._escapeHtml(r.name);
            const color = answer?.marks === 2 ? "green" : answer?.marks === 1 ? "orange" : "red";
            return `<tr>
                <td>${r.index + 1}</td>
                <td>${name}</td>
                <td style="color:${color};font-weight:bold;">${label}</td>
                <td>${answer?.marks ?? 0}</td>
            </tr>`;
        }).join("");

        return `<div class="memory-reveal-report">
            <h3>Memory Reveal: ${this._escapeHtml(this.state.quizName)}</h3>
            <p>Score: <strong>${this.state.score}/${this.state.answeredMaximum}</strong> (from a possible total of ${this.state.fullTotalMarks})</p>
            <table class="table table-sm">
                <thead><tr><th>#</th><th>Region</th><th>Assessment</th><th>Marks</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
    }

    _escapeHtml(value) {
        const element = document.createElement("div");
        element.textContent = value || "";
        return element.innerHTML;
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
                `border:1px solid ${color};` +
                `background:transparent;pointer-events:none;`;
        }
        // Not revealed — blur or outline
        if (this.state.blurMode) {
            // Progress age controls the sidebar circle only. The image region
            // keeps a stable border width, while its colour still indicates
            // the current progress zone.
            const borderColor = this.regionProgressBorderColor(region);
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `backdrop-filter:blur(12px);` +
                `-webkit-backdrop-filter:blur(12px);` +
                `border-radius:10px;` +
                `background: rgba(255, 255, 255, 0.01);` + // Use a light white tint instead of gray
                `border:1px solid ${borderColor};` +
                `cursor:pointer;`;
        } else {
            const borderColor = this.regionProgressBorderColor(region);
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `border:5px solid ${borderColor};` +
                `border-radius:12px;background:rgba(249,115,22,0.15);cursor:pointer;`;
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

    get canSubmitResults() {
        const canSubmit = this.state.isSubmissionContext &&
            !this.state.submissionSubmitted &&
            (!this.state.submissionState || this.state.submissionState === "assigned") &&
            !this.state.saving;
        console.log("[MemoryRevealGame][render] canSubmitResults", {
            canSubmit,
            isSubmissionContext: this.state.isSubmissionContext,
            submissionSubmitted: this.state.submissionSubmitted,
            submissionState: this.state.submissionState,
            assessmentCount: Object.keys(this.state.assessments).length,
        });
        return canSubmit;
    }

    toggleProgressSummary() {
        this.state.progressExpanded = !this.state.progressExpanded;
    }

    progressWidth(key) {
        const total = this.state.regions.length || 1;
        return ((this.state.progressSummary[key] || 0) / total) * 100;
    }

    regionProgressClass(region) {
        // Once the student has responded, the sidebar number returns to its
        // normal result indicator. The review-age border is only useful for
        // regions still waiting to be reviewed.
        if (this.state.assessments[region.id]) return "";
        if (region.category === "known") return "memory-region-known";
        if (region.category === "not_known") return "memory-region-learning";
        if ((region.attemptCount || 0) > 0) return "memory-region-middle";
        return "";
    }

    regionProgressStyle(region) {
        if (this.state.assessments[region.id] || !(region.attemptCount || 0) || !region.lastAnsweredAt) {
            return "";
        }
        const ageDays = this._regionAgeDays(region);
        const width = Math.max(2, 9 - Math.floor(ageDays / 5));
        const style = ageDays >= 10 ? "dashed" : "solid";
        return `border-style:${style};border-width:${width}px;`;
    }

    regionProgressBorderColor(region) {
        return region.category === "known"
            ? "#22c55e"
            : region.category === "not_known"
                ? "#f97316"
                : region.category === "middle"
                    ? "#adb5bd"
                    : "rgba(255, 255, 255, 0.45)";
    }

    _regionAgeDays(region) {
        const timestamp = Date.parse(region.lastAnsweredAt);
        if (!Number.isFinite(timestamp)) return 0;
        return Math.max(0, (Date.now() - timestamp) / 86400000);
    }

    _getLaunchStorageKey() {
        return `educational_games.memory_reveal.launch:${window.location.pathname}`;
    }

    _persistLaunchParams(storageKey, payload) {
        if (!payload.quiz_id) {
            return;
        }

        try {
            window.sessionStorage.setItem(storageKey, JSON.stringify(payload));
        } catch {
            // Ignore storage failures, including private-mode restrictions.
        }

        try {
            const url = new URL(window.location.href);
            const keys = [
                "quiz_id",
                "active_id",
                "active_model",
                "submission_id",
                "submission_model",
                "submission_state",
            ];
            let changed = false;

            for (const key of keys) {
                const value = payload[key];
                if (value === undefined || value === null || value === "" || value === false || value === 0) {
                    if (url.searchParams.has(key)) {
                        url.searchParams.delete(key);
                        changed = true;
                    }
                    continue;
                }
                const stringValue = String(value);
                if (url.searchParams.get(key) !== stringValue) {
                    url.searchParams.set(key, stringValue);
                    changed = true;
                }
            }

            if (changed) {
                window.history.replaceState(window.history.state, "", url.toString());
            }
        } catch {
            // Ignore URL manipulation failures.
        }
    }

    _syncActionRouteState(payload) {
        if (!this.props.updateActionState || !payload.quiz_id) {
            return;
        }
        this.props.updateActionState(payload);
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

    indicatorStyle(region) {
        return this.regionProgressStyle(region);
    }

    assessmentLabel(region) {
        const assessment = this.state.assessments[region.id];
        if (!assessment) return "";
        const answer = region.answers.find(a => a.id === assessment);
        return (answer?.answer_text || "").replace(/<[^>]+>/g, "").trim();
    }

    // ── Close ─────────────────────────────────────────────────────────────

    async closeViewer() {
        // Restore the action that opened this client action instead of
        // forcing navigation to the quiz form. This preserves the previous
        // list, resource, submission, or other originating view.
        if (this.action?.restore) {
            await this.action.restore();
        } else {
            await this.props.close();
        }
    }
}

import { registry } from "@web/core/registry";
registry.category("actions").add("action_memory_reveal_game_js", MemoryRevealGame);
