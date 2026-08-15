const editionButtons = document.querySelectorAll("[data-edition-target]");
const editions = document.querySelectorAll("[data-edition]");
const toast = document.querySelector(".toast");
const workoutStrip = document.querySelector(".workout-strip");
let toastTimer;
let workoutTimer;
let workoutSeconds = 0;

function showEdition(name) {
  editionButtons.forEach((button) => button.classList.toggle("active", button.dataset.editionTarget === name));
  editions.forEach((edition) => edition.classList.toggle("active", edition.dataset.edition === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

editionButtons.forEach((button) => button.addEventListener("click", () => showEdition(button.dataset.editionTarget)));

document.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => {
  document.getElementById(button.dataset.open).showModal();
}));

document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.querySelector(".sheet-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

function showToast() {
  clearTimeout(toastTimer);
  toast.classList.add("show");
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2400);
}

document.querySelectorAll("[data-done]").forEach((button) => button.addEventListener("click", () => {
  button.classList.toggle("done");
  const dialog = button.closest("dialog");
  if (dialog) dialog.close();
  showToast();
}));

document.querySelectorAll("[data-record-tab]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-record-tab]").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll("[data-record-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.recordPanel === button.dataset.recordTab));
}));

document.querySelectorAll(".prompt-row button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".prompt-row button").forEach((item) => item.classList.toggle("selected", item === button));
  button.closest("dialog").querySelector("textarea").value = `${button.textContent}. What would you recommend?`;
}));

function appendConversationMessage(sender, messageText, className) {
  document.querySelectorAll("[data-conversation-list]").forEach((list) => {
    const message = document.createElement("li");
    message.className = `conversation-message ${className}`;
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const author = document.createElement("strong");
    author.textContent = sender;
    const time = document.createElement("time");
    time.textContent = "Just now";
    const copy = document.createElement("p");
    copy.textContent = messageText;
    meta.append(author, time);
    message.append(meta, copy);
    list.append(message);
    list.scrollTop = list.scrollHeight;
  });
}

document.querySelectorAll("[data-chat-form]").forEach((form) => form.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = form.querySelector("[data-chat-input]");
  const message = input.value.trim();
  if (!message) {
    input.focus();
    return;
  }
  appendConversationMessage("You", message, "user-message");
  input.value = "";
  showToast();
  setTimeout(() => appendConversationMessage("AI coach", "I have that. I’ll keep today’s effort controlled and use your next update to refine the plan.", "coach-message"), 450);
}));

document.querySelectorAll(".fake-submit").forEach((button) => button.addEventListener("click", () => {
  button.closest("dialog").close();
  showToast();
}));

function updateWorkoutTime() {
  const minutes = String(Math.floor(workoutSeconds / 60)).padStart(2, "0");
  const seconds = String(workoutSeconds % 60).padStart(2, "0");
  workoutStrip.querySelector("b").textContent = `${minutes}:${seconds}`;
}

document.querySelector("[data-workout-start]").addEventListener("click", (event) => {
  event.currentTarget.closest("dialog").close();
  workoutStrip.classList.add("active");
  if (!workoutTimer) workoutTimer = setInterval(() => { workoutSeconds += 1; updateWorkoutTime(); }, 1000);
});

document.querySelector("[data-pause-workout]").addEventListener("click", (event) => {
  if (workoutTimer) {
    clearInterval(workoutTimer);
    workoutTimer = null;
    event.currentTarget.textContent = "▶";
  } else {
    workoutTimer = setInterval(() => { workoutSeconds += 1; updateWorkoutTime(); }, 1000);
    event.currentTarget.textContent = "Ⅱ";
  }
});

document.querySelector("[data-stop-workout]").addEventListener("click", () => {
  clearInterval(workoutTimer);
  workoutTimer = null;
  workoutSeconds = 0;
  updateWorkoutTime();
  workoutStrip.classList.remove("active");
  document.querySelector("[data-daily-brief-label]").textContent = "Coach feedback / Session complete";
  document.querySelector("[data-daily-brief-title]").innerHTML = "Controlled to the finish.<br><em>Keep the evening easy.</em>";
  document.querySelector("[data-daily-brief-copy]").textContent = "Your pace stayed measured and the final repetition was your cleanest. Eat, recover, and leave the work there.";
  showToast();
});
