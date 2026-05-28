// Main JavaScript for LLMBench Web
console.log('LLMBench Web loaded');

async function readResponseBody(response) {
    const text = await response.text();
    if (!text) {
        return { data: null, text: '' };
    }

    try {
        return { data: JSON.parse(text), text };
    } catch {
        return { data: null, text };
    }
}

function buildFetchErrorMessage(error) {
    if (!error) return 'Request failed';
    if (error.name === 'TypeError') {
        return `Request failed before the server returned a response: ${error.message}`;
    }
    return error.message || 'Request failed';
}

function buildApiErrorMessage(response, payload, fallbackMessage) {
    const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`;

    if (payload && typeof payload === 'object') {
        if (payload.detail) return `${statusLabel}: ${payload.detail}`;
        if (payload.error) return `${statusLabel}: ${payload.error}`;
        if (payload.message) return `${statusLabel}: ${payload.message}`;
    }

    if (typeof payload === 'string' && payload.trim()) {
        return `${statusLabel}: ${payload.trim()}`;
    }

    return fallbackMessage ? `${statusLabel}: ${fallbackMessage}` : statusLabel;
}
