function toggleTheme() {
  const dark = document.documentElement.classList.toggle("dark");
  localStorage.setItem("theme", dark ? "dark" : "light");
}

let toastTimer;
function showToast(message) {
  const box = document.getElementById("toast");
  box.innerHTML = "";
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  box.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.innerHTML = ""), 2200);
}

function celebrate() {
  const canvas = document.getElementById("confetti");
  const ctx = canvas.getContext("2d");
  canvas.width = innerWidth;
  canvas.height = innerHeight;
  const colors = ["#059669", "#f59e0b", "#10b981", "#fbbf24", "#0ea5e9", "#f43f5e"];
  const pieces = Array.from({ length: 160 }, () => ({
    x: Math.random() * canvas.width,
    y: -20 - Math.random() * canvas.height * 0.5,
    w: 6 + Math.random() * 6,
    h: 8 + Math.random() * 8,
    vy: 2 + Math.random() * 4,
    vx: -2 + Math.random() * 4,
    rot: Math.random() * Math.PI,
    vr: -0.2 + Math.random() * 0.4,
    color: colors[(Math.random() * colors.length) | 0],
  }));
  const start = performance.now();
  (function frame(t) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of pieces) {
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }
    if (t - start < 4000) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  })(start);
}

document.body.addEventListener("toast", (e) => {
  showToast(e.detail.message);
  if (e.detail.celebrate) celebrate();
  if (navigator.vibrate) navigator.vibrate(15);
});

document.body.addEventListener("htmx:responseError", () => {
  showToast("저장하지 못했어요. 잠시 후 다시 시도해 주세요.");
});
document.body.addEventListener("htmx:sendError", () => {
  showToast("인터넷 연결을 확인해 주세요.");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
