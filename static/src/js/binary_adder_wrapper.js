/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class BinaryAdderWrapper extends Component {
    static template = "binary_adder_wrapper.GameTemplate";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        // console.log('[BinaryAdderWrapper] Full this.props:', this.props);
        // console.log('[BinaryAdderWrapper] this.props.action:', this.props.action);
        
        const context = this.props.action.context || {};
        // console.log('[BinaryAdderWrapper] Extracted context:', context);
        // console.log('[BinaryAdderWrapper] Context keys:', Object.keys(context));
        // console.log('[BinaryAdderWrapper] active_id from context:', context.active_id);
        // console.log('[BinaryAdderWrapper] active_model from context:', context.active_model);
        
        // Build URL with query parameters if provided
        const params = new URLSearchParams();
        if (context.format) params.append('format', context.format);
        if (context.level) params.append('level', context.level);
        if (context.numCount) params.append('numCount', context.numCount);
        if (context.questionCount) params.append('questionCount', context.questionCount);
        if (context.active_id) params.append('active_id', context.active_id);
        if (context.active_model) params.append('active_model', context.active_model);
        if (context.submission_state) params.append('submission_state', context.submission_state);
        if (context.res_id) params.append('res_id', context.res_id);
        if (context.res_model) params.append('res_model', context.res_model);
        
        const queryString = params.toString();
        this.iframeUrl = `/educational_games/static/src/js/binary_adder/index.html${queryString ? '?' + queryString : ''}`;
        
    //     console.log('[BinaryAdderWrapper] Built iframe URL:', this.iframeUrl);
    //     console.log('[BinaryAdderWrapper] Query params:', Object.fromEntries(params));
    }
}

registry.category("actions").add("action_binary_adder_wrapper_js", BinaryAdderWrapper);
