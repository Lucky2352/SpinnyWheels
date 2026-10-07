document.addEventListener('DOMContentLoaded', function() {
    initMobileSidebar();
    initModals();
    initDropdowns();
    initLogout();
    initChangeEmail();
    initAuthGuard();
});

function initMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarOverlay = document.getElementById('sidebarOverlay');

    if (!sidebarToggle || !sidebar || !sidebarOverlay) return;

    sidebarToggle.addEventListener('click', function() {
        const isOpen = sidebar.classList.toggle('-translate-x-full');
        sidebarOverlay.classList.toggle('hidden');
        sidebarToggle.setAttribute('aria-expanded', !isOpen);
    });

    sidebarOverlay.addEventListener('click', function() {
        sidebar.classList.add('-translate-x-full');
        sidebarOverlay.classList.add('hidden');
        sidebarToggle.setAttribute('aria-expanded', 'false');
    });
}

function initModals() {
    document.querySelectorAll('[data-modal-toggle]').forEach(trigger => {
        const targetId = trigger.getAttribute('data-modal-toggle');
        const modal = document.getElementById(targetId);
        if (!modal) return;

        trigger.addEventListener('click', function(e) {
            e.preventDefault();
            openModal(modal);
        });

        modal.querySelectorAll('[data-modal-close]').forEach(closeBtn => {
            closeBtn.addEventListener('click', function() {
                closeModal(modal);
            });
        });

        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeModal(modal);
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal.open').forEach(closeModal);
        }
    });
}

function openModal(modal) {
    modal.classList.add('open');
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    modal.focus();
}

function closeModal(modal) {
    modal.classList.remove('open');
    modal.classList.add('hidden');
    document.body.style.overflow = '';
}

function initDropdowns() {
    document.querySelectorAll('[data-dropdown-toggle]').forEach(trigger => {
        const targetId = trigger.getAttribute('data-dropdown-toggle');
        const dropdown = document.getElementById(targetId);
        if (!dropdown) return;

        trigger.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            closeAllDropdowns();
            dropdown.classList.toggle('hidden');
        });
    });

    document.addEventListener('click', closeAllDropdowns);
}

function closeAllDropdowns() {
    document.querySelectorAll('[data-dropdown].open').forEach(d => d.classList.add('hidden'));
}

function initLogout() {
    const logoutBtn = document.getElementById('logoutBtn');
    if (!logoutBtn || !window.AutoFlowAuth) return;

    logoutBtn.disabled = true;

    window.AutoFlowAuth.getSession().then(session => {
        if (session) logoutBtn.disabled = false;
    });

    logoutBtn.addEventListener('click', async function() {
        if (logoutBtn.disabled) return;
        logoutBtn.disabled = true;
        await window.AutoFlowAuth.signOut();
    });
}

function initChangeEmail() {
    const form = document.getElementById('emailForm');
    const input = document.getElementById('emailInput');
    const hint = document.getElementById('emailHint');
    if (!form || !input || !hint || !window.AutoFlowAuth) return;

    const trigger = document.querySelector('[data-email-open]');

    if (trigger) {
        trigger.addEventListener('click', async function() {
            const user = await window.AutoFlowAuth.getUser();
            if (user && user.email) {
                input.value = user.email;
            }
        });
    }

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        if (form.dataset.submitting === 'true') return;

        const email = input.value.trim();

        if (!email) {
            window.AutoFlowUI.showFormError(form, 'Please enter your new email address.');
            return;
        }

        const current = await window.AutoFlowAuth.getUser();
        if (current && current.email && current.email.toLowerCase() === email.toLowerCase()) {
            window.AutoFlowUI.showFormError(form, 'That is already your current email address.');
            return;
        }

        form.dataset.submitting = 'true';
        window.AutoFlowUI.setSubmitting(form, true, 'Updating...');
        window.AutoFlowUI.clearFormError(form);

        try {
            const { error } = await window.AutoFlowAuth.changeEmail(email);

            if (error) {
                window.AutoFlowUI.showFormError(form, error.message || 'Could not change your email.');
                return;
            }

            window.AutoFlowUI.showToast('Check your inbox to confirm the new email address.');
            hint.textContent = 'We sent a confirmation link to ' + email + '. Open it to finish the change.';
            input.value = '';
        } catch (err) {
            window.AutoFlowUI.showFormError(form, 'Could not change your email. Please try again.');
        } finally {
            form.dataset.submitting = 'false';
            window.AutoFlowUI.setSubmitting(form, false);
        }
    });
}

async function initAuthGuard() {
    if (!window.AutoFlowAuth) return;

    window.AutoFlowAuth.updateAuthUI();

    if (document.body.dataset.protectedPage !== 'true') return;

    document.body.dataset.authResolved = 'false';

    const session = await window.AutoFlowAuth.getSession();

    if (session) {
        document.body.dataset.authResolved = 'true';
        initRoleUi();
        return;
    }

    await new Promise(resolve => setTimeout(resolve, 1000));

    const retrySession = await window.AutoFlowAuth.getSession();

    if (retrySession) {
        document.body.dataset.authResolved = 'true';
        initRoleUi();
        return;
    }

    window.location.href = `/login/?redirect=${encodeURIComponent(window.location.pathname)}`;
}
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const inrFormatter = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
});

function formatMoney(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return '-';
    return inrFormatter.format(amount);
}

function formatDate(value) {
    if (!value) return '-';
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function formatDateTime(value) {
    if (!value) return '-';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function formatRelative(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '';
    const seconds = Math.round((Date.now() - parsed.getTime()) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 7) return `${days}d ago`;
    const weeks = Math.round(days / 7);
    if (weeks < 5) return `${weeks}w ago`;
    return formatDate(value);
}

function todayIso() {
    const now = new Date();
    const offset = now.getTimezoneOffset();
    return new Date(now.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function appointmentStatusBadge(status) {
    const styles = {
        PENDING: 'bg-amber-100 text-amber-800',
        CONFIRMED: 'bg-green-100 text-green-800',
        IN_PROGRESS: 'bg-blue-100 text-blue-800',
        COMPLETED: 'bg-green-100 text-green-800',
        CANCELLED: 'bg-red-100 text-red-800',
    };
    return styles[status] || 'bg-slate-100 text-slate-800';
}

function priorityBadge(priority) {
    const styles = {
        LOW: 'bg-green-100 text-green-800',
        MEDIUM: 'bg-amber-100 text-amber-800',
        HIGH: 'bg-orange-100 text-orange-800',
        URGENT: 'bg-red-100 text-red-800',
    };
    return styles[priority] || 'bg-slate-100 text-slate-800';
}

function serviceStatusBadge(status) {
    const styles = {
        PENDING: 'bg-amber-100 text-amber-800',
        CONFIRMED: 'bg-green-100 text-green-800',
        IN_PROGRESS: 'bg-blue-100 text-blue-800',
        COMPLETED: 'bg-green-100 text-green-800',
        CANCELLED: 'bg-red-100 text-red-800',
    };
    return styles[status] || 'bg-slate-100 text-slate-800';
}

function setContainerState(container, state, options = {}) {
    if (!container) return;

    const loading = container.querySelector('[data-state="loading"]');
    const empty = container.querySelector('[data-state="empty"]');
    const error = container.querySelector('[data-state="error"]');
    const content = container.querySelector('[data-state="content"]');

    [loading, empty, error].forEach(el => {
        if (el) el.classList.add('hidden');
    });
    if (content) content.classList.add('hidden');

    if (state === 'loading' && loading) loading.classList.remove('hidden');
    if (state === 'empty' && empty) {
        empty.classList.remove('hidden');
        if (options.emptyText && empty.querySelector('[data-empty-text]')) {
            empty.querySelector('[data-empty-text]').textContent = options.emptyText;
        }
    }
    if (state === 'error' && error) {
        error.classList.remove('hidden');
        if (options.errorText && error.querySelector('[data-error-text]')) {
            error.querySelector('[data-error-text]').textContent = options.errorText;
        }
    }
    if (state === 'content' && content) content.classList.remove('hidden');
}

function errorMessageFor(err) {
    if (err && err.status === 0) return 'Unable to reach the server. Please check your connection.';
    if (err && err.message) return err.message;
    return 'Something went wrong. Please try again.';
}

function showFormError(form, message) {
    if (!form) return;
    let box = form.querySelector('[data-form-error]');
    if (!box) {
        box = document.createElement('div');
        box.setAttribute('data-form-error', '');
        box.className = 'hidden rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700';
        form.prepend(box);
    }
    box.textContent = message;
    box.classList.remove('hidden');
}

function clearFormError(form) {
    if (!form) return;
    const box = form.querySelector('[data-form-error]');
    if (box) box.classList.add('hidden');
}

function setSubmitting(form, submitting, pendingLabel) {
    if (!form) return;
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;

    if (submitting) {
        button.dataset.originalLabel = button.innerHTML;
        button.disabled = true;
        button.innerHTML = `<svg class="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>${pendingLabel || 'Submitting...'}`;
    } else {
        button.disabled = false;
        if (button.dataset.originalLabel) {
            button.innerHTML = button.dataset.originalLabel;
        }
    }
}

function showToast(message, tone = 'success') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'fixed bottom-6 right-6 z-[60] flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const tones = {
        success: 'bg-green-600 text-white',
        error: 'bg-red-600 text-white',
        info: 'bg-slate-800 text-white',
    };

    const toast = document.createElement('div');
    toast.className = `${tones[tone] || tones.info} rounded-lg px-4 py-3 text-sm font-medium shadow-lg`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 4000);
}

const roleState = { user: null, loaded: false };

async function loadCurrentUser() {
    if (roleState.loaded) return roleState.user;
    if (!window.AutoFlowAPI) return null;

    try {
        roleState.user = await window.AutoFlowAPI.me();
    } catch (err) {
        roleState.user = null;
    }

    roleState.loaded = true;
    return roleState.user;
}

function applyRoleVisibility(user) {
    const showOwner = Boolean(user?.can_manage_inventory);
    const showStaff = Boolean(user?.is_employee) && !user?.is_technician;
    const showTechnician = Boolean(user?.is_technician);

    document.querySelectorAll('[data-owner-only]').forEach((element) => {
        element.classList.toggle('hidden', !showOwner);
    });
    document.querySelectorAll('[data-customer-only]').forEach((element) => {
        element.classList.toggle('hidden', !user?.is_customer);
    });
    document.querySelectorAll('[data-staff-only]').forEach((element) => {
        element.classList.toggle('hidden', !showStaff);
    });
    document.querySelectorAll('[data-technician-only]').forEach((element) => {
        element.classList.toggle('hidden', !showTechnician);
    });

    return showOwner;
}

async function initRoleUi() {
    const user = await loadCurrentUser();
    return applyRoleVisibility(user);
}

window.AutoFlowUI = {
    escapeHtml,
    formatMoney,
    formatDate,
    formatDateTime,
    formatRelative,
    todayIso,
    appointmentStatusBadge,
    priorityBadge,
    serviceStatusBadge,
    setContainerState,
    errorMessageFor,
    showFormError,
    clearFormError,
    setSubmitting,
    showToast,
    openModal,
    closeModal,
    loadCurrentUser,
    applyRoleVisibility,
    initRoleUi,
};