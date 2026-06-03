(function () {
    var localFrontendHosts = ["localhost", "127.0.0.1"];
    var isLocalFrontend = localFrontendHosts.indexOf(window.location.hostname) !== -1
        && window.location.port === "8000";

    window.APP_CONFIG = window.APP_CONFIG || {
        apiBaseUrl: isLocalFrontend ? "http://127.0.0.1:5000" : window.location.origin
    };
}());
