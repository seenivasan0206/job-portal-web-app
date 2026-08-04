(function() {
    function getCSRFToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : null;
    }

    var originalFetch = window.fetch;
    window.fetch = async function(url, options) {
        options = options || {};
        var method = (options.method || 'GET').toUpperCase();
        if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
            var token = getCSRFToken();
            if (token) {
                var headers = options.headers || {};
                if (headers instanceof Headers) {
                    headers.set('X-CSRFToken', token);
                } else {
                    options.headers = Object.assign({}, headers, { 'X-CSRFToken': token });
                }
                if (options.body instanceof FormData) {
                    options.body.append('csrf_token', token);
                }
            }
        }
        return originalFetch.call(this, url, options);
    };

    // Also patch postReq if it exists and hasn't been patched yet
    window.getCSRFToken = getCSRFToken;
})();
