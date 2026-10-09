/* Six-box numeric code entry: auto-advance, backspace, arrow keys, paste of the whole code. */

const form = document.getElementById("code-form");
const boxes = [...document.querySelectorAll("[data-code-input] input")];
const hidden = document.getElementById("code-value");
const button = document.getElementById("join-btn");

function value() {
  return boxes.map((b) => b.value).join("");
}

function sync() {
  boxes.forEach((b) => b.classList.toggle("filled", b.value !== ""));
  hidden.value = value();
}

function fill(digits, start = 0) {
  const clean = digits.replace(/\D/g, "").slice(0, boxes.length - start);
  [...clean].forEach((d, i) => (boxes[start + i].value = d));
  sync();
  const next = Math.min(start + clean.length, boxes.length - 1);
  boxes[next].focus();
  if (value().length === boxes.length) button.focus();
}

boxes.forEach((box, i) => {
  box.addEventListener("input", () => {
    const digits = box.value.replace(/\D/g, "");
    box.value = "";
    if (digits) fill(digits, i);
    else sync();
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && !box.value && i > 0) {
      boxes[i - 1].value = "";
      boxes[i - 1].focus();
      sync();
      e.preventDefault();
    } else if (e.key === "ArrowLeft" && i > 0) boxes[i - 1].focus();
    else if (e.key === "ArrowRight" && i < boxes.length - 1) boxes[i + 1].focus();
    else if (e.key === "Enter") {
      e.preventDefault();
      // requestSubmit() needs iOS 16+; clicking the submit button runs the same validation.
      button.click();
    }
  });
  box.addEventListener("paste", (e) => {
    e.preventDefault();
    fill((e.clipboardData || window.clipboardData).getData("text"), 0);
  });
  box.addEventListener("focus", () => box.select());
});

form.addEventListener("submit", (e) => {
  sync();
  if (hidden.value.length !== boxes.length) {
    e.preventDefault();
    let alert = form.querySelector(".alert");
    if (!alert) {
      alert = document.createElement("div");
      alert.className = "alert";
      alert.setAttribute("role", "alert");
      form.prepend(alert);
    }
    alert.textContent = "ENTER ALL 6 DIGITS";
    boxes[Math.min(hidden.value.length, boxes.length - 1)].focus();
    return;
  }
  button.classList.add("is-busy");
});

// Keep the hidden field in the native form when the page is restored from bfcache.
window.addEventListener("pageshow", () => button.classList.remove("is-busy"));
if (!form.querySelector(".alert")) boxes[0].focus();
