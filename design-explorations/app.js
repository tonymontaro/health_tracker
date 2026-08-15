document.querySelectorAll(".concept").forEach((concept) => {
  concept.addEventListener("pointermove", (event) => {
    const bounds = concept.getBoundingClientRect();
    concept.style.setProperty("--pointer-x", `${event.clientX - bounds.left}px`);
    concept.style.setProperty("--pointer-y", `${event.clientY - bounds.top}px`);
  });
});

