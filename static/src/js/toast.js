/**
 * Show a styled toast notification similar to Odoo's notification system
 * Supports both plain text and HTML formatted messages
 * 
 * @param {string} type - Toast type: 'success', 'danger', 'warning', 'info'
 * @param {string} title - Toast header title (plain text)
 * @param {string} message - Toast body message (supports HTML)
 */
function showOdooLikeToast(type = 'success', title = 'Done', message = 'Operation completed') {
    const colors = {
        success: 'bg-success',
        danger:  'bg-danger',
        warning: 'bg-warning text-dark',
        info:    'bg-info'
    };

    const toastEl = document.getElementById('customToast');
    if (!toastEl) return;

    // Update classes & content
    const header = toastEl.querySelector('.toast-header');
    header.className = `toast-header ${colors[type] || 'bg-primary'} text-white`;
    header.querySelector('.me-auto').textContent = title;

    // Support both plain text and formatted HTML in message
    toastEl.querySelector('.toast-body').innerHTML = message;

    // Determine autohide: true for success/info, false for danger/warning
    const shouldAutoHide = type === 'success' || type === 'info';

    // Show it
    const toast = new bootstrap.Toast(toastEl, {
        autohide: shouldAutoHide,
        delay: 5000
    });
    toast.show();
}

/**
 * Initialize toast container - creates the DOM element automatically if it doesn't exist
 */
function initializeToastContainer() {
    // Check if toast container already exists
    if (document.getElementById('customToast')) {
        return;
    }

    // Create the toast HTML structure
    const toastHTML = `
        <div aria-live="polite" aria-atomic="true" class="position-fixed top-0 end-0 p-3" style="z-index: 9999;">
            <div id="customToast" class="toast bg-white border-0 shadow" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header bg-success text-white">
                    <strong class="me-auto">Success</strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body text-dark">
                    Your action was successful!
                </div>
            </div>
        </div>
    `;

    // Append to body
    document.body.insertAdjacentHTML('beforeend', toastHTML);
}

// Auto-initialize when script loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeToastContainer);
} else {
    initializeToastContainer();
}
