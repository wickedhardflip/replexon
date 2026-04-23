/* RePlexOn - Global JS */

// HTMX CSRF token injection
document.addEventListener('htmx:configRequest', function(evt) {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        evt.detail.headers['X-CSRF-Token'] = csrfMeta.content;
    }
});

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-success').forEach(function(el) {
        setTimeout(function() {
            el.style.transition = 'opacity 0.3s';
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 300);
        }, 5000);
    });

    // Dark mode toggle
    var toggle = document.getElementById('theme-toggle');
    if (toggle) {
        function updateIcon() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            toggle.textContent = isDark ? '\u2600' : '\u263E';
        }
        updateIcon();

        toggle.addEventListener('click', function() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
            }
            updateIcon();
        });
    }

    // Hamburger menu toggle
    var hamburger = document.getElementById('nav-hamburger');
    var navLinks = document.getElementById('nav-links');
    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function() {
            navLinks.classList.toggle('open');
        });
        // Close menu when clicking a link
        navLinks.querySelectorAll('a').forEach(function(link) {
            link.addEventListener('click', function() {
                navLinks.classList.remove('open');
            });
        });
    }
});
