/**
 * memory_reveal_setup.js
 *
 * Teacher setup viewer for Memory Reveal quizzes.
 * Extends ImageViewerDialog to reuse zoom/pan/image loading.
 * Adds: region drawing via highlight selection, naming popup, region list sidebar.
 */
import { _t } from "@web/core/l10n/translation";
import { onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ImageViewerDialog } from "@aui_enhancements/js/image_viewer_dialog";

const ZOOM_STEP = 0.08;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 5;

export class MemoryRevealSetup extends ImageViewerDialog {
    static template = "educational_games.MemoryRevealSetup";
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
        console.log("[MemoryRevealSetup] setup() called, props keys:", Object.keys(this.props));
        console.log("[MemoryRevealSetup] action keys:", Object.keys(this.props.action || {}));
        console.log("[MemoryRevealSetup] action.context:", this.props.action?.context);
        console.log("[MemoryRevealSetup] action.params:", this.props.action?.params);
        console.log("[MemoryRevealSetup] quizId from context:", this.props.action?.context?.default_quiz_id);

        // ImageViewerDialog.setup() expects props.imageConfig and props.close.
        // As a client action we don't have those, so provide safe defaults
        // BEFORE calling super.setup() so the parent can reference them.
        if (!this.props.imageConfig) {
            this.props.imageConfig = { directUrl: "" };
        }
        if (!this.props.close) {
            this.props.close = () => {};
        }

        // Call super.setup() — this initializes zoom/pan/drawing state
        // AND registers its own onMounted hook that calls loadCurrentImage().
        // Our override of loadCurrentImage() ensures quiz data is loaded
        // before the parent's image-loading pipeline runs.
        super.setup();

        this.notification = useService("notification");
        this.action = useService("action");

        // Additional state for memory reveal
        Object.assign(this.state, {
            quizId: parseInt(this.props.action?.context?.default_quiz_id, 10) || 0,
            quizName: "",
            regions: [],       // [{id, name, x1, y1, x2, y2, question_id}]
            addingRegion: false,
            namingRegion: null, // {x1,y1,x2,y2} pending naming
            regionNameInput: "",
            selectedRegionId: null,
            deletingId: null,
            editingRegionId: null,
            editingRegionName: "",
            namingDialogPosition: { x: 0, y: 0 },
            draggingNamingDialog: false,
        });

        // Override infoOpen to default to true (for highlight selection mode)
        this.state.infoOpen = true;

        this._onKeydown = async (ev) => {
            if (ev.key === "Escape") {
                if (this.state.namingRegion) {
                    this.state.namingRegion = null;
                    this.state.regionNameInput = "";
                } else {
                    await this.closeViewer();
                }
            }
        };
    }

    async mounted() {
        console.log("[MemoryRevealSetup] mounted() called");
        console.log("[MemoryRevealSetup] currentUrl:", this.state.currentUrl, "directUrl:", this.state.directUrl);
        await super.mounted?.();
        console.log("[MemoryRevealSetup] super.mounted done");
        window.addEventListener("keydown", this._onKeydown);
        // Fit the image after data loads
        setTimeout(() => this.fitWholeImage(), 200);
    }

    async willUnmount() {
        await super.willUnmount?.();
        window.removeEventListener("keydown", this._onKeydown);
        this._stopDraggingNamingDialog();
    }

    startDraggingNamingDialog(ev) {
        if (ev.button !== 0) return;
        ev.preventDefault();
        this._namingDialogDrag = {
            startX: ev.clientX,
            startY: ev.clientY,
            originX: this.state.namingDialogPosition.x,
            originY: this.state.namingDialogPosition.y,
        };
        this.state.draggingNamingDialog = true;
        this._onNamingDialogPointerMove = (moveEvent) => {
            const drag = this._namingDialogDrag;
            if (!drag) return;
            this.state.namingDialogPosition = {
                x: drag.originX + moveEvent.clientX - drag.startX,
                y: drag.originY + moveEvent.clientY - drag.startY,
            };
        };
        this._onNamingDialogPointerUp = () => this._stopDraggingNamingDialog();
        document.addEventListener("pointermove", this._onNamingDialogPointerMove);
        document.addEventListener("pointerup", this._onNamingDialogPointerUp, { once: true });
    }

    _stopDraggingNamingDialog() {
        if (this._onNamingDialogPointerMove) {
            document.removeEventListener("pointermove", this._onNamingDialogPointerMove);
        }
        if (this._onNamingDialogPointerUp) {
            document.removeEventListener("pointerup", this._onNamingDialogPointerUp);
        }
        this._onNamingDialogPointerMove = null;
        this._onNamingDialogPointerUp = null;
        this._namingDialogDrag = null;
        if (this.state) this.state.draggingNamingDialog = false;
    }

    namingDialogStyle() {
        const { x, y } = this.state.namingDialogPosition;
        return `transform:translate(${x}px, ${y}px);`;
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
        return super.loadCurrentImage();
    }

    async _loadQuizData() {
        console.log("[MemoryRevealSetup] _loadQuizData() called, quizId:", this.state.quizId);
        if (!this.state.quizId) {
            console.warn("[MemoryRevealSetup] No quizId, aborting");
            return;
        }
        try {
            console.log("[MemoryRevealSetup] ORM reading quiz.quiz id:", this.state.quizId);
            const [quiz] = await this.orm.read("quiz.quiz", [this.state.quizId], [
                "name", "quiz_type", "image_url", "question_ids",
            ]);
            console.log("[MemoryRevealSetup] ORM result:", JSON.stringify(quiz));
            this.state.quizName = quiz.name || "";

            // Set the image URL on the viewer state so it loads
            if (quiz.image_url) {
                console.log("[MemoryRevealSetup] Setting image URL:", quiz.image_url);
                this.state.currentUrl = quiz.image_url;
                this.state.directUrl = quiz.image_url;
            } else {
                console.warn("[MemoryRevealSetup] No image_url returned from ORM");
            }

            if (quiz.question_ids && quiz.question_ids.length > 0) {
                const questions = await this.orm.read("quiz.question", quiz.question_ids, [
                    "id", "question_text", "region_x1", "region_y1", "region_x2", "region_y2",
                ]);
                this.state.regions = questions.map(q => ({
                    id: q.id,
                    name: (q.question_text || "").replace(/<[^>]+>/g, "").trim() || `Region ${q.id}`,
                    x1: q.region_x1,
                    y1: q.region_y1,
                    x2: q.region_x2,
                    y2: q.region_y2,
                    question_id: q.id,
                }));
            }
        } catch (e) {
            console.error("[MemoryRevealSetup] Failed to load quiz data:", e);
        }
    }

    // ── Override highlight completion to create regions ─────────────────────

    /**
     * Called when the user finishes drawing a highlight selection.
     * Instead of storing it as a highlight, we open the naming dialog.
     */
    _onHighlightComplete(box) {
        // Convert pixel coords to percentages
        if (!this.state.imageWidth || !this.state.imageHeight) return;
        const region = {
            x1: +(box.x1 / this.state.imageWidth * 100).toFixed(2),
            y1: +(box.y1 / this.state.imageHeight * 100).toFixed(2),
            x2: +(box.x2 / this.state.imageWidth * 100).toFixed(2),
            y2: +(box.y2 / this.state.imageHeight * 100).toFixed(2),
        };
        this.state.namingRegion = region;
        this.state.regionNameInput = "";
        // Clear the highlight preview
        this.state.selectingHighlight = false;
        this.state.selectionPreview = null;
        this.state.selectionStart = null;
    }

    async confirmRegionName() {
        const name = (this.state.regionNameInput || "").trim();
        if (!name || !this.state.namingRegion) return;

        const r = this.state.namingRegion;
        try {
            // Create a quiz.question with the region coordinates
            const [question] = await this.orm.create("quiz.question", [{
                all_quiz_ids: [this.state.quizId],
                question_text: name,
                marks: 1,
                region_x1: r.x1,
                region_y1: r.y1,
                region_x2: r.x2,
                region_y2: r.y2,
            }]);

            // Auto-create the 3 traffic-light answers (green/orange/red)
            await this.orm.call("quiz.question", "ensure_memory_reveal_answers", [question]);
            this.state.regions.push({
                id: question,
                name: name,
                x1: r.x1,
                y1: r.y1,
                x2: r.x2,
                y2: r.y2,
                question_id: question,
            });
            this.notification.add(_t("Region created") + ": " + name, { type: "success" });
        } catch (e) {
            console.error("[MemoryRevealSetup] Failed to create region:", e);
            this.notification.add(_t("Failed to create region"), { type: "danger" });
        }

        this.state.namingRegion = null;
        this.state.regionNameInput = "";
    }

    cancelRegionName() {
        this.state.namingRegion = null;
        this.state.regionNameInput = "";
    }

    onNameInputKeydown(ev) {
        if (ev.key === "Enter") {
            this.confirmRegionName();
        } else if (ev.key === "Escape") {
            this.cancelRegionName();
        }
    }

    startEditingRegion(region) {
        this.state.selectedRegionId = region.id;
        this.state.editingRegionId = region.id;
        this.state.editingRegionName = region.name;
        this._zoomToRegion(region);
    }

    cancelEditingRegion() {
        this.state.editingRegionId = null;
        this.state.editingRegionName = "";
    }

    async saveRegionName(region) {
        if (this.state.editingRegionId !== region.id) return;

        const name = (this.state.editingRegionName || "").trim();
        if (!name) {
            this.cancelEditingRegion();
            return;
        }

        try {
            await this.orm.write("quiz.question", [region.question_id], {
                question_text: name,
            });
            region.name = name;
            this.notification.add(_t("Region name updated"), { type: "success" });
        } catch (e) {
            console.error("[MemoryRevealSetup] Failed to update region name:", e);
            this.notification.add(_t("Failed to update region name"), { type: "danger" });
        }
        this.cancelEditingRegion();
    }

    onRegionNameKeydown(ev, region) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.saveRegionName(region);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.cancelEditingRegion();
        }
    }

    // ── Region management ──────────────────────────────────────────────────

    selectRegion(region) {
        this.state.selectedRegionId = region.id;
        // Zoom to the region
        this._zoomToRegion(region);
    }

    _zoomToRegion(region) {
        if (!this.state.imageWidth || !this.state.imageHeight) return;
        const x1 = region.x1 / 100 * this.state.imageWidth;
        const y1 = region.y1 / 100 * this.state.imageHeight;
        const x2 = region.x2 / 100 * this.state.imageWidth;
        const y2 = region.y2 / 100 * this.state.imageHeight;
        const centerX = (x1 + x2) / 2;
        const centerY = (y1 + y2) / 2;
        const width = x2 - x1;
        const height = y2 - y1;
        const stageEl = this.stageRef?.el;
        if (!stageEl) return;
        const rect = stageEl.getBoundingClientRect();
        const zoom = Math.min(
            MAX_ZOOM,
            Math.max(MIN_ZOOM, Math.min((rect.width * 0.8) / width, (rect.height * 0.8) / height))
        );
        const imageCenterX = this.state.imageWidth / 2;
        const imageCenterY = this.state.imageHeight / 2;
        this._setViewTransform({
            zoom,
            offsetX: -((centerX - imageCenterX) * zoom),
            offsetY: -((centerY - imageCenterY) * zoom),
        });
    }

    async deleteRegion(region) {
        if (!confirm(`Delete region "${region.name}"?`)) return;
        try {
            await this.orm.unlink("quiz.question", [region.question_id]);
            this.state.regions = this.state.regions.filter(r => r.id !== region.id);
            if (this.state.selectedRegionId === region.id) {
                this.state.selectedRegionId = null;
            }
            this.notification.add(_t("Region deleted"), { type: "info" });
        } catch (e) {
            console.error("[MemoryRevealSetup] Failed to delete region:", e);
        }
    }

    // ── Region overlay styling ─────────────────────────────────────────────

    regionOverlayStyle(region) {
        const left = region.x1;
        const top = region.y1;
        const width = region.x2 - region.x1;
        const height = region.y2 - region.y1;
        const selected = region.id === this.state.selectedRegionId;
        const borderColor = selected ? "#22c55e" : "#ef4444";
        const bg = selected ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.1)";
        return `position:absolute;left:${left}%;top:${top}%;width:${width}%;height:${height}%;border:4px solid ${borderColor};background:${bg};pointer-events:none;`;
    }

    // ── Override onPointerUp to intercept highlight completion ──────────────

    onPointerUp(ev) {
        // If we were selecting a highlight and now finished, intercept
        if (this.state.selectingHighlight && this.state.selectionPreview) {
            const box = this.state.selectionPreview;
            const width = Math.abs(box.x2 - box.x1);
            const height = Math.abs(box.y2 - box.y1);
            // Only if the selection is meaningful (not a click)
            if (width > 5 && height > 5) {
                super.onPointerUp(ev);
                // Normalize the box
                const normalized = {
                    x1: Math.min(box.x1, box.x2),
                    y1: Math.min(box.y1, box.y2),
                    x2: Math.max(box.x1, box.x2),
                    y2: Math.max(box.y1, box.y2),
                };
                this._onHighlightComplete(normalized);
                return;
            }
        }
        super.onPointerUp(ev);
    }

    // ── Close override ─────────────────────────────────────────────────────

    async closeViewer() {
        // As a client action, navigate back to the quiz form
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

// Register as a client action
import { registry } from "@web/core/registry";
registry.category("actions").add("action_memory_reveal_setup_js", MemoryRevealSetup);
