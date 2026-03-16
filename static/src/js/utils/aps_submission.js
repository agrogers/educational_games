/**
 * aps_submission.js — Shared utilities for saving game/quiz results to
 * aps.resource.submission records.
 *
 * This module is imported by all OWL game/quiz components in this addon so
 * that the ORM-write and toast-notification logic is written once and reused,
 * rather than being copied into every game component.
 *
 * ── How to use in a game component ────────────────────────────────────────
 *
 *   import {
 *       APS_SUBMISSION_MODEL,
 *       saveToApsSubmission,
 *       createSubmissionCopy,
 *   } from "@educational_games/js/utils/aps_submission";
 *
 *   // In setup():
 *   this.orm          = useService("orm");
 *   this.notification = useService("notification");
 *   this.resId        = context.active_id;
 *   this.resModel     = context.active_model;
 *   this.isValidSubmission = this.resModel === APS_SUBMISSION_MODEL && !!this.resId;
 *
 *   // When the game/quiz finishes:
 *   const saved = await saveToApsSubmission(
 *       this.orm, this.notification, this.resId, score, htmlReport, outOfMarks
 *   );
 * ──────────────────────────────────────────────────────────────────────────
 */

/** Odoo model name for student submissions in the APEX (aps_sis) module. */
export const APS_SUBMISSION_MODEL = "aps.resource.submission";

/**
 * Write final results to an aps.resource.submission record.
 *
 * Sets score, answer (HTML report), and state = "submitted".
 * Displays a success or error toast notification automatically.
 *
 * @param {Object} orm           - ORM service obtained via useService("orm").
 * @param {Object} notification  - Notification service via useService("notification").
 * @param {number} submissionId  - ID of the submission record to update.
 * @param {number} score         - Numeric score to store.
 * @param {string} htmlReport    - HTML string stored in the answer field.
 * @param {number|null} outOfMarks - Total marks for this attempt (updates out_of_marks). Pass null to skip.
 * @returns {Promise<boolean>}   - true on success, false on failure.
 */
export async function saveToApsSubmission(orm, notification, submissionId, score, htmlReport, outOfMarks = null) {
    try {
        const vals = {
            score,
            answer: htmlReport,
            state: "submitted",
        };
        if (outOfMarks !== null && outOfMarks !== undefined) {
            vals.out_of_marks = outOfMarks;
        }
        await orm.write(APS_SUBMISSION_MODEL, [submissionId], vals);
        notification.add("Results saved successfully!", { type: "success" });
        return true;
    } catch (error) {
        console.error("Error saving to aps.resource.submission:", error);
        notification.add("Error saving results. Please contact your teacher.", { type: "danger" });
        return false;
    }
}

/**
 * Create a copy of an existing aps.resource.submission for re-submission.
 *
 * Calls quiz.quiz.create_submission_copy() on the server, which uses the
 * ORM copy() method to duplicate the original record with all required fields
 * preserved, but with the due date cleared so the student gets a fresh attempt.
 *
 * The new submission is returned in state "assigned" with score/answer cleared,
 * ready to receive fresh results via saveToApsSubmission().
 *
 * @param {Object} orm           - ORM service.
 * @param {Object} notification  - Notification service.
 * @param {number} sourceId      - ID of the submission to copy from.
 * @returns {Promise<number|null>} - New submission ID, or null on failure.
 */
export async function createSubmissionCopy(orm, notification, sourceId) {
    try {
        return await orm.call("quiz.quiz", "create_submission_copy", [sourceId]);
    } catch (error) {
        console.error("Error creating resubmission copy:", error);
        notification.add("Error creating resubmission. Please contact your teacher.", { type: "danger" });
        return null;
    }
}
