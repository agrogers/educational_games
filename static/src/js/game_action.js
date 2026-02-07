/** @odoo-module **/
import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StudentGame extends Component {
    static template = "student_game.GameTemplate";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ score: 0 });
        this.canvasRef = useRef("gameCanvas");

        onMounted(() => {
            this.drawGame();
        });
    }

    drawGame() {
        const ctx = this.canvasRef.el.getContext("2d");
        ctx.fillStyle = "#00A09D"; // Odoo Teal
        ctx.fillRect(50, 50, 100, 100);
    }

    addPoints() {
        this.state.score += 10;
    }

    async submitScore() {
        await this.orm.call("game.result", "save_score", [this.state.score]);
        this.notification.add("Score saved to LMS!", { type: "success" });
    }
}

registry.category("actions").add("action_student_game_js", StudentGame);