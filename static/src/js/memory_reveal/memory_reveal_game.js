import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ImageViewerDialog } from "@aui_enhancements/js/image_viewer_dialog";
import {
    APS_SUBMISSION_MODEL,
    saveMemoryRevealResult,
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
    return Object.fromEntries(params.entries());
}

function loadStoredLaunchParams(key) {
    try {
        return JSON.parse(window.sessionStorage.getItem(key) || "{}") || {};
    } catch {
        return {};
    }
}

function loadPendingSubmissionParams() {
    return loadStoredLaunchParams("educational_games.pending_submission_context");
}

function getLaunchParam(action, storedParams, key, extraSources = []) {
    const sources = [
        getUrlQueryParams(),
        action?.params,
        action?.context,
        ...extraSources,
        storedParams,
    ];
    for (const source of sources) {
        const value = source?.[key];
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }
    return undefined;
}

function getQuizIdFromRoute() {
    const match = window.location.pathname.match(/(?:^|\/)quiz\.quiz\/(\d+)(?:\/|$)/i);
    return match ? Number.parseInt(match[1], 10) : 0;
}

function getSubmissionRouteId() {
    const match = window.location.pathname.match(
        /(?:^|\/)quiz\.quiz\/(\d+)\/(\d+)(?:\/|$)/i,
    );
    return match ? Number.parseInt(match[2], 10) : 0;
}

function parseActionValue(value) {
    if (typeof value !== "string") {
        return value;
    }
    try {
        return JSON.parse(value);
    } catch {
        return value;
    }
}

function getActionContextSources(action) {
    const sources = [];
    let originalAction = parseActionValue(action?._originalAction);
    if (originalAction && typeof originalAction === "object") {
        sources.push(originalAction, originalAction.context, originalAction.params);
    }
    const actionStack = action?.params?.actionStack;
    if (Array.isArray(actionStack)) {
        for (const stackEntry of actionStack) {
            const parsedEntry = parseActionValue(stackEntry);
            sources.push(parsedEntry, parsedEntry?.context, parsedEntry?.params);
        }
    }
    return sources;
}

export class MemoryRevealGame extends ImageViewerDialog {
    static template = "educational_games.MemoryRevealGame";
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
        if (!this.props.imageConfig) {
            this.props.imageConfig = { directUrl: "" };
        }
        if (!this.props.close) {
            this.props.close = () => {};
        }

        super.setup();

        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        const storageKey = this._getLaunchStorageKey();
        const storedParams = loadStoredLaunchParams(storageKey);
        const pendingSubmission = loadPendingSubmissionParams();
        const actionSources = getActionContextSources(this.props.action);
        const immediateSources = [
            getUrlQueryParams(),
            this.props.action?.params,
            this.props.action?.context,
            ...actionSources,
        ];
        const hasImmediateQuizId = immediateSources.some((source) => (
            source?.quiz_id !== undefined && source?.quiz_id !== null && source?.quiz_id !== ""
        ));
        const hasImmediateSubmissionContext = immediateSources.some((source) => (
            source?.submission_id !== undefined && source?.submission_id !== null && source?.submission_id !== ""
        ) || (
            source?.active_model === APS_SUBMISSION_MODEL &&
            source?.active_id !== undefined && source?.active_id !== null && source?.active_id !== ""
        ));
        const pendingSubmissionId = Number.parseInt(
            pendingSubmission.submission_id || pendingSubmission.active_id,
            10,
        ) || 0;
        const hasPendingSubmission = pendingSubmission.submission_model === APS_SUBMISSION_MODEL &&
            pendingSubmissionId > 0;
        // A direct preview launch must not inherit a submission from an older
        // session. A pending submission is intentionally retained when the
        // submission flow opened this action without query parameters.
        const contextStorage = hasPendingSubmission
            ? pendingSubmission
            : hasImmediateQuizId || hasImmediateSubmissionContext
                ? {}
                : storedParams;

        const quizId = Number.parseInt(
            getLaunchParam(this.props.action, contextStorage, "quiz_id", actionSources),
            10,
        ) || getQuizIdFromRoute();
        const explicitSubmissionModel = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_model",
            actionSources,
        );
        const submissionModel = explicitSubmissionModel || getLaunchParam(
            this.props.action,
            contextStorage,
            "active_model",
            actionSources,
        ) || "";
        const explicitSubmissionId = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_id",
            actionSources,
        );
        const submissionId = submissionModel === APS_SUBMISSION_MODEL
            ? Number.parseInt(
                explicitSubmissionId || getLaunchParam(
                    this.props.action,
                    contextStorage,
                    "active_id",
                    actionSources,
                ),
                10,
            ) || getSubmissionRouteId()
            : 0;
        const submissionState = getLaunchParam(
            this.props.action,
            contextStorage,
            "submission_state",
            actionSources,
        ) || "";
        const isSubmissionContext = submissionModel === APS_SUBMISSION_MODEL && !!submissionId;

        Object.assign(this.state, {
            quizId,
            submissionId,
            submissionModel,
            submissionState,
            isSubmissionContext,
            quizName: "",
            regions: [],
            revealed: {},
            assessments: {},
            activeRegionId: null,
            activeRegionAnswers: [],
            activeRegionName: "",
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
            blurMode: true,
            highlightedRegionId: null,
            hoveredRegionId: null,
            highlightColor: "",
            attemptToken: "",
            saving: false,
            loading: false,
                submitToastMessage: "",
                submitToastType: "success",
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

        this._highlightInterval = null;
        this._highlightTimeout = null;
            this._submitToastTimeout = null;
        this._onKeydown = async (ev) => {
            if (ev.key === "Escape") {
                await this.closeViewer();
            }
        };
    }

    async mounted() {
        await super.mounted?.();
        window.addEventListener("keydown", this._onKeydown);
        setTimeout(() => this.fitWholeImage(), 300);
    }

    async willUnmount() {
        this._stopRegionHighlight();
            if (this._submitToastTimeout) {
                clearTimeout(this._submitToastTimeout);
                this._submitToastTimeout = null;
            }
        await super.willUnmount?.();
        window.removeEventListener("keydown", this._onKeydown);
    }

    async loadCurrentImage() {
        if (!this._quizDataLoaded) {
            await this._loadQuizData();
            this._quizDataLoaded = true;
        }
        if (!this.state.directUrl) {
            this.state.currentUrl = "";
            this.state.errorMessage = _t("No image is configured for this quiz.");
            return;
        }
        return super.loadCurrentImage();
    }

    async _loadQuizData() {
        if (!this.state.quizId) {
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "quiz.quiz",
                "get_memory_reveal_data",
                [this.state.quizId],
            );
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
            if (imageUrl) {
                this.state.currentUrl = imageUrl;
                this.state.directUrl = imageUrl;
            }

            this.state.regions = (data.regions || []).map((question, index) => ({
                id: question.id,
                name: decodeHtmlText(
                    (question.name || "").replace(/<[^>]+>/g, "").trim(),
                ) || `Region ${index + 1}`,
                x1: question.x1,
                y1: question.y1,
                x2: question.x2,
                y2: question.y2,
                question_id: question.id,
                marks: question.marks,
                answers: question.answers || [],
                index: question.index ?? index,
                attemptCount: question.attempt_count || 0,
                weightedScorePct: question.weighted_score_pct,
                lastAnsweredAt: question.last_answered_at,
                category: question.category || "not_tried",
            }));
            this.state.attemptToken = Date.now().toString(36) + Math.random().toString(36).slice(2);
            this._updateTotalPossible();
        } catch (error) {
            console.error("[MemoryRevealGame] failed to load quiz data", error);
            this.notification.add(_t("Failed to load quiz"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onRegionClick(region) {
        if (this.state.revealed[region.id]) {
            this.state.activeRegionId = this.state.activeRegionId === region.id ? null : region.id;
        } else {
            this.state.revealed[region.id] = true;
            this.state.activeRegionId = region.id;
            this._updateTotalPossible();
        }
        this._updateActiveRegionInfo();
    }

    onSidebarRegionClick(region) {
        this._highlightRegion(region);
    }

    onRegionPointerEnter(region) {
        this.state.hoveredRegionId = region.id;
    }

    onRegionPointerLeave(region) {
        if (this.state.hoveredRegionId === region.id) {
            this.state.hoveredRegionId = null;
        }
    }

    _getRegionMaxMarks(region) {
        const answerMarks = (region.answers || [])
            .map((answer) => Number(answer.marks))
            .filter(Number.isFinite);
        return answerMarks.length
            ? Math.max(...answerMarks)
            : Math.max(Number(region.marks) || 0, 0);
    }

    _updateTotalPossible() {
        this.state.fullTotalMarks = this.state.regions.reduce(
            (total, region) => total + this._getRegionMaxMarks(region),
            0,
        );
        this.state.totalPossible = this.state.regions
            .filter((region) => this.state.revealed[region.id])
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
        this._highlightTimeout = setTimeout(() => this._stopRegionHighlight(), 5000);
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
        if (this.state.assessments[region.id]) {
            return;
        }
        this.state.assessments[region.id] = answer.id;
        this.state.score += Number(answer.marks) || 0;

        try {
            await this.orm.call(
                "quiz.quiz",
                "submit_memory_reveal_assessment",
                [this.state.quizId, region.question_id, answer.id],
                { attempt_token: this.state.attemptToken },
            );
        } catch (error) {
            console.error("[MemoryRevealGame] failed to save assessment", error);
        }

        this._updateAnsweredMaximum();
        this._refreshProgressFromSession();
        if (Object.keys(this.state.assessments).length === this.state.regions.length) {
            this.state.completed = true;
            this.state.activeRegionId = null;
        } else {
            const nextRegion = this.state.regions.find(
                (candidate) => !this.state.assessments[candidate.id] && candidate.id !== region.id,
            );
            if (nextRegion) {
                this.state.activeRegionId = nextRegion.id;
                this._updateActiveRegionInfo();
            }
        }
    }

    async submitResults() {
        if (!this.state.isSubmissionContext) {
            this.notification.add(
                _t("This game was opened in preview mode and cannot submit results."),
                { type: "info" },
            );
            return;
        }
        if (!Object.keys(this.state.assessments).length) {
            this.notification.add(_t("Assess at least one region before submitting."), { type: "warning" });
            return;
        }
        if (this.state.submissionState && this.state.submissionState !== "assigned") {
            this.notification.add(_t("This submission has already been submitted."), { type: "info" });
            return;
        }
        if (this.state.saving) {
            return;
        }

        this.state.saving = true;
        try {
            const saved = await saveMemoryRevealResult(
                this.orm,
                this.notification,
                this.state.submissionId,
                this.state.score,
                this._buildReportHtml(),
                this.state.answeredMaximum,
            );
            if (saved) {
                    this._showSubmitToast(_t("Submit successful!"));
                this.state.submissionSubmitted = true;
                this.state.submissionState = "submitted";
            }
        } catch (error) {
            console.error("[MemoryRevealGame] failed to submit score", error);
        } finally {
            this.state.saving = false;
        }
    }

    _updateAnsweredMaximum() {
        this.state.answeredMaximum = this.state.regions
            .filter((region) => this.state.assessments[region.id])
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
                const answer = region.answers.find((item) => item.id === selectedId);
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
            if (summary[categoryKey] !== undefined) {
                summary[categoryKey] += 1;
            }
        }
        this.state.progressSummary = { ...this.state.progressSummary, ...summary };
    }

    _buildReportHtml() {
            const answeredRegions = this.state.regions.filter(
                (region) => this.state.assessments[region.id],
            );
            const rows = answeredRegions.map((region) => {
            const answer = region.answers.find((item) => item.id === this.state.assessments[region.id]);
                const label = this._escapeHtml(this._stripHtml(answer?.answer_text || ""));
                const name = this._escapeHtml(this._stripHtml(region.name));
            const marks = Number(answer?.marks) || 0;
            const color = marks === 2 ? "green" : marks === 1 ? "orange" : "red";
            return `<tr><td>${region.index + 1}</td><td>${name}</td>` +
                `<td style="color:${color};font-weight:bold;">${label}</td>` +
                `<td>${marks}</td></tr>`;
        }).join("");
        return `<div class="memory-reveal-report">` +
            `<h3>Memory Reveal: ${this._escapeHtml(this.state.quizName)}</h3>` +
            `<p>Score: <strong>${this.state.score}/${this.state.answeredMaximum}</strong> ` +
            `(from a possible total of ${this.state.fullTotalMarks})</p>` +
            `<table class="table table-sm"><thead><tr><th>#</th><th>Region</th>` +
            `<th>Assessment</th><th>Marks</th></tr></thead><tbody>${rows}</tbody></table>` +
            `</div>`;
    }

        _showSubmitToast(message, type = "success") {
            if (this._submitToastTimeout) {
                clearTimeout(this._submitToastTimeout);
            }
            this.state.submitToastMessage = message;
            this.state.submitToastType = type;
            this._submitToastTimeout = setTimeout(() => {
                this.state.submitToastMessage = "";
                this._submitToastTimeout = null;
            }, 5000);
        }

        dismissSubmitToast() {
            if (this._submitToastTimeout) {
                clearTimeout(this._submitToastTimeout);
                this._submitToastTimeout = null;
            }
            this.state.submitToastMessage = "";
        }

    _escapeHtml(value) {
        const element = document.createElement("div");
        element.textContent = value || "";
        return element.innerHTML;
    }

    _stripHtml(value) {
        const element = document.createElement("div");
        element.innerHTML = value || "";
        return (element.textContent || element.innerText || "").trim();
    }

    toggleBlurMode() {
        this.state.blurMode = !this.state.blurMode;
    }

    onBlurStyleClick() {
        if (!this.state.blurMode) this.toggleBlurMode();
    }

    onOutlineStyleClick() {
        if (this.state.blurMode) this.toggleBlurMode();
    }

    onAssessActiveRegion(answer) {
        const region = this.state.regions.find((candidate) => candidate.id === this.state.activeRegionId);
        if (region) this.onAssess(region, answer);
    }

    regionAssessmentStyle(region) {
        const left = Math.min(Math.max(region.x1, 1), 78);
        const top = region.y2 <= 84 ? region.y2 + 1 : Math.max(region.y1 - 9, 1);
        return `position:absolute;left:${left}%;top:${top}%;display:flex;` +
            "gap:8px;z-index:30;pointer-events:auto;";
    }

    regionNumberStyle(region) {
        const left = Math.min(Math.max(region.x1, 1), 96);
        const top = Math.max(region.y1, 1);
        const markerSize = this.state.imageWidth ? this.state.imageWidth * 0.02 : 28;
        const fontSize = markerSize * 0.46;
        const borderWidth = Math.max(2, markerSize * 0.07);
        const highlightStyle = this.state.highlightedRegionId === region.id
            ? `background:${this.state.highlightColor};transform:translate(-50%, calc(-50% - 5px)) scale(1.8);`
            : "transform:translate(-50%, calc(-50% - 5px));";
        return `position:absolute;left:${left}%;top:${top}%;z-index:25;` +
            `width:${markerSize}px;height:${markerSize}px;font-size:${fontSize}px;` +
            `border-width:${borderWidth}px;${highlightStyle}pointer-events:none;`;
    }

    _updateActiveRegionInfo() {
        if (!this.state.activeRegionId) {
            this.state.activeRegionAnswers = [];
            this.state.activeRegionName = "";
            return;
        }
        const region = this.state.regions.find((candidate) => candidate.id === this.state.activeRegionId);
        this.state.activeRegionAnswers = region ? region.answers || [] : [];
        this.state.activeRegionName = region ? region.name : "";
    }

    regionOverlayStyle(region) {
        const left = region.x1;
        const top = region.y1;
        const width = region.x2 - region.x1;
        const height = region.y2 - region.y1;
        const isRevealed = !!this.state.revealed[region.id];
        const assessment = this.state.assessments[region.id];
        if (isRevealed && !assessment) return "display:none;";
        if (assessment) {
            const answer = region.answers.find((item) => item.id === assessment);
            const color = answer?.marks === 2 ? "#22c55e" : answer?.marks === 1 ? "#f59e0b" : "#ef4444";
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `border:1px solid ${color};background:transparent;pointer-events:none;`;
        }
        const borderColor = this.regionProgressBorderColor(region);
        if (this.state.blurMode) {
            return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
                `backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);` +
                `border-radius:10px;background:rgba(255,255,255,0.01);` +
                `border:1px solid ${borderColor};cursor:pointer;`;
        }
        return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;` +
            `border:5px solid ${borderColor};border-radius:12px;` +
            "background:rgba(249,115,22,0.15);cursor:pointer;";
    }

    regionClickStyle(region) {
        const width = region.x2 - region.x1;
        const height = region.y2 - region.y1;
        return `position:absolute;left:${region.x1}%;top:${region.y1}%;` +
            `width:${width}%;height:${height}%;cursor:pointer;z-index:10;`;
    }

    get remainingCount() {
        return this.state.regions.length - Object.keys(this.state.assessments).length;
    }

    get isComplete() {
        return this.state.completed;
    }

    get canSubmitResults() {
        return this.state.isSubmissionContext &&
            !this.state.submissionSubmitted &&
            (!this.state.submissionState || this.state.submissionState === "assigned") &&
            !this.state.saving;
    }

    toggleProgressSummary() {
        this.state.progressExpanded = !this.state.progressExpanded;
    }

    progressWidth(key) {
        const total = this.state.regions.length || 1;
        return ((this.state.progressSummary[key] || 0) / total) * 100;
    }

    regionProgressClass(region) {
        if (this.state.assessments[region.id]) return "";
        if (region.category === "known") return "memory-region-known";
        if (region.category === "not_known") return "memory-region-learning";
        if ((region.attemptCount || 0) > 0) return "memory-region-middle";
        return "";
    }

    regionProgressStyle(region) {
        if (this.state.assessments[region.id] || !(region.attemptCount || 0) || !region.lastAnsweredAt) return "";
        const ageDays = this._regionAgeDays(region);
        const width = Math.max(2, 9 - Math.floor(ageDays / 5));
        return `border-style:${ageDays >= 10 ? "dashed" : "solid"};border-width:${width}px;`;
    }

    regionProgressBorderColor(region) {
        return region.category === "known"
            ? "#22c55e"
            : region.category === "not_known"
                ? "#f97316"
                : region.category === "middle"
                    ? "#adb5bd"
                    : "rgba(255,255,255,0.45)";
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
        if (!payload.quiz_id) return;
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
            if (changed) window.history.replaceState(window.history.state, "", url.toString());
        } catch {
            // Ignore URL manipulation failures.
        }
    }

    _syncActionRouteState(payload) {
        if (this.props.updateActionState && payload.quiz_id) {
            this.props.updateActionState(payload);
        }
    }

    indicatorClass(region) {
        const assessment = this.state.assessments[region.id];
        if (assessment) {
            const answer = region.answers.find((item) => item.id === assessment);
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
        const answer = region.answers.find((item) => item.id === assessment);
        return (answer?.answer_text || "").replace(/<[^>]+>/g, "").trim();
    }

    async closeViewer() {
        if (this.action?.restore) {
            await this.action.restore();
        } else {
            await this.props.close?.();
        }
    }
}

registry.category("actions").add("action_memory_reveal_game_js", MemoryRevealGame);
