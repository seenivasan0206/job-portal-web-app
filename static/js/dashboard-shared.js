/* ============================================================
   Dashboard Shared Utilities
   - Toast notifications (delegates to global window.showToast)
   - Notification bell + dropdown with 30s polling
   - Click-outside handling for dropdowns
   ============================================================ */

window.dashboardShared = (function () {
    "use strict";

    function showToast(message, type) {
        if (typeof window.showToast === "function") {
            window.showToast(message, type);
        }
    }

    function formatTimeAgo(dateString) {
        if (!dateString) return "Unknown";
        var date = new Date(dateString);
        if (isNaN(date.getTime())) return dateString;
        var now = new Date();
        var diffMs = now - date;
        var diffMins = Math.floor(diffMs / 60000);
        var diffHours = Math.floor(diffMs / 3600000);
        var diffDays = Math.floor(diffMs / 86400000);
        if (diffMins < 1) return "Just now";
        if (diffMins < 60) return diffMins + " min ago";
        if (diffHours < 24) return diffHours + " hour" + (diffHours > 1 ? "s" : "") + " ago";
        if (diffDays === 1) return "Yesterday";
        if (diffDays < 7) return diffDays + " days ago";
        return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str.replace(/[&<>"']/g, function (m) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
        });
    }

    function getCookie(name) {
        var nameEQ = name + "=";
        var ca = document.cookie.split(";");
        for (var i = 0; i < ca.length; i++) {
            var c = ca[i];
            while (c.charAt(0) === " ") c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
        }
        return null;
    }

    function setCookie(name, value, days) {
        var d = new Date();
        d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
        document.cookie = name + "=" + value + ";expires=" + d.toUTCString() + ";path=/;SameSite=Lax";
    }

    // --- Notification bell ---
    var notifDropdownOpen = false;
    var notifPolling = null;

    function updateNotifBadge(count) {
        var badge = document.getElementById("notif-count");
        if (!badge) return;
        if (count > 0) {
            badge.style.display = "flex";
            badge.textContent = count > 99 ? "99+" : count;
        } else {
            badge.style.display = "none";
        }
    }

    async function loadNotifCount() {
        try {
            var res = await fetch("/api/get_unread_count");
            var data = await res.json();
            if (data.success && typeof data.count !== "undefined") {
                updateNotifBadge(data.count);
            }
        } catch (e) { /* silent */ }
    }

    async function loadNotifications() {
        var list = document.getElementById("notif-list");
        if (!list) return;
        list.innerHTML = "";
        // Skeleton loading
        for (var i = 0; i < 4; i++) {
            list.innerHTML += '<div class="notif-skeleton"><div class="skeleton-line" style="width:100%; margin-bottom:5px;"></div><div class="skeleton-line short" style="width:80%;"></div></div>';
        }
        try {
            var res = await fetch("/api/get_user_notifications");
            var data = await res.json();
            list.innerHTML = "";
            if (data.notifications && data.notifications.length > 0) {
                data.notifications.forEach(function (n) {
                    var icon = "bell";
                    var msgLower = (n.message || "").toLowerCase();
                    if (msgLower.includes("selected") || msgLower.includes("congratulations")) icon = "trophy";
                    else if (msgLower.includes("rejected") || msgLower.includes("not selected")) icon = "times-circle";
                    else if (msgLower.includes("applied")) icon = "file-check";

                    var unreadClass = !n.is_read ? "unread" : "read";
                    var timeAgo = formatTimeAgo(n.created_at);
                    var isNew = !n.is_read ? '<span class="ds-badge ds-badge-active" style="margin-left:8px;font-size:10px;">New</span>' : "";

                    var div = document.createElement("div");
                    div.className = "notif-item " + unreadClass;
                    div.onclick = function (e) {
                        e.preventDefault();
                        if (!n.is_read) {
                            markNotificationRead(n.id);
                        }
                    };
                    div.innerHTML = '<h4><i class="fas fa-' + icon + '"></i> ' + escapeHtml(n.message || "") + isNew + "</h4>" +
                        '<p>' + escapeHtml(n.details || "") + "</p>" +
                        '<span class="notif-time"><i class="fas fa-clock"></i> ' + timeAgo + "</span>";
                    list.appendChild(div);
                });
            } else {
                list.innerHTML = '<div class="notif-empty"><i class="fas fa-bell-slash"></i><p>No notifications yet</p></div>';
            }
        } catch (e) {
            list.innerHTML = '<div class="notif-empty"><i class="fas fa-exclamation-circle"></i><p>Failed to load notifications</p></div>';
        }
    }

    function toggleNotificationDropdown(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        var dd = document.getElementById("notif-dropdown");
        if (!dd) return;
        if (dd.classList.contains("show")) {
            dd.classList.remove("show");
            notifDropdownOpen = false;
            if (notifPolling) clearInterval(notifPolling);
        } else {
            dd.classList.add("show");
            notifDropdownOpen = true;
            loadNotifications();
            notifPolling = setInterval(loadNotifications, 30000);
        }
    }

    async function markAllAsRead(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        try {
            await fetch("/api/mark_notifications_read", { method: "POST" });
            loadNotifications();
            loadNotifCount();
            showToast("All notifications marked as read", "success");
        } catch (e) {
            showToast("Failed to mark as read", "error");
        }
    }

    async function markNotificationRead(id) {
        try {
            await fetch("/api/notifications/" + id + "/read", { method: "POST" });
            loadNotifCount();
        } catch (e) { /* silent */ }
    }

    // Click-outside for notifications
    function initNotifClickOutside() {
        document.addEventListener("click", function (e) {
            var dd = document.getElementById("notif-dropdown");
            var bell = document.querySelector(".notif-bell");
            if (notifDropdownOpen && dd && !dd.contains(e.target) && (!bell || !bell.contains(e.target))) {
                dd.classList.remove("show");
                notifDropdownOpen = false;
                if (notifPolling) clearInterval(notifPolling);
            }
        });
    }

    // --- Init ---
    function init() {
        initNotifClickOutside();
        loadNotifCount();
    }

    // Expose public API
    return {
        showToast: showToast,
        formatTimeAgo: formatTimeAgo,
        toggleNotifications: toggleNotificationDropdown,
        markAllAsRead: markAllAsRead,
        loadNotifCount: loadNotifCount,
        loadNotifications: loadNotifications,
        getCookie: getCookie,
        setCookie: setCookie,
        init: init,
    };
})();

// Auto-init when DOM is ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", window.dashboardShared.init);
} else {
    window.dashboardShared.init();
}
