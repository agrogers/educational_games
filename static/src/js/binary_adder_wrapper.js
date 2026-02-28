/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class BinaryAdderWrapper extends Component {
    static template = "binary_adder_wrapper.GameTemplate";

    setup() {
        const context = this.props.action.context || {};
        
        // Build URL with query parameters if provided
        const params = new URLSearchParams();
        if (context.format) params.append('format', context.format);
        if (context.level) params.append('level', context.level);
        if (context.numCount) params.append('numCount', context.numCount);
        if (context.questionCount) params.append('questionCount', context.questionCount);
        
        const queryString = params.toString();
        this.iframeUrl = `/educational_games/static/src/js/binary_adder/index.html${queryString ? '?' + queryString : ''}`;
    }
}

registry.category("actions").add("action_binary_adder_wrapper_js", BinaryAdderWrapper);
