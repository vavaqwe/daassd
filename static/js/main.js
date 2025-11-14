// Main JavaScript for XT Trading Bot

// Global variables
let refreshInterval;
let isPageVisible = true;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Set up page visibility detection
    document.addEventListener('visibilitychange', function() {
        isPageVisible = !document.hidden;
        if (isPageVisible) {
            // Resume updates when page becomes visible
            resumeUpdates();
        } else {
            // Pause updates when page is hidden
            pauseUpdates();
        }
    });

    // Add loading states to all buttons
    setupLoadingStates();
    
    // Initialize tooltips
    initializeTooltips();
    
    // Set up WebSocket connection for real-time updates
    // setupWebSocket();
}

function setupLoadingStates() {
    const buttons = document.querySelectorAll('[data-loading]');
    buttons.forEach(button => {
        button.addEventListener('click', function() {
            showButtonLoading(this);
        });
    });
}

function showButtonLoading(button) {
    const originalText = button.innerHTML;
    button.setAttribute('data-original-text', originalText);
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Завантаження...';
    button.disabled = true;
    
    // Auto-restore after 3 seconds if not manually restored
    setTimeout(() => {
        if (button.disabled) {
            restoreButton(button);
        }
    }, 3000);
}

function restoreButton(button) {
    const originalText = button.getAttribute('data-original-text');
    if (originalText) {
        button.innerHTML = originalText;
        button.disabled = false;
        button.removeAttribute('data-original-text');
    }
}

function initializeTooltips() {
    // Initialize Bootstrap tooltips
    const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltips.forEach(tooltip => {
        new bootstrap.Tooltip(tooltip);
    });
}

function resumeUpdates() {
    // Resume any auto-refresh intervals
    if (typeof loadDashboardData === 'function') {
        loadDashboardData();
    }
}

function pauseUpdates() {
    // Clear any intervals when page is not visible to save resources
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
}

// Utility functions
function formatCurrency(amount, currency = 'USD') {
    return new Intl.NumberFormat('uk-UA', {
        style: 'currency',
        currency: currency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 4
    }).format(amount);
}

function formatPercent(value) {
    return (value > 0 ? '+' : '') + value.toFixed(2) + '%';
}

function formatTime(timestamp) {
    return new Date(timestamp).toLocaleTimeString('uk-UA', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

function formatDate(timestamp) {
    return new Date(timestamp).toLocaleDateString('uk-UA', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Show toast notifications
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.id = toastId;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-${getIconForType(type)} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, {
        autohide: true,
        delay: 5000
    });
    
    bsToast.show();
    
    // Remove toast element after it's hidden
    toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
    });
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
    return container;
}

function getIconForType(type) {
    const icons = {
        'success': 'check-circle',
        'danger': 'exclamation-triangle',
        'warning': 'exclamation-circle',
        'info': 'info-circle',
        'primary': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

// API helper functions
function fetchAPI(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    return fetch(endpoint, { ...defaultOptions, ...options })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .catch(error => {
            console.error('API Error:', error);
            showToast('Помилка з\'єднання з сервером', 'danger');
            throw error;
        });
}

// Form validation
function validateForm(form) {
    const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('is-invalid');
            isValid = false;
        } else {
            input.classList.remove('is-invalid');
        }
    });
    
    return isValid;
}

// Export for use in other scripts
window.tradingBot = {
    formatCurrency,
    formatPercent,
    formatTime,
    formatDate,
    showToast,
    fetchAPI,
    validateForm,
    showButtonLoading,
    restoreButton
};