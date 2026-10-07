// AutoFlow Supabase Client
// Single shared Supabase client instance for the entire application

let supabaseClient = null;
let isInitialized = false;

function getSupabaseClient() {
    if (!isInitialized) {
        if (!window.AutoFlowConfig || !window.AutoFlowConfig.supabaseUrl || !window.AutoFlowConfig.supabasePublishableKey) {
            console.warn('AutoFlowConfig not properly configured. Supabase client not initialized.');
            return null;
        }

        if (typeof supabase === 'undefined') {
            console.error('Supabase JS library not loaded. Make sure to load the Supabase CDN script first.');
            return null;
        }

        supabaseClient = supabase.createClient(
            window.AutoFlowConfig.supabaseUrl,
            window.AutoFlowConfig.supabasePublishableKey,
            {
                auth: {
                    autoRefreshToken: true,
                    persistSession: true,
                    detectSessionInUrl: true,
                    storage: window.localStorage,
                    storageKey: 'autoflow-auth',
                    flowType: 'pkce'
                }
            }
        );
        isInitialized = true;
    }
    return supabaseClient;
}

async function getSession() {
    const client = getSupabaseClient();
    if (!client) {
        console.log('AUTH DEBUG: Supabase client is null');
        return null;
    }

    try {
        const { data: { session }, error } = await client.auth.getSession();

        console.log('AUTH DEBUG: getSession()', {
            hasSession: !!session,
            user: session?.user?.email,
            error: error?.message
        });

        if (error) {
            console.error('Error getting session:', error);
            return null;
        }

        return session;
    } catch (err) {
        console.error('AUTH DEBUG: getSession exception', err);
        return null;
    }
}

async function getAccessToken() {
    const session = await getSession();
    return session?.access_token || null;
}

async function getUser() {
    const session = await getSession();
    return session?.user || null;
}

async function refreshSession() {
    const client = getSupabaseClient();
    if (!client) return null;

    try {
        const { data: { session }, error } = await client.auth.refreshSession();
        if (error) {
            console.error('Error refreshing session:', error);
            return null;
        }
        return session || null;
    } catch (err) {
        console.error('Exception refreshing session:', err);
        return null;
    }
}

async function isAuthenticated() {
    return !!(await getSession());
}

async function changeEmail(newEmail) {
    const client = getSupabaseClient();
    if (!client) {
        return { data: null, error: { message: 'Supabase client not initialized' } };
    }

    const session = await getSession();
    if (!session) {
        return { data: null, error: { message: 'Your session has expired. Please sign in again.' } };
    }

    try {
        const { data, error } = await client.auth.updateUser({ email: newEmail });

        if (error) {
            console.error('Change email error:', error);
            return { data: null, error };
        }

        return { data, error: null };
    } catch (err) {
        console.error('Change email exception:', err);
        return { data: null, error: { message: err.message || 'Could not change your email.' } };
    }
}

async function checkAuthAndRedirect() {
    const session = await getSession();
    if (!session) {
        const currentPath = window.location.pathname;
        const loginUrl = `/login/?redirect=${encodeURIComponent(currentPath)}`;
        window.location.href = loginUrl;
        return false;
    }
    return true;
}

async function signOut() {
    const client = getSupabaseClient();
    if (!client) return { error: { message: 'Supabase client not initialized' } };

    try {
        const { error } = await client.auth.signOut();
        if (error) {
            console.error('Sign out error:', error);
            return { error };
        }
        window.location.href = '/login/';
        return { error: null };
    } catch (err) {
        console.error('Sign out exception:', err);
        return { error: { message: err.message || 'Sign out failed' } };
    }
}

function onAuthStateChange(callback) {
    const client = getSupabaseClient();
    if (!client) return { data: { subscription: { unsubscribe: () => {} } } };

    const { data: { subscription } } = client.auth.onAuthStateChange((event, session) => {
        callback(event, session);
    });
    return { data: { subscription } };
}

function resolveDisplayName(user) {
    const metadata = user.user_metadata || {};
    return metadata.full_name || metadata.name || user.email || '';
}

function updateAuthUI() {
    getSession().then(session => {
        const user = session?.user || null;
        const name = user ? resolveDisplayName(user) : '';

        document.querySelectorAll('[data-user-email]').forEach(el => {
            el.textContent = user ? user.email : '';
            el.style.display = user ? '' : 'none';
        });

        document.querySelectorAll('[data-user-name]').forEach(el => {
            el.textContent = name;
            el.style.display = user ? '' : 'none';
        });
    });
}

window.AutoFlowAuth = {
    getSupabaseClient,
    getSession,
    getAccessToken,
    getUser,
    refreshSession,
    isAuthenticated,
    changeEmail,
    checkAuthAndRedirect,
    signOut,
    onAuthStateChange,
    updateAuthUI,
};