const app = document.getElementById("app");
const apiBaseInput = document.getElementById("api-base");
const apiConfigForm = document.getElementById("api-config-form");

const state = {
  apiBase: localStorage.getItem("signomat_api_base") || defaultApiBase(),
};

apiBaseInput.value = state.apiBase;

apiConfigForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.apiBase = normalizeBase(apiBaseInput.value);
  apiBaseInput.value = state.apiBase;
  localStorage.setItem("signomat_api_base", state.apiBase);
  renderRoute().catch(renderFatalError);
});

window.addEventListener("hashchange", () => {
  renderRoute().catch(renderFatalError);
});

renderRoute().catch(renderFatalError);

async function renderRoute() {
  const route = parseRoute(window.location.hash);
  if (route.name === "trip") {
    await renderTripDetail(route.tripId);
    return;
  }
  if (route.name === "detection") {
    await renderDetectionDetail(route.eventId);
    return;
  }
  if (route.name === "review") {
    await renderReview();
    return;
  }
  if (route.name === "training") {
    await renderTraining();
    return;
  }
  await renderArchive();
}

function parseRoute(hash) {
  const raw = hash.replace(/^#/, "") || "/";
  if (raw.startsWith("/trips/")) {
    return { name: "trip", tripId: decodeURIComponent(raw.split("/")[2] || "") };
  }
  if (raw.startsWith("/detections/")) {
    return { name: "detection", eventId: decodeURIComponent(raw.split("/")[2] || "") };
  }
  if (raw === "/review") {
    return { name: "review" };
  }
  if (raw === "/training") {
    return { name: "training" };
  }
  return { name: "archive" };
}

async function renderArchive() {
  const [detectionsPayload, tripsPayload] = await Promise.all([
    apiFetch("/public/detections?limit=60"),
    apiFetch("/public/trips?limit=24"),
  ]);
  const detections = detectionsPayload.detections || [];
  const trips = tripsPayload.trips || [];
  const uniqueCategories = [...new Set(detections.map((item) => item.categoryLabel).filter(Boolean))].sort();
  const uniqueTrips = trips.map((trip) => trip.tripId);
  const reviewCounts = detections.reduce((counts, detection) => {
    counts[detection.reviewState] = (counts[detection.reviewState] || 0) + 1;
    return counts;
  }, {});

  app.innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Public Archive</p>
          <h2>Trip detections, quick map context, and lightweight review links.</h2>
        </div>
        <p class="status-line">API: ${escapeHtml(state.apiBase)}</p>
      </div>
      <div class="stats-grid">
        <div class="stat"><span class="muted">Visible detections</span><strong>${detections.length}</strong></div>
        <div class="stat"><span class="muted">Trips</span><strong>${trips.length}</strong></div>
        <div class="stat"><span class="muted">Reviewed</span><strong>${reviewCounts.reviewed || 0}</strong></div>
        <div class="stat"><span class="muted">False positives</span><strong>${reviewCounts.false_positive || 0}</strong></div>
      </div>
    </section>

    <div class="archive-layout">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Archive Map</p>
            <h3>Detection field view</h3>
          </div>
          <div class="legend">
            <span><span class="dot" style="background:#0d6c63"></span>reviewed</span>
            <span><span class="dot" style="background:#c46a3d"></span>false positive</span>
            <span><span class="dot" style="background:#8b7a42"></span>unreviewed</span>
          </div>
        </div>
        ${renderScatterMap(detections)}
        <div class="filters">
          <div class="card">
            <div class="muted">Categories on screen</div>
            <div class="pill-row">${uniqueCategories.map((category) => `<span class="pill">${escapeHtml(category)}</span>`).join("") || "<span class=\"muted\">No categories yet</span>"}</div>
          </div>
          <div class="card">
            <div class="muted">Trips in archive</div>
            <div class="pill-row">${uniqueTrips.slice(0, 8).map((tripId) => `<a class="pill" href="#/trips/${encodeURIComponent(tripId)}">${escapeHtml(tripId)}</a>`).join("") || "<span class=\"muted\">No trips yet</span>"}</div>
          </div>
        </div>
        <div class="list">
          ${detections.length ? detections.map((detection) => renderDetectionCard(detection)).join("") : `<div class="empty">No detections available yet.</div>`}
        </div>
      </section>

      <aside class="panel section-stack">
        <div>
          <p class="eyebrow">Trips</p>
          <h3>Recent drive archive</h3>
        </div>
        <div class="list">
          ${trips.length ? trips.map((trip) => renderTripSummaryCard(trip)).join("") : `<div class="empty">No trip metadata has been ingested yet.</div>`}
        </div>
      </aside>
    </div>
  `;
}

async function renderTripDetail(tripId) {
  const payload = await apiFetch(`/public/trips/${encodeURIComponent(tripId)}`);
  const trip = payload.trip;
  const detections = payload.detections || [];
  const gpsPoints = payload.gpsPoints || [];
  const videoSegments = payload.videoSegments || [];

  app.innerHTML = `
    <div class="trip-layout">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Trip Detail</p>
            <h2>${escapeHtml(trip.tripId)}</h2>
          </div>
          <a class="button ghost" href="#/">Back to archive</a>
        </div>
        <div class="meta">
          ${renderMetaItem("Started", formatDate(trip.startedAtUtc))}
          ${renderMetaItem("Ended", formatDate(trip.endedAtUtc))}
          ${renderMetaItem("Status", trip.status)}
          ${renderMetaItem("Detections", String(detections.length))}
        </div>
        <section>
          <div class="panel-head">
            <h3>Route sketch</h3>
            <span class="muted">${gpsPoints.length} GPS points</span>
          </div>
          ${renderRouteMap(gpsPoints)}
        </section>
        <section class="section-stack">
          <div class="panel-head">
            <h3>Detections</h3>
            <span class="muted">${detections.length} archived events</span>
          </div>
          <div class="list">
            ${detections.length ? detections.map((detection) => renderDetectionCard(detection)).join("") : `<div class="empty">This trip does not have detections yet.</div>`}
          </div>
        </section>
      </section>

      <aside class="panel section-stack">
        <div>
          <p class="eyebrow">Trip Media</p>
          <h3>Segments and notes</h3>
        </div>
        <div class="card">
          <div class="meta">
            ${renderMetaItem("Recording", trip.recordingEnabled ? "Enabled" : "Off")}
            ${renderMetaItem("Inference", trip.inferenceEnabled ? "Enabled" : "Off")}
          </div>
          <p class="muted">${escapeHtml(trip.notes || "No trip notes saved.")}</p>
        </div>
        <div class="list">
          ${videoSegments.length ? videoSegments.map(renderVideoSegmentCard).join("") : `<div class="empty">No uploaded video segments for this trip yet.</div>`}
        </div>
      </aside>
    </div>
  `;
}

async function renderDetectionDetail(eventId) {
  const payload = await apiFetch(`/public/detections/${encodeURIComponent(eventId)}`);
  const detection = payload.detection;
  const primaryImage = detection.cleanFrameUrl || detection.annotatedFrameUrl || detection.signCropUrl;
  const secondaryImage = detection.annotatedFrameUrl || detection.signCropUrl || detection.cleanFrameUrl;

  app.innerHTML = `
    <div class="detail-layout">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Detection Detail</p>
            <h2>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h2>
          </div>
          <div class="inline-actions">
            <a class="button ghost" href="#/">Archive</a>
            <a class="button ghost" href="#/trips/${encodeURIComponent(detection.tripId)}">Trip</a>
          </div>
        </div>
        <div class="meta">
          ${renderMetaItem("Timestamp", formatDate(detection.timestampUtc))}
          ${renderMetaItem("Trip", detection.tripId)}
          ${renderMetaItem("Detector", formatPercent(detection.detectorConfidence))}
          ${renderMetaItem("Classifier", formatPercent(detection.classifierConfidence))}
          ${renderMetaItem("Review", detection.reviewState)}
          ${renderMetaItem("Coords", formatCoords(detection.gpsLat, detection.gpsLon))}
        </div>
        <div class="media-viewer section-stack">
          ${primaryImage ? `<img src="${escapeHtml(primaryImage)}" alt="Primary detection frame" />` : `<div class="empty">No full frame image available.</div>`}
          ${secondaryImage && secondaryImage !== primaryImage ? `<img src="${escapeHtml(secondaryImage)}" alt="Secondary detection frame" />` : ""}
          ${detection.signCropUrl ? `<img src="${escapeHtml(detection.signCropUrl)}" alt="Detection crop" />` : ""}
        </div>
      </section>

      <aside class="panel section-stack">
        <div>
          <p class="eyebrow">Metadata</p>
          <h3>Review context</h3>
        </div>
        <div class="card">
          <div class="pill-row">
            <span class="pill ${escapeHtml(detection.reviewState)}">${escapeHtml(detection.reviewState)}</span>
            <span class="pill">${escapeHtml(detection.categoryLabel)}</span>
            ${detection.specificLabel ? `<span class="pill">${escapeHtml(detection.specificLabel)}</span>` : ""}
          </div>
          <dl class="meta">
            ${renderMetaItem("Event ID", detection.eventId)}
            ${renderMetaItem("Raw detector label", detection.rawDetectorLabel || "n/a")}
            ${renderMetaItem("Raw classifier label", detection.rawClassifierLabel || "n/a")}
            ${renderMetaItem("BBox", formatBbox(detection))}
            ${renderMetaItem("Offset ms", detection.videoTimestampOffsetMs != null ? String(detection.videoTimestampOffsetMs) : "n/a")}
          </dl>
          <p class="muted">${escapeHtml(detection.notes || "No review notes yet.")}</p>
        </div>
      </aside>
    </div>
  `;
}

async function renderReview() {
  const [payload, summaryPayload] = await Promise.all([
    apiFetch("/admin/review/queue?limit=80"),
    apiFetch("/admin/training/summary"),
  ]);
  const detections = payload.detections || [];
  const metrics = summaryPayload.modelMetrics || {};

  app.innerHTML = `
    <div class="review-layout">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Admin Review</p>
            <h2>Review images first, confirm sign or not-sign fast, and keep training setup secondary.</h2>
          </div>
          <span class="status-line">Precision is based on reviewed samples only.</span>
        </div>
        <div class="stats-grid">
          <div class="stat"><span class="muted">Reviewed sample</span><strong>${metrics.reviewedSampleSize || 0}</strong></div>
          <div class="stat"><span class="muted">Confirmed signs</span><strong>${metrics.confirmedSignCount || 0}</strong></div>
          <div class="stat"><span class="muted">False positives</span><strong>${metrics.falsePositiveCount || 0}</strong></div>
          <div class="stat"><span class="muted">Current YOLO precision</span><strong>${metrics.reviewedPrecisionEstimate != null ? `${Math.round(metrics.reviewedPrecisionEstimate * 100)}%` : "n/a"}</strong></div>
        </div>
        <div id="review-status" class="status-line">Queue loaded from ${escapeHtml(state.apiBase)}</div>
        <div class="list">
          ${detections.length ? detections.map((detection) => renderReviewCard(detection)).join("") : `<div class="empty">No detections available for review.</div>`}
        </div>
      </section>
    </div>
  `;

  attachReviewHandlers();
}

async function renderTraining() {
  const [summaryPayload, jobsPayload, tripsPayload] = await Promise.all([
    apiFetch("/admin/training/summary"),
    apiFetch("/admin/training/jobs"),
    apiFetch("/public/trips?limit=100"),
  ]);
  const reviewCounts = summaryPayload.reviewCounts || [];
  const topReviewedCategories = summaryPayload.topReviewedCategories || [];
  const topReviewedTrips = summaryPayload.topReviewedTrips || [];
  const jobs = jobsPayload.jobs || [];
  const trips = tripsPayload.trips || [];

  app.innerHTML = `
    <div class="training-layout">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Training Lab</p>
            <h2>Secondary workflow: draft exports after the image review pass is in good shape.</h2>
          </div>
          <span class="status-line">Best handled mostly through code and local training runs.</span>
        </div>

        <div class="stats-grid">
          ${reviewCounts.map((item) => `<div class="stat"><span class="muted">${escapeHtml(item.reviewState)}</span><strong>${item.count}</strong></div>`).join("")}
        </div>

        <div class="card">
          <div class="panel-head">
            <h3>Create training draft</h3>
            <div id="training-status" class="status-line">Pick a scope and create a reusable export.</div>
          </div>
          <form id="training-form" class="filters">
            <input class="field" name="name" placeholder="Draft name (optional)" />
            <select name="modelType">
              <option value="detector">Detector</option>
              <option value="classifier">Classifier</option>
            </select>
            <select name="tripId">
              <option value="">All reviewed trips</option>
              ${trips.map((trip) => `<option value="${escapeHtml(trip.tripId)}">${escapeHtml(trip.tripId)}</option>`).join("")}
            </select>
            <select name="reviewState">
              <option value="reviewed">Reviewed</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="false_positive">False positive</option>
            </select>
            <label class="card"><input type="checkbox" name="includeFalsePositives" /> Include false positives for error analysis</label>
            <textarea class="textarea" name="notes" placeholder="Notes about this training pass"></textarea>
            <button class="primary" type="submit">Create draft</button>
          </form>
        </div>

        <div class="card">
          <div class="panel-head">
            <h3>Reviewed category mix</h3>
            <span class="muted">What you have enough examples for right now.</span>
          </div>
          <div class="pill-row">
            ${topReviewedCategories.length ? topReviewedCategories.map((item) => `<span class="pill">${escapeHtml(item.categoryLabel)} · ${item.count}</span>`).join("") : `<span class="muted">No reviewed categories yet.</span>`}
          </div>
        </div>
      </section>

      <aside class="panel section-stack">
        <div>
          <p class="eyebrow">Draft Jobs</p>
          <h3>Saved export scopes</h3>
        </div>
        <div class="card">
          <div class="pill-row">
            ${topReviewedTrips.length ? topReviewedTrips.map((item) => `<span class="pill">${escapeHtml(item.tripId)} · ${item.count}</span>`).join("") : `<span class="muted">No reviewed trips yet.</span>`}
          </div>
        </div>
        <div class="list" id="training-job-list">
          ${jobs.length ? jobs.map(renderTrainingJobCard).join("") : `<div class="empty">No training drafts yet.</div>`}
        </div>
      </aside>
    </div>
  `;

  attachTrainingHandlers();
}

function attachReviewHandlers() {
  const statusNode = document.getElementById("review-status");
  document.querySelectorAll("[data-review-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const eventId = button.getAttribute("data-review-save");
      const container = document.querySelector(`[data-review-card="${cssEscape(eventId)}"]`);
      const reviewState = container.querySelector("select[name='reviewState']").value;
      const notes = container.querySelector("textarea[name='notes']").value;
      const categoryLabel = container.querySelector("input[name='categoryLabel']").value;
      const specificLabel = container.querySelector("input[name='specificLabel']").value;
      button.disabled = true;
      statusNode.textContent = `Saving ${eventId}...`;
      try {
        await apiFetch(`/admin/detections/${encodeURIComponent(eventId)}/review`, {
          method: "PATCH",
          body: JSON.stringify({
            reviewState,
            notes,
            categoryLabel,
            specificLabel,
          }),
        });
        statusNode.textContent = `Saved ${eventId}.`;
        statusNode.className = "status-line success";
      } catch (error) {
        statusNode.textContent = error.message;
        statusNode.className = "status-line error";
      } finally {
        button.disabled = false;
      }
    });
  });
}

function attachTrainingHandlers() {
  const form = document.getElementById("training-form");
  const statusNode = document.getElementById("training-status");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = {
      name: valueOrNull(formData.get("name")),
      modelType: formData.get("modelType"),
      tripId: valueOrNull(formData.get("tripId")),
      reviewState: formData.get("reviewState"),
      includeFalsePositives: formData.get("includeFalsePositives") === "on",
      notes: valueOrNull(formData.get("notes")),
    };
    statusNode.textContent = "Creating training draft...";
    statusNode.className = "status-line";
    try {
      await apiFetch("/admin/training/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      statusNode.textContent = "Training draft created.";
      statusNode.className = "status-line success";
      await renderTraining();
    } catch (error) {
      statusNode.textContent = error.message;
      statusNode.className = "status-line error";
    }
  });
}

function renderDetectionCard(detection) {
  const thumb = detection.cleanThumbnailUrl || detection.annotatedThumbnailUrl || detection.signCropThumbnailUrl;
  return `
    <article class="card">
      <div class="card-grid">
        <div>
          ${thumb ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(detection.categoryLabel || "detection")}" />` : `<div class="empty">No thumb</div>`}
        </div>
        <div class="section-stack">
          <div class="panel-head">
            <div>
              <div class="pill-row">
                <span class="pill ${escapeHtml(detection.reviewState)}">${escapeHtml(detection.reviewState)}</span>
                <span class="pill">${escapeHtml(detection.categoryLabel || "unknown")}</span>
                ${detection.specificLabel ? `<span class="pill">${escapeHtml(detection.specificLabel)}</span>` : ""}
              </div>
              <h3>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h3>
              <p class="muted">${escapeHtml(formatDate(detection.timestampUtc))}</p>
            </div>
            <div class="inline-actions">
              <a class="button ghost" href="#/detections/${encodeURIComponent(detection.eventId)}">Open</a>
              <a class="button ghost" href="#/trips/${encodeURIComponent(detection.tripId)}">Trip</a>
            </div>
          </div>
          <div class="meta">
            ${renderMetaItem("Trip", detection.tripId)}
            ${renderMetaItem("Detector", formatPercent(detection.detectorConfidence))}
            ${renderMetaItem("Classifier", formatPercent(detection.classifierConfidence))}
            ${renderMetaItem("Coords", formatCoords(detection.gpsLat, detection.gpsLon))}
          </div>
          ${detection.notes ? `<p class="muted">${escapeHtml(detection.notes)}</p>` : ""}
        </div>
      </div>
    </article>
  `;
}

function renderTripSummaryCard(trip) {
  return `
    <article class="card">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(trip.tripId)}</h3>
          <p class="muted">${escapeHtml(formatDate(trip.startedAtUtc))}</p>
        </div>
        <a class="button ghost" href="#/trips/${encodeURIComponent(trip.tripId)}">Open trip</a>
      </div>
      <div class="meta">
        ${renderMetaItem("Status", trip.status)}
        ${renderMetaItem("Detections", String(trip.detectionCount || 0))}
        ${renderMetaItem("Recording", trip.recordingEnabled ? "On" : "Off")}
        ${renderMetaItem("Inference", trip.inferenceEnabled ? "On" : "Off")}
      </div>
    </article>
  `;
}

function renderVideoSegmentCard(segment) {
  return `
    <article class="card">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(segment.videoSegmentId)}</h3>
          <p class="muted">${escapeHtml(formatDate(segment.startTimestampUtc))}</p>
        </div>
        ${segment.mediaUrl ? `<a class="button ghost" href="${escapeHtml(segment.mediaUrl)}" target="_blank" rel="noreferrer">Media</a>` : ""}
      </div>
      <div class="meta">
        ${renderMetaItem("Duration", segment.durationSec != null ? `${segment.durationSec.toFixed(1)} s` : "n/a")}
        ${renderMetaItem("Size", segment.fileSize != null ? formatMegabytes(segment.fileSize) : "n/a")}
      </div>
    </article>
  `;
}

function renderReviewCard(detection) {
  const thumb = bestReviewImageUrl(detection);
  return `
    <article class="card" data-review-card="${escapeHtml(detection.eventId)}">
      <div class="card-grid">
        <div>
          ${thumb ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(detection.categoryLabel || "review image")}" />` : `<div class="empty">No thumb</div>`}
        </div>
        <div class="section-stack">
          <div class="panel-head">
            <div>
              <div class="pill-row">
                <span class="pill ${escapeHtml(detection.reviewState)}">${escapeHtml(detection.reviewState)}</span>
                <span class="pill">${escapeHtml(detection.tripId)}</span>
              </div>
              <h3>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h3>
              <p class="muted">${escapeHtml(formatDate(detection.timestampUtc))}</p>
            </div>
            <a class="button ghost" href="#/detections/${encodeURIComponent(detection.eventId)}">Open detail</a>
          </div>
          <div class="filters">
            <select name="reviewState">
              ${["unreviewed", "reviewed", "false_positive"].map((value) => `<option value="${value}" ${detection.reviewState === value ? "selected" : ""}>${value}</option>`).join("")}
            </select>
            <input class="field" name="categoryLabel" value="${escapeHtml(detection.categoryLabel || "")}" placeholder="Category label" />
            <input class="field" name="specificLabel" value="${escapeHtml(detection.specificLabel || "")}" placeholder="Specific label" />
          </div>
          <textarea class="textarea" name="notes" placeholder="Review notes">${escapeHtml(detection.notes || "")}</textarea>
          <div class="review-actions">
            <button class="primary" type="button" data-review-save="${escapeHtml(detection.eventId)}">Save review</button>
            <button class="ghost" type="button" onclick="location.hash='#/detections/${encodeURIComponent(detection.eventId)}'">Open record</button>
          </div>
        </div>
      </div>
    </article>
  `;
}

function bestReviewImageUrl(detection) {
  return (
    detection.cleanThumbnailUrl ||
    detection.annotatedThumbnailUrl ||
    detection.signCropThumbnailUrl ||
    detection.cleanFrameUrl ||
    detection.annotatedFrameUrl ||
    detection.signCropUrl ||
    null
  );
}

function renderTrainingJobCard(job) {
  return `
    <article class="card">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(job.name)}</h3>
          <p class="muted">${escapeHtml(formatDate(job.createdAtUtc))}</p>
        </div>
        ${job.exportUrl ? `<a class="button ghost" href="${escapeHtml(job.exportUrl)}" target="_blank" rel="noreferrer">Export JSON</a>` : ""}
      </div>
      <div class="meta">
        ${renderMetaItem("Model", job.modelType)}
        ${renderMetaItem("Scope", job.tripId || "all reviewed trips")}
        ${renderMetaItem("State", job.reviewState)}
        ${renderMetaItem("Selected", String(job.selectedCount || 0))}
      </div>
      <pre class="code">${escapeHtml(job.suggestedCommand || "No command generated")}</pre>
      ${job.notes ? `<p class="muted">${escapeHtml(job.notes)}</p>` : ""}
    </article>
  `;
}

function renderMetaItem(label, value) {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "n/a")}</dd></div>`;
}

function renderScatterMap(detections) {
  const points = detections
    .filter((item) => Number.isFinite(item.gpsLat) && Number.isFinite(item.gpsLon))
    .map((item) => ({
      x: item.gpsLon,
      y: item.gpsLat,
      color: item.reviewState === "reviewed" ? "#0d6c63" : item.reviewState === "false_positive" ? "#c46a3d" : "#8b7a42",
      label: item.specificLabel || item.categoryLabel || item.eventId,
      href: `#/detections/${encodeURIComponent(item.eventId)}`,
    }));

  if (!points.length) {
    return `<div class="map-frame empty">No GPS-tagged detections available for the map view yet.</div>`;
  }

  const bounds = getBounds(points);
  const circles = points
    .map((point) => {
      const x = scale(point.x, bounds.minX, bounds.maxX, 30, 770);
      const y = scale(point.y, bounds.minY, bounds.maxY, 330, 30);
      return `<a href="${point.href}"><circle cx="${x}" cy="${y}" r="7" fill="${point.color}" opacity="0.88"><title>${escapeHtml(point.label)}</title></circle></a>`;
    })
    .join("");

  return `
    <div class="map-frame">
      <svg viewBox="0 0 800 360" role="img" aria-label="Detection scatter map">
        ${circles}
      </svg>
    </div>
  `;
}

function renderRouteMap(gpsPoints) {
  const points = gpsPoints
    .filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon))
    .map((item) => ({ x: item.lon, y: item.lat }));

  if (points.length < 2) {
    return `<div class="route-frame empty">Not enough GPS points to draw a route yet.</div>`;
  }

  const bounds = getBounds(points);
  const path = points
    .map((point, index) => {
      const x = scale(point.x, bounds.minX, bounds.maxX, 30, 770);
      const y = scale(point.y, bounds.minY, bounds.maxY, 330, 30);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
  const latest = points[points.length - 1];
  const latestX = scale(latest.x, bounds.minX, bounds.maxX, 30, 770);
  const latestY = scale(latest.y, bounds.minY, bounds.maxY, 330, 30);

  return `
    <div class="route-frame">
      <svg viewBox="0 0 800 360" role="img" aria-label="Trip route sketch">
        <path d="${path}" fill="none" stroke="#0d6c63" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"></path>
        <circle cx="${latestX}" cy="${latestY}" r="8" fill="#8c2f2f"></circle>
      </svg>
    </div>
  `;
}

function getBounds(points) {
  const xs = points.map((item) => item.x);
  const ys = points.map((item) => item.y);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

function scale(value, min, max, outMin, outMax) {
  if (min === max) {
    return (outMin + outMax) / 2;
  }
  const ratio = (value - min) / (max - min);
  return outMin + ratio * (outMax - outMin);
}

async function apiFetch(path, options = {}) {
  const url = `${normalizeBase(state.apiBase)}${path}`;
  const response = await fetch(url, {
    headers: {
      "content-type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function normalizeBase(value) {
  return String(value || window.location.origin).replace(/\/+$/, "");
}

function defaultApiBase() {
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return "http://127.0.0.1:8787";
  }
  return window.location.origin;
}

function formatDate(value) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "n/a";
}

function formatCoords(lat, lon) {
  return Number.isFinite(lat) && Number.isFinite(lon) ? `${lat.toFixed(5)}, ${lon.toFixed(5)}` : "n/a";
}

function formatBbox(detection) {
  const values = [detection.bboxLeft, detection.bboxTop, detection.bboxRight, detection.bboxBottom];
  return values.every((value) => Number.isFinite(value)) ? values.join(", ") : "n/a";
}

function formatMegabytes(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function valueOrNull(value) {
  const text = String(value || "").trim();
  return text ? text : null;
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, "\\$&");
}

function renderFatalError(error) {
  app.innerHTML = `
    <section class="panel">
      <p class="eyebrow">Error</p>
      <h2>Archive UI could not load.</h2>
      <p class="error">${escapeHtml(error.message || String(error))}</p>
      <p class="muted">Check the API base URL in the top bar and make sure the Worker is running.</p>
    </section>
  `;
}
