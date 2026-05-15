/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EducationalGamesDashboard extends Component {
    static template = "educational_games_dashboard.DashboardTemplate";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            loading: true,
            error: "",
            stats: { total_quizzes: 0, total_questions: 0, total_responses: 0, active_students: 0 },
            recentQuizzes: [],
            recentActivity: [],
            strugglingQuestions: [],
            leaderboard: [],
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("quiz.quiz", "get_dashboard_data", []);
            this.state.stats = data.stats;
            this.state.recentQuizzes = data.recent_quizzes;
            this.state.recentActivity = data.recent_activity;
            this.state.strugglingQuestions = data.struggling_questions;
            this.state.leaderboard = data.leaderboard;
        } catch (err) {
            this.state.error = "Failed to load dashboard data. Please refresh the page.";
            console.error("Dashboard load error:", err);
        } finally {
            this.state.loading = false;
        }
    }

    formatDate(dateStr) {
        if (!dateStr) return "—";
        try {
            // Odoo datetimes are UTC, formatted as "YYYY-MM-DD HH:MM:SS"
            const d = new Date(dateStr.replace(" ", "T") + "Z");
            return d.toLocaleDateString(undefined, {
                year: "numeric",
                month: "short",
                day: "numeric",
            });
        } catch {
            return dateStr;
        }
    }

    truncate(text, maxLen = 80) {
        if (!text) return "—";
        return text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
    }

    pctBadgeClass(pct) {
        if (pct <= 30) return "bg-danger";
        if (pct <= 60) return "bg-warning text-dark";
        return "bg-success";
    }

    getDifficultyColor(pct) {
        if (pct <= 30) return "#dc3545";
        if (pct <= 60) return "#ffc107";
        return "#198754";
    }

    rankMedal(index) {
        if (index === 0) return "🥇";
        if (index === 1) return "🥈";
        if (index === 2) return "🥉";
        return String(index + 1);
    }

    openQuiz(quizId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "quiz.quiz",
            res_id: quizId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openQuestion(questionId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "quiz.question",
            res_id: questionId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openQuizList() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "All Quizzes",
            res_model: "quiz.quiz",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openQuestionList() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "All Questions",
            res_model: "quiz.question",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openResponseList() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "All Responses",
            res_model: "quiz.response",
            views: [[false, "list"]],
            target: "current",
        });
    }

    openStrugglingQuestions() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Struggling Questions",
            res_model: "quiz.question",
            domain: [["attempt_count", ">", 0]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openStudentResponses(userId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Student Responses",
            res_model: "quiz.response",
            domain: [["user_id", "=", userId]],
            views: [[false, "list"]],
            target: "current",
        });
    }

    openQuizWithActivity(quizId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "quiz.quiz",
            res_id: quizId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry
    .category("actions")
    .add("action_educational_games_dashboard_js", EducationalGamesDashboard);
