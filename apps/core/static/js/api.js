class ApiError extends Error {
    constructor(message, status, errors) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.errors = errors || null;
    }
}

function apiUrl(endpoint) {
    const base = window.AutoFlowConfig?.apiBaseUrl || '/api/';
    return `${base}${endpoint.replace(/^\//, '')}`;
}

function extractDetail(payload) {
    if (!payload || typeof payload !== 'object') return null;
    if (typeof payload.detail === 'string') return payload.detail;
    return null;
}

function extractFieldErrors(payload) {
    if (!payload || typeof payload !== 'object') return null;
    const fields = {};
    let hasFieldErrors = false;

    for (const [key, value] of Object.entries(payload)) {
        if (key === 'detail') continue;
        fields[key] = Array.isArray(value) ? value.join(' ') : String(value);
        hasFieldErrors = true;
    }

    return hasFieldErrors ? fields : null;
}

async function readBody(response) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        const text = await response.text();
        return text || null;
    }
    try {
        return await response.json();
    } catch (err) {
        return null;
    }
}

async function apiRequest(endpoint, options = {}, allowSessionRetry = true) {
    const { method = 'GET', body = null, query = null, headers: extraHeaders = {} } = options;

    if (!window.AutoFlowAuth) {
        throw new ApiError('You need to sign in to continue.', 401);
    }

    const session = await window.AutoFlowAuth.getSession();
    if (!session) {
        window.location.href = `/login/?redirect=${encodeURIComponent(window.location.pathname)}`;
        throw new ApiError('Your session has expired. Please sign in again.', 401);
    }

    let url = apiUrl(endpoint);
    if (query) {
        const params = new URLSearchParams();
        for (const [key, value] of Object.entries(query)) {
            if (value !== undefined && value !== null && value !== '') {
                params.append(key, value);
            }
        }
        const queryString = params.toString();
        if (queryString) url += `?${queryString}`;
    }

    const headers = {
        'Accept': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
        ...extraHeaders,
    };

    const config = { method, headers };

    if (body !== null && !(body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        config.body = JSON.stringify(body);
    } else if (body instanceof FormData) {
        config.body = body;
    }

    let response;
    try {
        response = await fetch(url, config);
    } catch (err) {
        throw new ApiError('Unable to reach the server. Please check your connection.', 0);
    }

    if (response.status === 204) return null;

    const payload = await readBody(response);

    if (response.ok) return payload;

    if (response.status === 401) {
        if (allowSessionRetry) {
            const refreshed = await window.AutoFlowAuth.refreshSession();
            if (refreshed) {
                return apiRequest(endpoint, options, false);
            }
        }

        window.location.href = `/login/?redirect=${encodeURIComponent(window.location.pathname)}`;
        throw new ApiError('Your session has expired. Please sign in again.', 401);
    }

    if (response.status === 403) {
        throw new ApiError(
            extractDetail(payload) || 'You do not have permission to perform this action.',
            403
        );
    }

    if (response.status === 404) {
        throw new ApiError(extractDetail(payload) || 'The requested resource was not found.', 404);
    }

    if (response.status === 400) {
        throw new ApiError(
            extractDetail(payload) || 'Please check the highlighted fields and try again.',
            400,
            extractFieldErrors(payload)
        );
    }

    throw new ApiError('Something went wrong on our end. Please try again later.', 500);
}

const api = {
    health: () => apiRequest('health/'),
    me: () => apiRequest('me/'),
    dashboard: () => apiRequest('dashboard/'),
    vehicles: {
        available: (filters = {}) => apiRequest('vehicles/available/', { query: filters }),
        inventory: (filters = {}) => apiRequest('vehicles/', { query: filters }),
        create: (data) => apiRequest('vehicles/', { method: 'POST', body: data }),
        update: (id, data) => apiRequest(`vehicles/${id}/`, { method: 'PATCH', body: data }),
        deactivate: (id) => apiRequest(`vehicles/${id}/`, { method: 'DELETE' }),
    },
    appointments: {
        list: (filters = {}) => apiRequest('appointments/', { query: filters }),
        createTestDrive: (data) => apiRequest('appointments/test-drives/', { method: 'POST', body: data }),
        updateStatus: (id, nextStatus) => apiRequest(`appointments/${id}/status/`, { method: 'PATCH', body: { status: nextStatus } }),
    },
    employees: {
        list: () => apiRequest('employees/'),
        create: (data) => apiRequest('employees/', { method: 'POST', body: data }),
        update: (id, data) => apiRequest(`employees/${id}/`, { method: 'PATCH', body: data }),
        deactivate: (id) => apiRequest(`employees/${id}/`, { method: 'DELETE' }),
    },
    technicians: {
        list: () => apiRequest('technicians/'),
        create: (data) => apiRequest('technicians/', { method: 'POST', body: data }),
        update: (id, data) => apiRequest(`technicians/${id}/`, { method: 'PATCH', body: data }),
    },
    serviceRequests: {
        list: (filters = {}) => apiRequest('service-requests/', { query: filters }),
        create: (data) => apiRequest('service-requests/', { method: 'POST', body: data }),
        assignments: (id) => apiRequest(`service-requests/${id}/assignments/`),
        assign: (id, data) => apiRequest(`service-requests/${id}/assignments/`, { method: 'POST', body: data }),
    },
    technicianAssignments: {
        list: (filters = {}) => apiRequest('technician-assignments/', { query: filters }),
        start: (id) => apiRequest(`technician-assignments/${id}/`, { method: 'POST', body: { action: 'start' } }),
        complete: (id, data) => apiRequest(`technician-assignments/${id}/`, { method: 'POST', body: { action: 'complete', ...data } }),
    },
    customerVehicles: {
        list: () => apiRequest('customer/vehicles/'),
        create: (data) => apiRequest('customer/vehicles/', { method: 'POST', body: data }),
    },
    yourspinny: {
        recommendations: (data) => apiRequest('yourspinny/recommendations/', { method: 'POST', body: data }),
        compare: (data) => apiRequest('yourspinny/compare/', { method: 'POST', body: data }),
        query: (data) => apiRequest('yourspinny/query/', { method: 'POST', body: data }),
        ask: (data) => apiRequest('yourspinny/ask/', { method: 'POST', body: data }),
    },
};

window.AutoFlowAPI = api;
window.AutoFlowApiError = ApiError;