/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Generic HTML/JS Game Iframe Wrapper
 * 
 * This component renders an HTML/JS game in an iframe and forwards context to it.
 * 
 * Usage:
 * 1. Define an action in actions.xml:
 *    <record id="action_my_game" model="ir.actions.client">
 *        <field name="name">My Game</field>
 *        <field name="tag">action_html_game_wrapper_js</field>
 *        <field name="context">{
 *            'game_path': '/educational_games/static/src/js/my_game/index.html',
 *            'format': 'default',
 *            'level': 1
 *        }</field>
 *    </record>
 * 
 * 2. The wrapper will automatically forward all context params to the game via URL
 */
export class HtmlGameWrapper extends Component {
    static template = "html_game_wrapper.GameTemplate";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        // debugger;
        const context = this.props.action.context || {};
        
        // Get the game path from context - required for determining which game to load
        const gamePath = context.game_path ;
        
        // Build URL with all context parameters as query params
        const params = new URLSearchParams();
        
        // Add all context parameters to URL - the game can use what it needs
        for (const [key, value] of Object.entries(context)) {
            if (key !== 'game_path' && value !== null && value !== undefined) {
                params.append(key, value);
            }
        }
        
        const queryString = params.toString();
        this.iframeUrl = `${gamePath}${queryString ? '?' + queryString : ''}`;
    }
}

// Register the generic wrapper - can be used by any HTML/JS game
registry.category("actions").add("action_html_game_wrapper_js", HtmlGameWrapper);

// // For backward compatibility, also register with the specific binary_adder name
// registry.category("actions").add("action_binary_adder_wrapper_js", HtmlGameWrapper);
