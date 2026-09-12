/*
 * Adapted from Contoso-State/red-team-agent-orchestration,
 * doc/assets/mission-orbit.html at 953b01d85fac9a6af45618e3f093f08cf5c647ba.
 * Original copyright (c) Microsoft Corporation, MIT. See THIRD_PARTY_NOTICES.txt.
 * AEF adaptation: sequential route, shared-state links, accessible selection,
 * elapsed-time motion, frozen pause, reduced motion and visibility scheduling.
 */
(() => {
  "use strict";
  const canvas = document.querySelector("#orbit");
  const context = canvas.getContext("2d");
  if (!context) return; // The textual graph and node details remain available.
  const motionButton = document.querySelector("#motion");
  const picker = document.querySelector("#orbit-node");
  const resetButton = document.querySelector("#orbit-reset");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const TAU = Math.PI * 2;
  const nodes = [
    { id: "state", label: "SHARED STATE", short: "AEF", type: "core", x: 0, y: 0, z: 0,
      copy: "Each workflow node reads AEFState and returns a StateDelta plus its next route." },
    { id: "retrieve", label: "RETRIEVE", short: "01", type: "agent", x: -190, y: -125, z: -50,
      copy: "Retrieve relevant memory through injected services. Stored lessons remain fallible evidence." },
    { id: "prompt", label: "PROMPT AGENT", short: "02", type: "agent", x: 150, y: -140, z: -75,
      copy: "Call the configured model inside an explicitly nondeterministic node. Tools need target wiring." },
    { id: "reflect", label: "REFLECT", short: "03", type: "agent", x: 220, y: 65, z: 35,
      copy: "Inspect the outcome. Rule-based reflection is implemented; optional LLM reflection defaults off." },
    { id: "consolidate", label: "CONSOLIDATE", short: "04", type: "learning", x: 0, y: 190, z: 45,
      copy: "Update knowledge through injected services. This does not train weights or establish task gains." },
    { id: "end", label: "END", short: "✓", type: "finding", x: -215, y: 65, z: 50,
      copy: "Finish this graph run. There is no automatic route back, self-rewrite or automatic merge." }
  ];
  const edges = [["retrieve", "prompt"], ["prompt", "reflect"], ["reflect", "consolidate"], ["consolidate", "end"]];
  let width = 0, height = 0;
  let rotationX = -0.13, rotationY = 0.18;
  let paused = reduced.matches;
  let selected = "state";
  let dragging = false, moved = false, dragX = 0, dragY = 0, pointerId = null;
  let projected = new Map();
  let elapsed = 0, previous = null, frame = null, visible = true;
  function color(type) {
    return type === "learning" ? "#d4ed9b" : type === "finding" ? "#f1f5e7" : type === "core" ? "#d4ed9b" : "#92c8b0";
  }
  function project(node) {
    const cosY = Math.cos(rotationY);
    const sinY = Math.sin(rotationY);
    const x1 = node.x * cosY - node.z * sinY;
    const z1 = node.x * sinY + node.z * cosY;
    const cosX = Math.cos(rotationX);
    const sinX = Math.sin(rotationX);
    const y2 = node.y * cosX - z1 * sinX;
    const z2 = node.y * sinX + z1 * cosX;
    const camera = 760;
    const scale = camera / (camera + z2);
    const compact = width <= 560;
    const top = 36;
    const bottom = 42;
    const horizontalPadding = compact ? 20 : 34;
    const xCompression = compact ? 0.84 : 1;
    const graphHeight = height - top - bottom;
    const fit = Math.min(
      (width - horizontalPadding - 50) / (610 * xCompression),
      graphHeight / 500
    );
    return {
      x: width / 2 + x1 * scale * fit * xCompression,
      y: top + graphHeight / 2 + y2 * scale * fit,
      z: z2,
      scale
    };
  }

  function drawOrbit(radiusX, radiusY, tilt, color) {
    context.beginPath();
    for (let index = 0; index <= 80; index += 1) {
      const angle = index / 80 * TAU;
      const point = project({ x: Math.cos(angle) * radiusX, y: Math.sin(angle) * radiusY, z: Math.sin(angle) * tilt });
      if (index === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    }
    context.strokeStyle = color;
    context.lineWidth = 0.75;
    context.stroke();
  }

  function drawNode(node, point, time) {
    const active = node.id === selected;
    const core = node.type === "core";
    const radius = (core ? 19 : 11) * Math.max(0.72, point.scale);
    const nodeColor = color(node.type);
    const breathe = Math.sin(time * 0.0018 + node.x) * 1.1;

    context.beginPath();
    context.arc(point.x, point.y, radius + 5 + breathe, 0, TAU);
    context.strokeStyle = active ? nodeColor : `${nodeColor}7a`;
    context.lineWidth = active ? 1.8 : 0.9;
    context.stroke();

    const glow = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius * 3.2);
    glow.addColorStop(0, `${nodeColor}d8`);
    glow.addColorStop(0.28, `${nodeColor}55`);
    glow.addColorStop(1, `${nodeColor}00`);
    context.fillStyle = glow;
    context.beginPath();
    context.arc(point.x, point.y, radius * 3.2, 0, TAU);
    context.fill();

    context.beginPath();
    context.arc(point.x, point.y, radius, 0, TAU);
    context.fillStyle = core ? "#18291d" : nodeColor;
    context.fill();
    context.strokeStyle = nodeColor;
    context.lineWidth = core ? 2 : 1;
    context.stroke();

    context.fillStyle = core ? "#f1f5e7" : "#101913";
    context.font = `800 ${core ? 8.5 : 7.5}px system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(node.short, point.x, point.y + 0.5);

    context.fillStyle = active || core ? "#f1f5e7" : "#c0cebd";
    context.font = `${active || core ? 720 : 620} ${core ? 10.5 : 8.5}px system-ui, sans-serif`;
    context.textBaseline = "top";
    context.shadowBlur = 5;
    context.shadowColor = "#101913";
    context.fillText(node.label, point.x, point.y + radius + 8);
    context.shadowBlur = 0;
  }

  function drawEdge(edge, index) {
    const from = projected.get(edge[0]), to = projected.get(edge[1]);
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.strokeStyle = "#8fae8c";
    context.lineWidth = 1.2;
    context.stroke();
    const angle = Math.atan2(to.y - from.y, to.x - from.x);
    const arrowX = from.x + (to.x - from.x) * 0.78;
    const arrowY = from.y + (to.y - from.y) * 0.78;
    context.beginPath();
    context.moveTo(arrowX, arrowY);
    context.lineTo(arrowX - Math.cos(angle - 0.5) * 6, arrowY - Math.sin(angle - 0.5) * 6);
    context.moveTo(arrowX, arrowY);
    context.lineTo(arrowX - Math.cos(angle + 0.5) * 6, arrowY - Math.sin(angle + 0.5) * 6);
    context.stroke();
    // One illustrative route pulse at a time: AEF does not execute fan-out.
    const step = elapsed / 2200 % 5;
    if (Math.floor(step) !== index) return;
    const phase = step % 1;
    context.beginPath();
    context.fillStyle = "#e7ffac";
    context.shadowColor = "#d4ed9b";
    context.shadowBlur = 14;
    context.arc(from.x + (to.x - from.x) * phase, from.y + (to.y - from.y) * phase, 3, 0, TAU);
    context.fill();
    context.shadowBlur = 0;
  }
  function render() {
    context.clearRect(0, 0, width, height);
    drawOrbit(265, 200, 78, "rgba(146,200,176,.16)");
    drawOrbit(185, 160, -105, "rgba(146,200,176,.11)");
    drawOrbit(125, 210, 50, "rgba(212,237,155,.10)");
    projected = new Map(nodes.map(node => [node.id, project(node)]));
    // Dashed lines are shared-state relationships, never dispatch routes.
    context.setLineDash([3, 6]);
    for (const node of nodes.slice(1, 5)) {
      const from = projected.get("state"), to = projected.get(node.id);
      context.beginPath(); context.moveTo(from.x, from.y); context.lineTo(to.x, to.y);
      context.strokeStyle = "rgba(146,200,176,.25)"; context.lineWidth = 1; context.stroke();
    }
    context.setLineDash([]);
    edges.forEach(drawEdge);
    [...nodes].sort((a, b) => projected.get(b.id).z - projected.get(a.id).z)
      .forEach(node => drawNode(node, projected.get(node.id), elapsed));
  }
  function tick(now) {
    frame = null;
    if (previous !== null) {
      const delta = Math.min(now - previous, 64);
      elapsed += delta;
      // A gentle sweep keeps the route readable instead of turning it edge-on.
      if (!dragging) rotationY += (Math.sin(elapsed / 9000) - Math.sin((elapsed - delta) / 9000)) * 0.48;
    }
    previous = now;
    render();
    schedule();
  }
  function schedule() {
    if (!paused && visible && !document.hidden && frame === null) frame = requestAnimationFrame(tick);
  }
  function stopFrame() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null; previous = null;
  }
  function setPaused(value) {
    paused = value;
    stopFrame();
    motionButton.textContent = paused ? "Resume motion" : "Pause motion";
    motionButton.setAttribute("aria-pressed", String(paused));
    render(); schedule();
  }
  function select(id) {
    selected = id;
    picker.value = id;
    document.querySelector("#orbit-description").textContent = nodes.find(node => node.id === id).copy;
    render();
  }
  function closest(event) {
    const bounds = canvas.getBoundingClientRect();
    let result = null, distance = 26;
    for (const node of nodes) {
      const point = projected.get(node.id);
      if (!point) continue;
      const current = Math.hypot(event.clientX - bounds.left - point.x, event.clientY - bounds.top - point.y);
      if (current < distance) { distance = current; result = node; }
    }
    return result;
  }
  function release() {
    dragging = false;
    if (pointerId !== null && canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
    pointerId = null;
    canvas.style.cursor = "grab";
  }
  canvas.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    dragging = true; moved = false;
    pointerId = event.pointerId;
    dragX = event.clientX; dragY = event.clientY;
    canvas.setPointerCapture(pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (dragging && event.pointerId === pointerId) {
      const dx = event.clientX - dragX, dy = event.clientY - dragY;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      rotationY += dx * 0.006;
      rotationX = Math.max(-0.62, Math.min(0.62, rotationX + dy * 0.004));
      dragX = event.clientX; dragY = event.clientY;
      canvas.style.cursor = "grabbing";
      render();
    } else canvas.style.cursor = closest(event) ? "pointer" : "grab";
  });
  canvas.addEventListener("pointerup", event => {
    if (event.pointerId !== pointerId) return;
    if (!moved) { const node = closest(event); if (node) select(node.id); }
    release();
  });
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("lostpointercapture", release);
  canvas.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") { rotationX = -0.13; rotationY = 0.18; }
    else if (event.key === "ArrowLeft") rotationY -= 0.15;
    else if (event.key === "ArrowRight") rotationY += 0.15;
    else rotationX = Math.max(-0.62, Math.min(0.62, rotationX + (event.key === "ArrowUp" ? -0.1 : 0.1)));
    render();
  });
  picker.addEventListener("change", () => select(picker.value));
  motionButton.addEventListener("click", () => setPaused(!paused));
  resetButton.addEventListener("click", () => { rotationX = -0.13; rotationY = 0.18; render(); });
  reduced.addEventListener("change", event => setPaused(event.matches));
  document.addEventListener("visibilitychange", () => { stopFrame(); schedule(); });
  new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting;
    stopFrame(); schedule();
  }).observe(canvas);
  new ResizeObserver(() => {
    const bounds = canvas.getBoundingClientRect();
    width = bounds.width; height = bounds.height;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    render();
  }).observe(canvas);
  document.querySelectorAll(".orbit-controls [disabled]").forEach(control => { control.disabled = false; });
  setPaused(paused);
})();
