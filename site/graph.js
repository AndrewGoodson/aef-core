/*
 * Adapted from Contoso-State/red-team-agent-orchestration,
 * doc/assets/mission-orbit.html at 953b01d85fac9a6af45618e3f093f08cf5c647ba.
 * Original copyright (c) Microsoft Corporation, MIT. See THIRD_PARTY_NOTICES.txt.
 * AEF adaptation: sequential route, shared-state links, accessible selection,
 * 3D spheres and orbital planes, elapsed-time rotation, accessible motion controls.
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
    { id: "retrieve", label: "RETRIEVE", short: "01", type: "agent", x: -190, y: -145, z: -110,
      copy: "Retrieve relevant memory through injected services. Stored lessons remain fallible evidence." },
    { id: "prompt", label: "PROMPT AGENT", short: "02", type: "agent", x: 180, y: -100, z: 125,
      copy: "Call the configured model inside an explicitly nondeterministic node. Tools need target wiring." },
    { id: "reflect", label: "REFLECT", short: "03", type: "agent", x: 210, y: 115, z: -105,
      copy: "Inspect the outcome. Rule-based reflection is implemented; optional LLM reflection defaults off." },
    { id: "consolidate", label: "CONSOLIDATE", short: "04", type: "learning", x: -25, y: 190, z: 140,
      copy: "Update knowledge through injected services. This does not train weights or establish task gains." },
    { id: "end", label: "END", short: "✓", type: "finding", x: -215, y: 65, z: 80,
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
    return type === "learning" ? "#5ce6d1" : type === "finding" ? "#dcfffa" : type === "core" ? "#5ce6d1" : "#36bcd2";
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
    const camera = 650;
    const scale = camera / (camera + z2);
    const compact = width <= 560;
    const top = 36;
    const bottom = 42;
    const horizontalPadding = compact ? 20 : 34;
    const xCompression = compact ? 0.84 : 1;
    const graphHeight = height - top - bottom;
    const fit = Math.min(
      (width - horizontalPadding - 50) / (730 * xCompression),
      graphHeight / 680
    );
    return {
      x: width / 2 + x1 * scale * fit * xCompression,
      y: top + graphHeight / 2 + y2 * scale * fit,
      z: z2,
      scale
    };
  }

  // Three-dimensional great circles, projected with the same camera as nodes.
  function drawOrbit(radius, plane, tilt) {
    let previousPoint = null;
    for (let index = 0; index <= 120; index += 1) {
      const angle = index / 120 * TAU;
      const a = Math.cos(angle) * radius, b = Math.sin(angle) * radius;
      const point = project(plane === "xz"
        ? { x: a, y: b * Math.sin(tilt), z: b * Math.cos(tilt) }
        : { x: a * Math.cos(tilt), y: b, z: a * Math.sin(tilt) });
      if (previousPoint) {
        context.beginPath();
        context.moveTo(previousPoint.x, previousPoint.y);
        context.lineTo(point.x, point.y);
        const alpha = Math.max(0.035, 0.17 - point.z / 2600);
        context.strokeStyle = `rgba(76,207,223,${alpha})`;
        context.lineWidth = point.z < 0 ? 0.85 : 0.55;
        context.stroke();
      }
      previousPoint = point;
    }
  }

  function drawNode(node, point, time) {
    const active = node.id === selected;
    const core = node.type === "core";
    const radius = (core ? 25 : 16) * Math.max(0.65, point.scale);
    context.globalAlpha = Math.max(0.55, Math.min(1, 1.05 - point.z / 850));
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
    const sphere = context.createRadialGradient(
      point.x - radius * 0.35, point.y - radius * 0.4, radius * 0.04,
      point.x + radius * 0.18, point.y + radius * 0.2, radius * 1.3
    );
    sphere.addColorStop(0, core ? "#b5fff0" : "#e6ffff");
    sphere.addColorStop(0.3, nodeColor);
    sphere.addColorStop(0.68, core ? "#087f83" : "#12607e");
    sphere.addColorStop(1, "#031b2d");
    context.fillStyle = sphere;
    context.fill();
    context.strokeStyle = nodeColor;
    context.lineWidth = core ? 2 : 1;
    context.stroke();

    context.fillStyle = "#032a36";
    context.font = `800 ${core ? 8.5 : 7.5}px system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(node.short, point.x, point.y + 0.5);

    context.fillStyle = active || core ? "#dcfffa" : "#a3d5df";
    context.font = `${active || core ? 720 : 620} ${core ? 10.5 : 8.5}px system-ui, sans-serif`;
    context.textBaseline = "top";
    context.shadowBlur = 5;
    context.shadowColor = "#031923";
    context.fillText(node.label, point.x, point.y + radius + 8);
    context.shadowBlur = 0;
    context.globalAlpha = 1;
  }

  function drawEdge(edge, index) {
    const from = projected.get(edge[0]), to = projected.get(edge[1]);
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.strokeStyle = "#55b1c1";
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
    context.fillStyle = "#a0fff0";
    context.shadowColor = "#5ce6d1";
    context.shadowBlur = 14;
    context.arc(from.x + (to.x - from.x) * phase, from.y + (to.y - from.y) * phase, 3, 0, TAU);
    context.fill();
    context.shadowBlur = 0;
  }
  function render() {
    context.clearRect(0, 0, width, height);
    // Sparse fixed stars give the rotating volume a stable frame of reference.
    for (let i = 0; i < 48; i++) {
      const x = ((i * 137.508) % 100) / 100 * width;
      const y = ((i * 73.31) % 100) / 100 * height;
      context.fillStyle = i % 5 === 0 ? "#6eafbd66" : "#6eafbd26";
      context.beginPath(); context.arc(x, y, i % 5 === 0 ? 1 : 0.6, 0, TAU); context.fill();
    }
    drawOrbit(300, "xz", 0);
    drawOrbit(300, "xy", 0);
    drawOrbit(300, "xy", Math.PI / 2);
    drawOrbit(300, "xz", Math.PI / 4);
    projected = new Map(nodes.map(node => [node.id, project(node)]));
    // Dashed lines are shared-state relationships, never dispatch routes.
    context.setLineDash([3, 6]);
    for (const node of nodes.slice(1, 5)) {
      const from = projected.get("state"), to = projected.get(node.id);
      context.beginPath(); context.moveTo(from.x, from.y); context.lineTo(to.x, to.y);
      context.strokeStyle = "rgba(93,203,219,.28)"; context.lineWidth = 1; context.stroke();
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
      // Full azimuth rotation and a small pitch drift expose all three axes.
      if (!dragging) {
        rotationY += delta * 0.00016;
        rotationX += (Math.sin(elapsed / 8000) - Math.sin((elapsed - delta) / 8000)) * 0.14;
      }
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
