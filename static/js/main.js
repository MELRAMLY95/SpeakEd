const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/* --------------------------------------------------------------------------
   Mobile navigation
   -------------------------------------------------------------------------- */

const navToggle = document.querySelector("[data-nav-toggle]");
const nav = document.querySelector(".nav");

function setNavOpen(open) {
  if (!nav || !navToggle) return;
  nav.classList.toggle("open", open);
  navToggle.setAttribute("aria-expanded", open ? "true" : "false");
}

if (navToggle && nav) {
  navToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    setNavOpen(!nav.classList.contains("open"));
  });

  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) setNavOpen(false);
  });

  document.addEventListener("click", (event) => {
    if (!nav.classList.contains("open")) return;
    if (nav.contains(event.target) || navToggle.contains(event.target)) return;
    setNavOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && nav.classList.contains("open")) {
      setNavOpen(false);
      navToggle.focus();
    }
  });
}

/* --------------------------------------------------------------------------
   Button ripple
   -------------------------------------------------------------------------- */

document.addEventListener("click", (event) => {
  if (prefersReducedMotion.matches) return;
  const button = event.target.closest(".btn");
  if (!button || button.disabled) return;

  const rect = button.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const ripple = document.createElement("span");
  ripple.className = "ripple";
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
  ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

  button.appendChild(ripple);
  setTimeout(() => ripple.remove(), 620);
});

/* --------------------------------------------------------------------------
   Reveal on scroll
   -------------------------------------------------------------------------- */

const revealTargets = document.querySelectorAll(
  ".features article, .stats-grid article, .card, [data-reveal]"
);

if (!prefersReducedMotion.matches && "IntersectionObserver" in window) {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove("will-reveal");
        entry.target.classList.add("animate-fade-in");
        revealObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
  );

  revealTargets.forEach((el, index) => {
    // The hidden state lives in CSS so nothing is stranded invisible if the
    // observer never fires for an element.
    el.classList.add("will-reveal");
    el.style.animationDelay = `${Math.min(index, 5) * 55}ms`;
    revealObserver.observe(el);
  });
}

/* --------------------------------------------------------------------------
   Smooth anchor scrolling
   -------------------------------------------------------------------------- */

document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
  anchor.addEventListener("click", function (event) {
    const href = this.getAttribute("href");
    if (!href || href === "#") return;
    const target = document.querySelector(href);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({
      behavior: prefersReducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
  });
});

/* --------------------------------------------------------------------------
   Header elevation on scroll
   -------------------------------------------------------------------------- */

const header = document.querySelector(".site-header");

if (header) {
  const syncHeader = () => {
    header.classList.toggle("scrolled", window.scrollY > 8);
  };
  syncHeader();
  window.addEventListener("scroll", syncHeader, { passive: true });
}

/* --------------------------------------------------------------------------
   Field focus state
   -------------------------------------------------------------------------- */

document.querySelectorAll("input, textarea, select").forEach((field) => {
  field.addEventListener("focus", () => field.parentElement?.classList.add("focused"));
  field.addEventListener("blur", () => field.parentElement?.classList.remove("focused"));
});

/* --------------------------------------------------------------------------
   Submit button loading state
   -------------------------------------------------------------------------- */

document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", function () {
    const submitBtn = this.querySelector('.btn[type="submit"]');
    if (!submitBtn || submitBtn.disabled) return;
    // Lock the current size so the button does not collapse around the spinner.
    submitBtn.style.minWidth = `${submitBtn.offsetWidth}px`;
    submitBtn.setAttribute("aria-busy", "true");
    submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span class="sr-only">Working…</span>';
    submitBtn.disabled = true;
  });
});

/* --------------------------------------------------------------------------
   Stat counters
   -------------------------------------------------------------------------- */

function animateCounter(element, target, duration = 1200) {
  const start = performance.now();
  const step = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    // Ease-out so the number settles rather than stopping abruptly.
    const eased = 1 - Math.pow(1 - progress, 3);
    element.textContent = Math.round(target * eased);
    if (progress < 1) requestAnimationFrame(step);
    else element.textContent = target;
  };
  requestAnimationFrame(step);
}

if (!prefersReducedMotion.matches && "IntersectionObserver" in window) {
  const counterObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const raw = entry.target.textContent.trim();
        // Only animate plain whole numbers; "12/15" or "—" must stay as written.
        if (/^\d+$/.test(raw)) animateCounter(entry.target, parseInt(raw, 10));
        counterObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.5 }
  );

  document.querySelectorAll(".stat").forEach((stat) => counterObserver.observe(stat));
}

/* --------------------------------------------------------------------------
   Toasts
   -------------------------------------------------------------------------- */

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `flash flash-${type} animate-slide-in`;
  toast.setAttribute("role", "status");
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = "opacity 300ms ease, transform 300ms ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(12px)";
    setTimeout(() => toast.remove(), 320);
  }, 3600);
}

window.showToast = showToast;
