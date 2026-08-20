document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-nav-toggle]");
  if (!toggle) return;
  document.querySelector(".nav")?.classList.toggle("open");
});

// Ripple effect for buttons
document.addEventListener("click", function(e) {
  const button = e.target.closest(".btn");
  if (!button) return;

  const ripple = document.createElement("span");
  ripple.classList.add("ripple");
  
  const rect = button.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x = e.clientX - rect.left - size / 2;
  const y = e.clientY - rect.top - size / 2;
  
  ripple.style.width = ripple.style.height = size + "px";
  ripple.style.left = x + "px";
  ripple.style.top = y + "px";
  
  button.appendChild(ripple);
  
  setTimeout(() => ripple.remove(), 600);
});

// Scroll animations
const observerOptions = {
  threshold: 0.1,
  rootMargin: "0px 0px -50px 0px"
};

const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add("animate-fade-in");
      observer.unobserve(entry.target);
    }
  });
}, observerOptions);

// Observe elements for scroll animation
document.querySelectorAll(".features article, .stats-grid article, .card").forEach(el => {
  el.style.opacity = "0";
  observer.observe(el);
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener("click", function(e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute("href"));
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
});

// Header scroll effect
let lastScroll = 0;
const header = document.querySelector(".site-header");

window.addEventListener("scroll", () => {
  const currentScroll = window.pageYOffset;
  
  if (currentScroll <= 0) {
    header.style.boxShadow = "";
  } else if (currentScroll > lastScroll) {
    header.style.boxShadow = "0 4px 20px rgba(18, 35, 58, 0.1)";
  }
  
  lastScroll = currentScroll;
});

// Form input animations
document.querySelectorAll("input, textarea, select").forEach(input => {
  input.addEventListener("focus", function() {
    this.parentElement.classList.add("focused");
  });
  
  input.addEventListener("blur", function() {
    this.parentElement.classList.remove("focused");
  });
});

// Loading states for form submit buttons
document.querySelectorAll("form").forEach(form => {
  form.addEventListener("submit", function() {
    const submitBtn = this.querySelector('.btn[type="submit"]');
    if (submitBtn) {
      submitBtn.innerHTML = '<span class="spinner"></span>';
      submitBtn.disabled = true;
    }
  });
});

// Counter animation for stats
function animateCounter(element, target, duration = 2000) {
  let start = 0;
  const increment = target / (duration / 16);
  
  const updateCounter = () => {
    start += increment;
    if (start < target) {
      element.textContent = Math.floor(start);
      requestAnimationFrame(updateCounter);
    } else {
      element.textContent = target;
    }
  };
  
  updateCounter();
}

// Initialize counters when they come into view
const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const target = parseInt(entry.target.textContent);
      if (!isNaN(target)) {
        animateCounter(entry.target, target);
      }
      counterObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.5 });

document.querySelectorAll(".stat").forEach(stat => {
  counterObserver.observe(stat);
});

// Toast notification system
function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `flash flash-${type} animate-slide-in`;
  toast.textContent = message;
  toast.style.position = "fixed";
  toast.style.top = "20px";
  toast.style.right = "20px";
  toast.style.zIndex = "1000";
  toast.style.maxWidth = "300px";
  
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Make showToast available globally
window.showToast = showToast;
