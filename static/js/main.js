/**
 * HireVolt — Master UI & Motion Engine
 * Powered by Lenis (https://lenis.dev/) for 60fps Butter-Smooth Scrolling
 */

(function () {
  'use strict';

  // ---- 1. Dark Mode / Theme Manager ----
  function initTheme() {
    const savedTheme = localStorage.getItem('hirevolt-theme') || localStorage.getItem('nexrole-theme') || localStorage.getItem('dreamjobs-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }

  window.toggleTheme = function () {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('hirevolt-theme', next);
    localStorage.setItem('dreamjobs-theme', next);
  };

  // ---- 2. Scrollbar Width & Mobile Navigation ----
  let savedScrollY = 0;

  window.lockBodyScroll = function () {
    savedScrollY = window.pageYOffset || document.documentElement.scrollTop || window.scrollY || 0;
    if (window.lenis) {
      try { window.lenis.stop(); } catch (e) {}
    }
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = scrollbarWidth + 'px';
    }
    document.body.style.overflow = 'hidden';
  };

  window.unlockBodyScroll = function () {
    const activeModals = document.querySelectorAll('.modal-backdrop.active, .premium-success-overlay.is-open');
    if (activeModals.length === 0) {
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
      if (window.lenis) {
        try {
          window.lenis.start();
          window.lenis.scrollTo(savedScrollY, { immediate: true, force: true });
        } catch (e) {}
      }
      window.scrollTo({ top: savedScrollY, left: 0, behavior: 'instant' });
    }
  };

  window.toggleMobileMenu = function () {
    const drawer = document.getElementById('mobile-drawer');
    const backdrop = document.getElementById('mobile-drawer-backdrop');
    if (drawer && backdrop) {
      const isOpen = drawer.classList.contains('active') || drawer.classList.contains('open');
      if (isOpen) {
        drawer.classList.remove('active');
        drawer.classList.remove('open');
        backdrop.classList.remove('active');
        backdrop.classList.remove('open');
        if (typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
      } else {
        drawer.classList.add('active');
        drawer.classList.add('open');
        backdrop.classList.add('active');
        backdrop.classList.add('open');
        if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
      }
    }
  };

  // ---- 3. Unified Sticky Navbar & Scroll Progress Indicator ----
  function initNavbarAndScrollProgress() {
    const navbar = document.querySelector('.navbar');

    function updateScrollState(scrollY) {
      if (navbar) {
        if (scrollY > 20) {
          navbar.classList.add('is-scrolled');
        } else {
          navbar.classList.remove('is-scrolled');
        }
      }
    }

    // If Lenis is active, updateScrollState will be driven by Lenis scroll events.
    // Otherwise, attach a native scroll listener.
    if (!window.lenis) {
      let ticking = false;
      window.addEventListener('scroll', function () {
        if (!ticking) {
          window.requestAnimationFrame(() => {
            updateScrollState(window.scrollY || window.pageYOffset);
            ticking = false;
          });
          ticking = true;
        }
      }, { passive: true });
      updateScrollState(window.scrollY || window.pageYOffset);
    }

    window.updateScrollState = updateScrollState;
  }

  // ---- 4. Centralized Lenis Smooth Anchor Scrolling ----
  function initSmoothAnchorScrolling() {
    document.addEventListener('click', function (e) {
      const link = e.target.closest('a');
      if (!link) return;

      const href = link.getAttribute('href');
      if (!href) return;

      let targetId = null;
      if (href.startsWith('#') && href.length > 1) {
        targetId = href.substring(1);
      } else if (href.startsWith('/#') && (window.location.pathname === '/' || window.location.pathname === '/index')) {
        targetId = href.substring(2);
      }

      if (targetId) {
        const targetEl = document.getElementById(targetId) || document.querySelector(`[name="${targetId}"]`);
        if (targetEl) {
          e.preventDefault();
          const navbarHeight = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--navbar-height')) || 72;
          
          if (window.lenis) {
            window.lenis.scrollTo(targetEl, {
              offset: -(navbarHeight + 16),
              duration: 1.1,
              easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t))
            });
          } else {
            const elementPosition = targetEl.getBoundingClientRect().top + window.pageYOffset;
            const offsetPosition = Math.max(0, elementPosition - navbarHeight - 16);
            window.scrollTo({
              top: offsetPosition,
              behavior: 'smooth'
            });
          }

          const drawer = document.getElementById('mobile-drawer');
          if (drawer && drawer.classList.contains('active')) {
            window.toggleMobileMenu();
          }
        }
      }
    });
  }

  // ---- 5. 60fps Scroll Reveal Animation Engine ----
  function initScrollRevealObserver() {
    if (!('IntersectionObserver' in window)) {
      document.querySelectorAll('.reveal-on-scroll').forEach(el => el.classList.add('is-visible'));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      {
        root: null,
        rootMargin: '0px 0px -40px 0px',
        threshold: 0.1
      }
    );

    document.querySelectorAll('.reveal-on-scroll').forEach((el) => {
      observer.observe(el);
    });

    window.refreshScrollReveal = function () {
      document.querySelectorAll('.reveal-on-scroll:not(.is-visible)').forEach((el) => {
        observer.observe(el);
      });
    };
  }

  // ---- 6. Lucide Icons ----
  function initLucide() {
    if (window.lucide) {
      lucide.createIcons();
    }
  }

  // ---- 7. Global Toast Notifications ----
  window.showToast = function (message, type) {
    type = type || 'info';
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.setAttribute('aria-live', 'polite');
      container.setAttribute('aria-atomic', 'true');
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    
    let iconClass = 'fa-info-circle';
    if (type === 'success') iconClass = 'fa-check-circle';
    if (type === 'error') iconClass = 'fa-triangle-exclamation';
    if (type === 'warning') iconClass = 'fa-circle-exclamation';

    toast.innerHTML = `
      <i class="fas ${iconClass}"></i>
      <span class="toast-message">${escapeToastHtml(message)}</span>
      <button type="button" class="toast-close" onclick="this.parentElement.remove()" aria-label="Close notification">&times;</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      setTimeout(() => {
        if (toast.parentElement) toast.remove();
      }, 300);
    }, 3500);
  };

  function escapeToastHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ---- 8. Universal POST / GET Request Helpers ----
  window.postReq = async function (url, data, retryOnCsrf = true) {
    try {
      const headers = { 'Content-Type': 'application/json' };
      let csrfMeta = document.querySelector('meta[name="csrf-token"]');
      let token = csrfMeta ? csrfMeta.getAttribute('content') : null;

      if (!token) {
        try {
          const tokRes = await fetch('/api/csrf_token');
          if (tokRes.ok) {
            const tokData = await tokRes.json();
            if (tokData && tokData.csrf_token) {
              token = tokData.csrf_token;
              if (csrfMeta) {
                csrfMeta.setAttribute('content', token);
              } else {
                csrfMeta = document.createElement('meta');
                csrfMeta.name = 'csrf-token';
                csrfMeta.content = token;
                document.head.appendChild(csrfMeta);
              }
            }
          }
        } catch (e) {}
      }

      if (token) {
        headers['X-CSRFToken'] = token;
      }

      const res = await fetch(url, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(data || {})
      });

      const contentType = res.headers.get('content-type') || '';

      if (contentType.includes('application/json')) {
        const json = await res.json();
        if (json.csrf_token) {
          const meta = document.querySelector('meta[name="csrf-token"]');
          if (meta) meta.setAttribute('content', json.csrf_token);
        }

        // Auto-heal CSRF token on 400 error and retry once
        if (res.status === 400 && json.message && json.message.toLowerCase().includes('csrf') && retryOnCsrf) {
          try {
            const refreshRes = await fetch('/api/csrf_token');
            if (refreshRes.ok) {
              const refreshData = await refreshRes.json();
              if (refreshData && refreshData.csrf_token) {
                const meta = document.querySelector('meta[name="csrf-token"]');
                if (meta) meta.setAttribute('content', refreshData.csrf_token);
                return await window.postReq(url, data, false);
              }
            }
          } catch (e) {}
        }

        return json;
      }

      if (res.status === 401) {
        window.showToast('Your session has expired. Please log in again.', 'warning');
        return { success: false, message: 'Unauthorized', status: 401 };
      }
      if (res.status === 403) {
        window.showToast('You do not have permission to perform this action.', 'error');
        return { success: false, message: 'Forbidden', status: 403 };
      }
      if (res.status === 429) {
        window.showToast('Too many requests. Please wait a moment.', 'warning');
        return { success: false, message: 'Rate limited', status: 429 };
      }
      if (res.status >= 500) {
        window.showToast('Server is temporarily unavailable. Please try again.', 'error');
        return { success: false, message: 'Server error', status: res.status };
      }
      if (res.status === 404) {
        window.showToast('Requested service endpoint was not found.', 'error');
        return { success: false, message: 'Not found', status: 404 };
      }

      window.showToast('Unable to complete request right now. Please try again.', 'error');
      return { success: false, message: 'Invalid response format', status: res.status };
    } catch (err) {
      console.error('postReq network error:', err);
      window.showToast('Unable to connect to server. Please check your internet connection.', 'error');
      return { success: false, message: 'Network connection error' };
    }
  };

  window.getReq = async function (url) {
    try {
      const res = await fetch(url, { method: 'GET' });
      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        window.showToast('Server error fetching data.', 'error');
        return { success: false, message: 'Server error' };
      }
      const json = await res.json();
      if (!json.success && json.message) {
        window.showToast(json.message, 'error');
      }
      return json;
    } catch (err) {
      console.error('getReq network error:', err);
      window.showToast('Unable to connect to server. Please check your internet connection.', 'error');
      return { success: false, message: 'Network connection error' };
    }
  };

  window.deleteReq = async function (url, data, retryOnCsrf = true) {
    try {
      const headers = { 'Content-Type': 'application/json' };
      let csrfMeta = document.querySelector('meta[name="csrf-token"]');
      let token = csrfMeta ? csrfMeta.getAttribute('content') : null;

      if (!token) {
        try {
          const tokRes = await fetch('/api/csrf_token');
          if (tokRes.ok) {
            const tokData = await tokRes.json();
            if (tokData && tokData.csrf_token) {
              token = tokData.csrf_token;
              if (csrfMeta) {
                csrfMeta.setAttribute('content', token);
              } else {
                csrfMeta = document.createElement('meta');
                csrfMeta.name = 'csrf-token';
                csrfMeta.content = token;
                document.head.appendChild(csrfMeta);
              }
            }
          }
        } catch (e) {}
      }

      if (token) {
        headers['X-CSRFToken'] = token;
      }

      const fetchOptions = {
        method: 'DELETE',
        headers: headers
      };
      if (data !== undefined && data !== null) {
        fetchOptions.body = JSON.stringify(data);
      }

      const res = await fetch(url, fetchOptions);
      const contentType = res.headers.get('content-type') || '';

      if (contentType.includes('application/json')) {
        const json = await res.json();
        if (json.csrf_token) {
          const meta = document.querySelector('meta[name="csrf-token"]');
          if (meta) meta.setAttribute('content', json.csrf_token);
        }

        if (res.status === 400 && json.message && json.message.toLowerCase().includes('csrf') && retryOnCsrf) {
          try {
            const refreshRes = await fetch('/api/csrf_token');
            if (refreshRes.ok) {
              const refreshData = await refreshRes.json();
              if (refreshData && refreshData.csrf_token) {
                const meta = document.querySelector('meta[name="csrf-token"]');
                if (meta) meta.setAttribute('content', refreshData.csrf_token);
                return await window.deleteReq(url, data, false);
              }
            }
          } catch (e) {}
        }

        return json;
      }

      if (res.status === 401) {
        window.showToast('Your session has expired. Please log in again.', 'warning');
        return { success: false, message: 'Unauthorized', status: 401 };
      }
      if (res.status === 403) {
        window.showToast('You do not have permission to perform this action.', 'error');
        return { success: false, message: 'Forbidden', status: 403 };
      }
      if (res.status === 429) {
        window.showToast('Too many requests. Please wait a moment.', 'warning');
        return { success: false, message: 'Rate limited', status: 429 };
      }
      if (res.status >= 500) {
        window.showToast('Server is temporarily unavailable. Please try again.', 'error');
        return { success: false, message: 'Server error', status: res.status };
      }
      if (res.status === 404) {
        window.showToast('Requested entry was not found.', 'error');
        return { success: false, message: 'Not found', status: 404 };
      }

      return { success: res.ok, status: res.status };
    } catch (err) {
      console.error('deleteReq network error:', err);
      window.showToast('Unable to connect to server. Please check your internet connection.', 'error');
      return { success: false, message: 'Network connection error' };
    }
  };

  window.putReq = async function (url, data, retryOnCsrf = true) {
    try {
      const headers = { 'Content-Type': 'application/json' };
      let csrfMeta = document.querySelector('meta[name="csrf-token"]');
      let token = csrfMeta ? csrfMeta.getAttribute('content') : null;

      if (!token) {
        try {
          const tokRes = await fetch('/api/csrf_token');
          if (tokRes.ok) {
            const tokData = await tokRes.json();
            if (tokData && tokData.csrf_token) {
              token = tokData.csrf_token;
              if (csrfMeta) {
                csrfMeta.setAttribute('content', token);
              } else {
                csrfMeta = document.createElement('meta');
                csrfMeta.name = 'csrf-token';
                csrfMeta.content = token;
                document.head.appendChild(csrfMeta);
              }
            }
          }
        } catch (e) {}
      }

      if (token) {
        headers['X-CSRFToken'] = token;
      }

      const res = await fetch(url, {
        method: 'PUT',
        headers: headers,
        body: JSON.stringify(data || {})
      });

      const contentType = res.headers.get('content-type') || '';

      if (contentType.includes('application/json')) {
        const json = await res.json();
        if (json.csrf_token) {
          const meta = document.querySelector('meta[name="csrf-token"]');
          if (meta) meta.setAttribute('content', json.csrf_token);
        }

        if (res.status === 400 && json.message && json.message.toLowerCase().includes('csrf') && retryOnCsrf) {
          try {
            const refreshRes = await fetch('/api/csrf_token');
            if (refreshRes.ok) {
              const refreshData = await refreshRes.json();
              if (refreshData && refreshData.csrf_token) {
                const meta = document.querySelector('meta[name="csrf-token"]');
                if (meta) meta.setAttribute('content', refreshData.csrf_token);
                return await window.putReq(url, data, false);
              }
            }
          } catch (e) {}
        }

        return json;
      }

      if (res.status === 401) {
        window.showToast('Your session has expired. Please log in again.', 'warning');
        return { success: false, message: 'Unauthorized', status: 401 };
      }
      if (res.status === 403) {
        window.showToast('You do not have permission to perform this action.', 'error');
        return { success: false, message: 'Forbidden', status: 403 };
      }
      if (res.status === 429) {
        window.showToast('Too many requests. Please wait a moment.', 'warning');
        return { success: false, message: 'Rate limited', status: 429 };
      }
      if (res.status >= 500) {
        window.showToast('Server is temporarily unavailable. Please try again.', 'error');
        return { success: false, message: 'Server error', status: res.status };
      }
      if (res.status === 404) {
        window.showToast('Requested service endpoint was not found.', 'error');
        return { success: false, message: 'Not found', status: 404 };
      }

      return { success: res.ok, status: res.status };
    } catch (err) {
      console.error('putReq network error:', err);
      window.showToast('Unable to connect to server. Please check your internet connection.', 'error');
      return { success: false, message: 'Network connection error' };
    }
  };

  // ---- 9. Smooth Page-to-Page Navigation Progress Bar ----
  function initNavProgressBar() {
    const navProgress = document.getElementById('app-nav-progress');
    if (!navProgress) return;

    document.addEventListener('click', (e) => {
      const link = e.target.closest('a');
      if (!link) return;

      const href = link.getAttribute('href');
      const target = link.getAttribute('target');

      if (
        href &&
        !href.startsWith('#') &&
        !href.startsWith('javascript:') &&
        !href.startsWith('mailto:') &&
        !href.startsWith('tel:') &&
        target !== '_blank' &&
        !e.ctrlKey &&
        !e.metaKey &&
        !e.shiftKey
      ) {
        const isInternal = href.startsWith('/') || href.startsWith(window.location.origin);
        if (isInternal) {
          navProgress.style.opacity = '1';
          navProgress.style.width = '70%';
        }
      }
    });

    window.addEventListener('pageshow', () => {
      navProgress.style.width = '100%';
      setTimeout(() => {
        navProgress.style.opacity = '0';
        navProgress.style.width = '0%';
      }, 200);
    });
  }

  // ---- 10. Word Rotator Utility ----
  function initWordRotator() {
    const rotators = document.querySelectorAll('[data-rotate-words]');
    rotators.forEach((rotator) => {
      const words = JSON.parse(rotator.getAttribute('data-rotate-words') || '[]');
      if (!words || words.length === 0) return;

      let idx = 0;
      setInterval(() => {
        rotator.style.opacity = '0';
        rotator.style.transform = 'translateY(8px)';
        setTimeout(() => {
          idx = (idx + 1) % words.length;
          rotator.textContent = words[idx];
          rotator.style.opacity = '1';
          rotator.style.transform = 'translateY(0)';
        }, 300);
      }, 2500);
    });
  }

  // ---- 11. Centralized Lenis Smooth Scroll Engine Initialization ----
  function initLenisEngine() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    
    if (typeof Lenis !== 'undefined' && !prefersReducedMotion && !window.lenis) {
      window.lenis = new Lenis({
        duration: 1.1,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // Smooth exponential deceleration
        orientation: 'vertical',
        gestureOrientation: 'vertical',
        smoothWheel: true,
        smoothTouch: false, // Maintain 120Hz native touch responsiveness on mobile/trackpads
        wheelMultiplier: 1.0,
        touchMultiplier: 1.6,
        infinite: false,
      });

      window.lenis.on('scroll', (e) => {
        const scrollY = typeof e.scroll === 'number' ? e.scroll : (window.scrollY || window.pageYOffset);
        if (typeof window.updateScrollState === 'function') {
          window.updateScrollState(scrollY);
        }
      });

      function lenisRaf(time) {
        if (window.lenis) {
          window.lenis.raf(time);
        }
        requestAnimationFrame(lenisRaf);
      }
      requestAnimationFrame(lenisRaf);
    }
  }

  // ---- Initialize Master Motion & UX Engine ----
  function init() {
    initTheme();
    initLenisEngine();
    initNavbarAndScrollProgress();
    initSmoothAnchorScrolling();
    initScrollRevealObserver();
    initLucide();
    initNavProgressBar();
    initWordRotator();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

// ---- Premium Success Animation Modal Controllers ----
window.showJobPostedSuccessModal = function (meta) {
  meta = meta || {};
  const modal = document.getElementById('premium-job-posted-modal');
  if (!modal) return;

  const titleEl = document.getElementById('prem-job-title');
  if (titleEl) titleEl.textContent = meta.title || 'Job Opening';

  const subEl = document.getElementById('prem-job-sub');
  if (subEl) {
    const loc = meta.location ? ` in ${meta.location}` : '';
    subEl.textContent = `Your job opening${loc} is now published and active for candidates.`;
  }

  const viewBtn = document.getElementById('prem-job-view-btn');
  if (viewBtn) {
    if (meta.jobId) {
      viewBtn.href = `/job_detail/${meta.jobId}`;
      viewBtn.style.display = 'inline-flex';
    } else {
      viewBtn.href = '/jobs';
    }
  }

  modal.classList.add('is-open');
  if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
};

window.showApplicationSubmittedModal = function (meta) {
  meta = meta || {};
  const modal = document.getElementById('premium-application-submitted-modal');
  if (!modal) return;

  const titleEl = document.getElementById('prem-app-title');
  if (titleEl) titleEl.textContent = meta.jobTitle || 'Role Application';

  const compEl = document.getElementById('prem-app-company');
  if (compEl) compEl.textContent = meta.companyName ? `at ${meta.companyName}` : 'to Employer';

  modal.classList.add('is-open');
  if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
};

window.closePremiumModal = function (modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('is-open');
    if (typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
  }
};

// =========================================================================
// UNIVERSAL ACCESSIBLE AUTHENTICATION MODAL ENGINE
// =========================================================================
var lastFocusedTrigger = null;

window.openUserModal = function (formType) {
  lastFocusedTrigger = document.activeElement;
  if (typeof window.closeEmpModal === 'function') window.closeEmpModal(false);
  if (typeof window.showForm === 'function') window.showForm(formType || 'login');
  
  const modal = document.getElementById('user-auth-modal');
  if (modal) {
    modal.classList.add('active');
    if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
    setTimeout(() => {
      const activePane = modal.querySelector('#form-' + (formType || 'login'));
      const firstInput = activePane ? activePane.querySelector('input:not([type=hidden])') : null;
      if (firstInput) {
        firstInput.focus();
      } else {
        const closeBtn = modal.querySelector('.modal-close');
        if (closeBtn) closeBtn.focus();
      }
    }, 60);
  }
};

window.closeUserModal = function (e) {
  e = e || (typeof window !== 'undefined' ? window.event : null);
  if (e) {
    if (typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof e.stopPropagation === 'function') e.stopPropagation();
  }
  const modal = document.getElementById('user-auth-modal');
  if (modal) {
    modal.classList.remove('active');
    if (typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
    if (lastFocusedTrigger && typeof lastFocusedTrigger.focus === 'function') {
      try {
        lastFocusedTrigger.focus({ preventScroll: true });
      } catch (err) {
        try { lastFocusedTrigger.focus(); } catch (e2) {}
      }
    }
  }
};

window.openEmpModal = function (formType) {
  lastFocusedTrigger = document.activeElement;
  if (typeof window.closeUserModal === 'function') window.closeUserModal(false);
  if (typeof window.showEmpForm === 'function') window.showEmpForm(formType || 'login');
  
  const modal = document.getElementById('emp-auth-modal');
  if (modal) {
    modal.classList.add('active');
    if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
    setTimeout(() => {
      const activePane = modal.querySelector('#emp-form-' + (formType || 'login'));
      const firstInput = activePane ? activePane.querySelector('input:not([type=hidden])') : null;
      if (firstInput) {
        firstInput.focus();
      } else {
        const closeBtn = modal.querySelector('.modal-close');
        if (closeBtn) closeBtn.focus();
      }
    }, 60);
  }
};

window.closeEmpModal = function (e, unlock = true) {
  if (typeof e === 'boolean') {
    unlock = e;
    e = null;
  }
  e = e || (typeof window !== 'undefined' ? window.event : null);
  if (e) {
    if (typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof e.stopPropagation === 'function') e.stopPropagation();
  }
  const modal = document.getElementById('emp-auth-modal');
  if (modal) {
    modal.classList.remove('active');
    if (unlock && typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
    if (lastFocusedTrigger && typeof lastFocusedTrigger.focus === 'function') {
      try {
        lastFocusedTrigger.focus({ preventScroll: true });
      } catch (err) {
        try { lastFocusedTrigger.focus(); } catch (e2) {}
      }
    }
  }
};

window.closeAllModals = function () {
  window.closeUserModal();
  window.closeEmpModal();
  if (typeof window.closeLogoutModal === 'function') window.closeLogoutModal();
};

window.handleBackdropClick = function (e, type) {
  if (e.target === e.currentTarget || e.target.classList.contains('modal-backdrop')) {
    if (type === 'user') window.closeUserModal(e);
    else if (type === 'employer') window.closeEmpModal(e);
    else if (type === 'logout') window.closeLogoutModal(e);
    else window.closeAllModals();
  }
};

window.showForm = function (type) {
  ['form-signup', 'form-login', 'form-forgot'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = (id === 'form-' + type) ? 'block' : 'none';
  });
  const body = document.getElementById('user-modal-body') || document.getElementById('base-user-modal-body');
  if (body) {
    body.style.overflowY = (type === 'login') ? 'hidden' : 'auto';
  }
  const tabIn = document.getElementById('tab-btn-signin');
  const tabUp = document.getElementById('tab-btn-signup');
  if (tabIn && tabUp) {
    if (type === 'login') {
      tabIn.style.background = '#FF5E14';
      tabIn.style.color = '#FFFFFF';
      tabUp.style.background = 'transparent';
      tabUp.style.color = '#94A3B8';
    } else if (type === 'signup') {
      tabUp.style.background = '#FF5E14';
      tabUp.style.color = '#FFFFFF';
      tabIn.style.background = 'transparent';
      tabIn.style.color = '#94A3B8';
    } else {
      tabIn.style.background = 'transparent';
      tabIn.style.color = '#94A3B8';
      tabUp.style.background = 'transparent';
      tabUp.style.color = '#94A3B8';
    }
  }
  const activePane = document.getElementById('form-' + type);
  if (activePane) {
    const firstInput = activePane.querySelector('input:not([type=hidden])');
    if (firstInput) setTimeout(() => firstInput.focus(), 50);
  }
};

window.showEmpForm = function (type) {
  ['emp-form-register', 'emp-form-login', 'emp-form-forgot'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = (id === 'emp-form-' + type) ? 'block' : 'none';
  });
  const empBody = document.getElementById('emp-modal-body') || document.getElementById('base-emp-modal-body');
  if (empBody) {
    empBody.style.overflowY = (type === 'login') ? 'hidden' : 'auto';
  }
  const tabIn = document.getElementById('emp-tab-btn-signin');
  const tabReg = document.getElementById('emp-tab-btn-register');
  if (tabIn && tabReg) {
    if (type === 'login') {
      tabIn.style.background = '#FF5E14';
      tabIn.style.color = '#FFFFFF';
      tabReg.style.background = 'transparent';
      tabReg.style.color = '#94A3B8';
    } else if (type === 'register') {
      tabReg.style.background = '#FF5E14';
      tabReg.style.color = '#FFFFFF';
      tabIn.style.background = 'transparent';
      tabIn.style.color = '#94A3B8';
    } else {
      tabIn.style.background = 'transparent';
      tabIn.style.color = '#94A3B8';
      tabReg.style.background = 'transparent';
      tabReg.style.color = '#94A3B8';
    }
  }
  const activePane = document.getElementById('emp-form-' + type);
  if (activePane) {
    const firstInput = activePane.querySelector('input:not([type=hidden])');
    if (firstInput) setTimeout(() => firstInput.focus(), 50);
  }
};

// Global Esc key listener
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape' || e.key === 'Esc' || e.keyCode === 27) {
    window.closeAllModals();
  }
});

// Logout Confirmation Modal Lifecycle
window.openLogoutModal = function () {
  lastFocusedTrigger = document.activeElement;
  if (typeof window.closeUserModal === 'function') window.closeUserModal(false);
  if (typeof window.closeEmpModal === 'function') window.closeEmpModal(false);

  const modal = document.getElementById('logout-confirm-modal');
  if (modal) {
    modal.classList.add('active');
    if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
    setTimeout(() => {
      const cancelBtn = document.getElementById('btn-cancel-logout');
      if (cancelBtn) {
        cancelBtn.focus();
      } else {
        const closeBtn = modal.querySelector('.modal-close');
        if (closeBtn) closeBtn.focus();
      }
    }, 60);
  }
};

window.closeLogoutModal = function (e) {
  e = e || (typeof window !== 'undefined' ? window.event : null);
  if (e) {
    if (typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof e.stopPropagation === 'function') e.stopPropagation();
  }
  const modal = document.getElementById('logout-confirm-modal');
  if (modal) {
    modal.classList.remove('active');
    if (typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
    if (lastFocusedTrigger && typeof lastFocusedTrigger.focus === 'function') {
      try {
        lastFocusedTrigger.focus({ preventScroll: true });
      } catch (err) {
        try { lastFocusedTrigger.focus(); } catch (e2) {}
      }
    }
  }
};

window.executeLogout = function () {
  const confirmBtn = document.getElementById('btn-confirm-logout');
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:6px;"></i> Logging out...';
  }
  try {
    sessionStorage.setItem('post_logout_toast', 'You have been successfully logged out.');
  } catch (e) {}
  window.location.href = '/logout';
};

// Universal Password Visibility Toggle
window.togglePasswordVisibility = function (inputId, btnEl) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const btn = btnEl || (window.event && window.event.currentTarget);
  const icon = btn ? btn.querySelector('i') : null;
  if (input.type === 'password') {
    input.type = 'text';
    if (icon) {
      icon.classList.remove('fa-eye');
      icon.classList.add('fa-eye-slash');
    }
    if (btn) btn.setAttribute('aria-label', 'Hide password');
  } else {
    input.type = 'password';
    if (icon) {
      icon.classList.remove('fa-eye-slash');
      icon.classList.add('fa-eye');
    }
    if (btn) btn.setAttribute('aria-label', 'Show password');
  }
};

// Universal Apply & Bookmark Handlers
window.handleJobApply = function (jobId) {
  const isCandidateLoggedIn = Boolean(window.HIREVOLT_USER_ID || window.NEXROLE_USER_ID || window.DREAMJOBS_USER_ID || document.body.classList.contains('user-authenticated'));
  if (isCandidateLoggedIn) {
    if (typeof window.applyDirectly === 'function') {
      window.applyDirectly(jobId);
    } else {
      window.postReq('/api/apply_job', { job_id: jobId }).then((res) => {
        if (res.success) {
          if (typeof window.showApplicationSubmittedModal === 'function') {
            window.showApplicationSubmittedModal({
              jobId: res.job_id || jobId,
              jobTitle: res.job_title || 'Role Application',
              companyName: res.company_name || 'Employer'
            });
          } else {
            window.showToast(res.message || 'Application submitted successfully!', 'success');
          }
        }
      });
    }
  } else {
    try {
      sessionStorage.setItem('pending_job_action', JSON.stringify({ action: 'apply', jobId: jobId }));
    } catch (e) {}
    if (typeof window.openUserModal === 'function') {
      window.openUserModal('login');
    } else {
      window.location.href = '/signup?tab=login';
    }
  }
};

window.handleJobBookmark = function (jobId, btn) {
  const isCandidateLoggedIn = Boolean(window.HIREVOLT_USER_ID || window.NEXROLE_USER_ID || window.DREAMJOBS_USER_ID || document.body.classList.contains('user-authenticated'));
  if (isCandidateLoggedIn) {
    window.postReq('/api/save_job', { job_id: jobId }).then((res) => {
      if (res.success) {
        window.showToast(res.message || 'Job saved to your bookmarks!', 'success');
        if (btn) btn.innerHTML = '<i class="fas fa-bookmark" style="color:#FF5E14;"></i>';
      }
    });
  } else {
    try {
      sessionStorage.setItem('pending_job_action', JSON.stringify({ action: 'bookmark', jobId: jobId }));
    } catch (e) {}
    if (typeof window.openUserModal === 'function') {
      window.openUserModal('login');
    } else {
      window.location.href = '/signup?tab=login';
    }
  }
};

// Post-Logout Notification Listener
document.addEventListener('DOMContentLoaded', function () {
  try {
    const postLogoutMsg = sessionStorage.getItem('post_logout_toast');
    if (postLogoutMsg) {
      sessionStorage.removeItem('post_logout_toast');
      setTimeout(() => {
        if (typeof window.showToast === 'function') {
          window.showToast(postLogoutMsg, 'success');
        }
      }, 250);
    }
  } catch (e) {}
});

// Window aliases for consistent triggering
window.openSignInModal = function () { window.openUserModal('login'); };
window.openSignUpModal = function () { window.openUserModal('signup'); };

// ==========================================================
// DATA-DRIVEN LOCATIONS HELPER & SESSION CACHING
// ==========================================================
window._cachedLocationsData = null;

window.fetchLocations = async function (forceRefresh = false) {
  if (!forceRefresh && window._cachedLocationsData && window._cachedLocationsData.india) {
    return window._cachedLocationsData;
  }

  if (!forceRefresh) {
    try {
      const cached = sessionStorage.getItem('hirevolt_locations_cache');
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && parsed.success && Array.isArray(parsed.india) && parsed.india.length > 0) {
          window._cachedLocationsData = parsed;
          return parsed;
        }
      }
    } catch (e) {}
  }

  try {
    const res = await fetch('/api/locations');
    const data = await res.json();
    if (data && data.success) {
      window._cachedLocationsData = data;
      try {
        sessionStorage.setItem('hirevolt_locations_cache', JSON.stringify(data));
      } catch (e) {}
      return data;
    }
  } catch (err) {
    console.warn('Failed to fetch /api/locations:', err);
  }

  return window._cachedLocationsData || { success: false, india: [], international: [] };
};

window.populateLocationSelect = function (selectTarget, selectedValue = '', defaultOptionText = 'All Locations') {
  const selectEl = (typeof selectTarget === 'string') ? document.getElementById(selectTarget) : selectTarget;
  if (!selectEl) return;

  const currentVal = selectedValue || selectEl.value || selectEl.getAttribute('data-selected-location') || '';

  window.fetchLocations().then((data) => {
    if (!data || !data.india) return;

    let html = '';
    if (defaultOptionText !== null && defaultOptionText !== false) {
      html += `<option value="">${window.escapeHtml ? window.escapeHtml(defaultOptionText) : defaultOptionText}</option>`;
    }

    // 1. India Cities & Remote (Static ~150 comprehensive hubs)
    if (Array.isArray(data.india) && data.india.length > 0) {
      html += '<optgroup label="India">';
      data.india.forEach((loc) => {
        const isSel = currentVal && (currentVal.toLowerCase() === loc.toLowerCase() || currentVal.toLowerCase() === loc.split('(')[0].trim().toLowerCase());
        html += `<option value="${window.escapeHtml ? window.escapeHtml(loc) : loc}"${isSel ? ' selected' : ''}>${window.escapeHtml ? window.escapeHtml(loc) : loc}</option>`;
      });
      html += '</optgroup>';
    }

    // 2. International Cities (Only if real active postings exist in DB)
    if (Array.isArray(data.international) && data.international.length > 0) {
      html += '<optgroup label="International">';
      data.international.forEach((loc) => {
        const isSel = currentVal && currentVal.toLowerCase() === loc.toLowerCase();
        html += `<option value="${window.escapeHtml ? window.escapeHtml(loc) : loc}"${isSel ? ' selected' : ''}>${window.escapeHtml ? window.escapeHtml(loc) : loc}</option>`;
      });
      html += '</optgroup>';
    }

    selectEl.innerHTML = html;
    if (currentVal) {
      selectEl.value = currentVal;
    }
  });
};

window.populateLocationDatalist = function (datalistId, inputTarget) {
  let dl = document.getElementById(datalistId);
  if (!dl) {
    dl = document.createElement('datalist');
    dl.id = datalistId;
    document.body.appendChild(dl);
  }

  if (inputTarget) {
    const inputEl = (typeof inputTarget === 'string') ? document.getElementById(inputTarget) : inputTarget;
    if (inputEl) {
      inputEl.setAttribute('list', datalistId);
    }
  }

  window.fetchLocations().then((data) => {
    if (!data || !data.india) return;
    let html = '';
    if (Array.isArray(data.india)) {
      data.india.forEach((loc) => {
        html += `<option value="${window.escapeHtml ? window.escapeHtml(loc) : loc}">India</option>`;
      });
    }
    if (Array.isArray(data.international)) {
      data.international.forEach((loc) => {
        html += `<option value="${window.escapeHtml ? window.escapeHtml(loc) : loc}">International</option>`;
      });
    }
    dl.innerHTML = html;
  });
};


// =========================================================================
// UNIVERSAL JOB APPLICATION CONTROLLER
// =========================================================================
window.openJobApplyModal = async function(jobId, prefillMeta) {
  const isCandidateLoggedIn = Boolean(window.HIREVOLT_USER_ID || window.NEXROLE_USER_ID || window.DREAMJOBS_USER_ID || document.body.classList.contains('user-authenticated'));
  if (!isCandidateLoggedIn) {
    try {
      sessionStorage.setItem('pending_job_action', JSON.stringify({ action: 'apply', jobId: jobId }));
    } catch (e) {}
    if (typeof window.openUserModal === 'function') {
      window.openUserModal('login');
    } else {
      window.location.href = '/signup?tab=login';
    }
    return;
  }

  const modal = document.getElementById('universal-job-apply-modal');
  if (!modal) {
    window.applyDirectly(jobId);
    return;
  }

  document.getElementById('apply-job-id').value = jobId;
  if (prefillMeta) {
    if (prefillMeta.title) document.getElementById('apply-modal-title').textContent = prefillMeta.title;
    if (prefillMeta.company) document.getElementById('apply-modal-company').textContent = prefillMeta.company;
    if (prefillMeta.location) document.getElementById('apply-modal-location').textContent = prefillMeta.location;
  }

  // Fetch job apply info and candidate resumes
  try {
    const res = await window.getReq(`/api/jobs/${jobId}/apply_info`);
    if (res && res.success) {
      if (res.already_applied) {
        window.showToast(`You have already applied for this job (Status: ${res.application_status || 'Applied'}).`, 'info');
        return;
      }
      if (!res.job.is_available) {
        window.showToast('This job posting is no longer active or the deadline has passed.', 'error');
        return;
      }

      document.getElementById('apply-modal-title').textContent = res.job.title;
      document.getElementById('apply-modal-company').textContent = res.job.company_name;
      document.getElementById('apply-modal-location').textContent = res.job.location;

      // Populate resume select
      const select = document.getElementById('apply-resume-select');
      if (select && res.user_resumes) {
        let opts = '';
        res.user_resumes.forEach(r => {
          opts += `<option value="${r.file_path || r.id}">${escapeHtml(r.label || r.filename)}</option>`;
        });
        opts += '<option value="upload">+ Upload New Resume File (.pdf, .docx, .txt)</option>';
        select.innerHTML = opts;
      }

      // Prefill user salary/notice period if available
      if (res.user_profile) {
        if (res.user_profile.expected_salary) {
          document.getElementById('apply-expected-salary').value = res.user_profile.expected_salary;
        }
      }
    }
  } catch (err) {
    console.error('Error fetching apply info:', err);
  }

  modal.style.display = 'flex';
  if (typeof window.lockBodyScroll === 'function') window.lockBodyScroll();
};

window.closeJobApplyModal = function() {
  const modal = document.getElementById('universal-job-apply-modal');
  if (modal) {
    modal.style.display = 'none';
    if (typeof window.unlockBodyScroll === 'function') window.unlockBodyScroll();
  }
};

window.toggleResumeUploadField = function() {
  const select = document.getElementById('apply-resume-select');
  const container = document.getElementById('apply-resume-file-container');
  if (select && container) {
    if (select.value === 'upload') {
      container.style.display = 'block';
    } else {
      container.style.display = 'none';
    }
  }
};

window.submitJobApplication = async function(e) {
  if (e) e.preventDefault();
  const form = document.getElementById('universal-job-apply-form');
  const submitBtn = document.getElementById('btn-submit-app-final');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Submitting...';
  }

  const formData = new FormData(form);
  const resumeChoice = document.getElementById('apply-resume-select').value;
  if (resumeChoice && resumeChoice !== 'upload') {
    formData.set('resume_path', resumeChoice);
  }

  try {
    const res = await fetch('/api/apply_job', {
      method: 'POST',
      headers: {
        'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]') || {}).content || ''
      },
      body: formData
    }).then(r => r.json());

    if (res && res.success) {
      window.closeJobApplyModal();
      if (typeof window.showApplicationSubmittedModal === 'function') {
        window.showApplicationSubmittedModal({
          jobId: res.job_id,
          jobTitle: res.job_title,
          companyName: res.company_name
        });
      } else {
        window.showToast(res.message || 'Application submitted successfully!', 'success');
      }
      if (typeof window.loadApplications === 'function') window.loadApplications();
    } else {
      window.showToast(res ? res.message : 'Failed to submit application.', 'error');
    }
  } catch (err) {
    console.error('Application submission error:', err);
    window.showToast('Network error while submitting application.', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Application';
    }
  }
};

// ==============================================================================
// 15. Real-Time Navbar Notifications Dropdown & Badges
// ==============================================================================
window.fetchNavbarUnreadCount = async function() {
  const badge = document.getElementById('navbar-notif-badge');
  if (!badge) return;

  try {
    const res = await fetch('/api/notifications/unread_count', {
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    });
    if (res.ok) {
      const data = await res.json();
      const count = data.unread_count !== undefined ? data.unread_count : data.count || 0;
      if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (e) {
    // Silent catch
  }
};

window.toggleNavbarNotifDropdown = function(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  const dropdown = document.getElementById('navbar-notif-dropdown');
  if (!dropdown) return;

  const isVisible = dropdown.style.display === 'flex';
  if (isVisible) {
    dropdown.style.display = 'none';
  } else {
    dropdown.style.display = 'flex';
    window.loadNavbarNotifsList();
  }
};

window.loadNavbarNotifsList = async function() {
  const listEl = document.getElementById('navbar-notif-list');
  if (!listEl) return;

  try {
    const res = await fetch('/api/notifications?limit=6', {
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    });
    if (res.status === 401) return;
    const data = await res.json();

    if (!data || !data.notifications || data.notifications.length === 0) {
      listEl.innerHTML = '<div style="padding:20px; text-align:center; color:#94A3B8; font-size:0.8125rem;"><i class="fas fa-bell-slash me-1"></i> No notifications yet</div>';
      return;
    }

    listEl.innerHTML = data.notifications.map(n => {
      let icon = 'fa-bell';
      let iconColor = '#06B6D4';
      const t = (n.notification_type || '').toLowerCase();
      if (t.includes('application') || t.includes('shortlist') || t.includes('rejection')) {
        icon = t.includes('shortlist') ? 'fa-star' : t.includes('rejection') ? 'fa-times-circle' : 'fa-briefcase';
        iconColor = '#3B82F6';
      } else if (t.includes('interview')) {
        icon = 'fa-calendar-alt';
        iconColor = '#10B981';
      } else if (t.includes('message')) {
        icon = 'fa-comment-dots';
        iconColor = '#8B5CF6';
      } else if (t.includes('alert') || t.includes('job_alert')) {
        icon = 'fa-bolt';
        iconColor = '#F59E0B';
      } else if (t.includes('assessment')) {
        icon = 'fa-award';
        iconColor = '#EC4899';
      } else if (t.includes('security')) {
        icon = 'fa-shield-alt';
        iconColor = '#EF4444';
      }

      return `
        <div class="notif-mini-item ${n.is_read ? '' : 'unread'}" onclick="handleNavNotifItemClick(${n.id}, '${n.action_url || ''}')">
          <i class="fas ${icon}" style="color:${iconColor}; margin-top:2px; font-size:14px; width:16px;"></i>
          <div style="flex:1; min-width:0;">
            <div style="font-weight:700; font-size:0.8125rem; color:#FFFFFF; margin-bottom:2px; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${n.title || 'Notification'}</div>
            <div style="font-size:0.75rem; color:#94A3B8; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${n.message || ''}</div>
            <div style="font-size:0.6875rem; color:#64748B; margin-top:4px;">${n.time_ago || 'Recently'}</div>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    listEl.innerHTML = '<div style="padding:16px; text-align:center; color:#EF4444; font-size:0.75rem;">Error loading notifications</div>';
  }
};

window.handleNavNotifItemClick = async function(id, actionUrl) {
  try {
    const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    await fetch(`/api/notifications/${id}/read`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    });
  } catch (e) {}

  window.fetchNavbarUnreadCount();
  if (actionUrl && actionUrl !== 'null' && actionUrl !== 'undefined') {
    window.location.href = actionUrl;
  }
};

window.markAllNotificationsReadFromNav = async function(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  try {
    const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const res = await fetch('/api/notifications/mark_all_read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    });
    if (res.ok) {
      if (typeof window.showToast === 'function') window.showToast('All notifications marked as read', 'success');
      window.fetchNavbarUnreadCount();
      window.loadNavbarNotifsList();
    }
  } catch (e) {
    console.error('Error marking read from nav:', e);
  }
};

// Global click outside listener to close notif dropdown
document.addEventListener('click', (e) => {
  const notifDropdown = document.getElementById('navbar-notif-dropdown');
  const notifBtn = document.getElementById('navbar-notif-btn');
  if (notifDropdown && notifDropdown.style.display === 'flex') {
    if (!notifDropdown.contains(e.target) && (!notifBtn || !notifBtn.contains(e.target))) {
      notifDropdown.style.display = 'none';
    }
  }
});

// Auto-fetch unread count on page load
document.addEventListener('DOMContentLoaded', () => {
  window.fetchNavbarUnreadCount();
});
