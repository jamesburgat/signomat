const app = document.getElementById("app");
const apiBaseInput = document.getElementById("api-base");
const adminTokenInput = document.getElementById("admin-token");
const settingsForm = document.getElementById("settings-form");
const configStatus = document.getElementById("config-status");
const configHint = document.getElementById("config-hint");

const state = {
  apiBase: localStorage.getItem("signomat_api_base") || defaultApiBase(),
  adminToken: localStorage.getItem("signomat_admin_token") || "",
  archiveBundle: null,
  archiveBundlePromise: null,
  activeMaps: [],
};

apiBaseInput.value = state.apiBase;
adminTokenInput.value = state.adminToken;

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.apiBase = normalizeBase(apiBaseInput.value);
  state.adminToken = adminTokenInput.value.trim();
  apiBaseInput.value = state.apiBase;
  adminTokenInput.value = state.adminToken;
  localStorage.setItem("signomat_api_base", state.apiBase);
  localStorage.setItem("signomat_admin_token", state.adminToken);
  state.archiveBundle = null;
  state.archiveBundlePromise = null;
  await refreshConfigCheck();
  await renderRoute();
});

window.addEventListener("popstate", () => {
  renderRoute().catch(renderFatalError);
});

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-nav]");
  if (!link) {
    return;
  }
  const href = link.getAttribute("href");
  if (!href || href.startsWith("http") || link.target === "_blank") {
    return;
  }
  event.preventDefault();
  navigate(href);
});

refreshConfigCheck().catch(() => {
  configStatus.textContent = "Unable to reach the archive API yet.";
  configStatus.className = "status-line error";
});

renderRoute().catch(renderFatalError);

async function renderRoute() {
  disposeMaps();
  updateChrome();

  const route = parseRoute();
  app.innerHTML = renderLoadingCard(route.title);

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
  await renderArchive(route.searchParams);
}

function parseRoute() {
  const url = new URL(window.location.href);
  const routeUrl = url.hash.startsWith("#/")
    ? new URL(url.hash.slice(1), `${url.origin}/`)
    : url;
  const parts = routeUrl.pathname.split("/").filter(Boolean);

  if (parts[0] === "trips" && parts[1]) {
    return {
      name: "trip",
      title: "Trip Detail",
      tripId: decodeURIComponent(parts[1]),
      searchParams: routeUrl.searchParams,
    };
  }
  if (parts[0] === "detections" && parts[1]) {
    return {
      name: "detection",
      title: "Detection Detail",
      eventId: decodeURIComponent(parts[1]),
      searchParams: routeUrl.searchParams,
    };
  }
  if (parts[0] === "review") {
    return { name: "review", title: "Admin Review", searchParams: routeUrl.searchParams };
  }
  if (parts[0] === "training") {
    return { name: "training", title: "Training Lab", searchParams: routeUrl.searchParams };
  }
  return { name: "archive", title: "Archive Map", searchParams: routeUrl.searchParams };
}

function updateChrome() {
  const route = parseRoute();
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.toggleAttribute("aria-current", link.getAttribute("data-route") === route.name);
  });
  configHint.textContent = state.adminToken
    ? "Admin token saved in this browser for review and training actions."
    : "Public archive works without a token. Review and training routes need the admin token.";
}

async function renderArchive(searchParams) {
  const bundle = await getArchiveBundle();
  const detections = bundle.detections || [];
  const trips = bundle.trips || [];
  const filters = archiveFiltersFromSearch(searchParams);
  const filteredDetections = filterDetections(detections, filters);
  const filteredTrips = filterTrips(trips, filters);
  const mapDetections = filteredDetections.filter(hasGps);
  const categories = uniqueValues(detections.map((item) => item.categoryLabel));
  const tripIds = uniqueValues(trips.map((item) => item.tripId));
  const selectedDetection = chooseSelectedDetection(filteredDetections, filters.selected);
  const selectedTrip = selectedDetection ? trips.find((trip) => trip.tripId === selectedDetection.tripId) : null;

  app.innerHTML = `
    <section class="panel hero-panel section-stack">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Public Archive</p>
          <h2>Roadside detections mapped by trip, confidence, and review state.</h2>
        </div>
        <div class="hero-note">
          <span class="pill">${escapeHtml(formatDate(bundle.totals.latestDetectionUtc) || "No detections yet")}</span>
          <span class="muted">Latest archived event</span>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat"><span class="muted">All detections</span><strong>${bundle.totals.detectionCount}</strong></div>
        <div class="stat"><span class="muted">Mapped detections</span><strong>${bundle.totals.gpsDetectionCount}</strong></div>
        <div class="stat"><span class="muted">Trips logged</span><strong>${bundle.totals.tripCount}</strong></div>
        <div class="stat"><span class="muted">Reviewed</span><strong>${bundle.totals.reviewedCount}</strong></div>
        <div class="stat"><span class="muted">False positives</span><strong>${bundle.totals.falsePositiveCount}</strong></div>
      </div>
    </section>

    <div class="archive-grid">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Map View</p>
            <h3>Detection field atlas</h3>
          </div>
          <div class="legend">
            <span><span class="dot reviewed"></span>Reviewed</span>
            <span><span class="dot false-positive"></span>False positive</span>
            <span><span class="dot unreviewed"></span>Unreviewed</span>
          </div>
        </div>
        <form id="archive-filter-form" class="filter-strip">
          <label class="field-group">
            <span>Search</span>
            <input class="field" type="search" name="q" value="${escapeAttribute(filters.q)}" placeholder="Trip, category, notes" />
          </label>
          <label class="field-group">
            <span>Category</span>
            <select name="category">
              <option value="">All categories</option>
              ${categories.map((category) => `<option value="${escapeAttribute(category)}" ${filters.category === category ? "selected" : ""}>${escapeHtml(category)}</option>`).join("")}
            </select>
          </label>
          <label class="field-group">
            <span>Review state</span>
            <select name="reviewState">
              <option value="">All states</option>
              ${["reviewed", "unreviewed", "false_positive"].map((value) => `<option value="${value}" ${filters.reviewState === value ? "selected" : ""}>${escapeHtml(formatReviewState(value))}</option>`).join("")}
            </select>
          </label>
          <label class="field-group">
            <span>Trip</span>
            <select name="tripId">
              <option value="">All trips</option>
              ${tripIds.map((tripId) => `<option value="${escapeAttribute(tripId)}" ${filters.tripId === tripId ? "selected" : ""}>${escapeHtml(tripId)}</option>`).join("")}
            </select>
          </label>
          <label class="checkbox-chip">
            <input type="checkbox" name="gpsOnly" ${filters.gpsOnly ? "checked" : ""} />
            GPS-tagged only
          </label>
          <a class="button ghost" data-nav href="/">Reset filters</a>
        </form>
        ${mapDetections.length ? `<div id="archive-map" class="leaflet-frame large"></div>` : `<div class="empty-state">No GPS-tagged detections match this filter set yet.</div>`}
        <div class="status-row">
          <span class="status-line">${filteredDetections.length} detections visible</span>
          <span class="status-line">${mapDetections.length} pinned on the map</span>
        </div>
      </section>

      <aside class="panel section-stack sticky-col">
        <div>
          <p class="eyebrow">Selection</p>
          <h3>${selectedDetection ? escapeHtml(selectedDetection.specificLabel || selectedDetection.categoryLabel || selectedDetection.eventId) : "Nothing selected"}</h3>
        </div>
        ${selectedDetection ? renderSelectedDetection(selectedDetection, selectedTrip) : `<div class="empty-state">Choose a marker or a card to inspect an archived detection.</div>`}
        <div class="card">
          <div class="panel-head">
            <h3>Common categories</h3>
            <span class="muted">Current archive mix</span>
          </div>
          <div class="pill-row">
            ${bundle.categories.length ? bundle.categories.slice(0, 10).map((item) => `<span class="pill">${escapeHtml(item.categoryLabel)} · ${item.count}</span>`).join("") : `<span class="muted">No category counts yet.</span>`}
          </div>
        </div>
      </aside>
    </div>

    <section class="panel section-stack">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Recent detections</p>
          <h3>Filtered archive results</h3>
        </div>
        <span class="muted">${filteredTrips.length} trips represented</span>
      </div>
      <div class="detection-grid">
        ${filteredDetections.length ? filteredDetections.slice(0, 24).map((item) => renderDetectionCard(item, { selected: selectedDetection ? item.eventId === selectedDetection.eventId : false, context: "archive" })).join("") : `<div class="empty-state">No detections match the current filters.</div>`}
      </div>
    </section>

    <section class="panel section-stack">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Trips</p>
          <h3>Recent drives in the archive</h3>
        </div>
      </div>
      <div class="trip-list">
        ${filteredTrips.length ? filteredTrips.slice(0, 18).map(renderTripCard).join("") : `<div class="empty-state">No trips match the current filters.</div>`}
      </div>
    </section>
  `;

  attachArchiveFilterHandlers();
  attachArchiveSelectionHandlers();

  if (mapDetections.length) {
    mountArchiveMap("archive-map", mapDetections, selectedDetection ? selectedDetection.eventId : null);
  }
}

async function renderTripDetail(tripId) {
  const payload = await apiFetch(`/public/trips/${encodeURIComponent(tripId)}`);
  const trip = payload.trip;
  const detections = (payload.detections || []).slice().sort(byTimestampAscending);
  const gpsPoints = payload.gpsPoints || [];
  const videoSegments = payload.videoSegments || [];
  const mappedDetections = detections.filter(hasGps);

  app.innerHTML = `
    <div class="detail-grid">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Trip Detail</p>
            <h2>${escapeHtml(trip.tripId)}</h2>
          </div>
          <div class="inline-actions">
            <a class="button ghost" data-nav href="/">Archive</a>
          </div>
        </div>
        <div class="meta-grid">
          ${renderMetaCard("Started", formatDate(trip.startedAtUtc))}
          ${renderMetaCard("Ended", formatDate(trip.endedAtUtc))}
          ${renderMetaCard("Status", trip.status)}
          ${renderMetaCard("Detections", String(detections.length))}
          ${renderMetaCard("GPS points", String(gpsPoints.length))}
          ${renderMetaCard("Video segments", String(videoSegments.length))}
        </div>
        ${gpsPoints.length || mappedDetections.length ? `<div id="trip-map" class="leaflet-frame large"></div>` : `<div class="empty-state">This trip does not have enough GPS data for a route map yet.</div>`}
        <div class="card route-summary">
          <div class="pill-row">
            <span class="pill">${trip.recordingEnabled ? "Recording on" : "Recording off"}</span>
            <span class="pill">${trip.inferenceEnabled ? "Inference on" : "Inference off"}</span>
          </div>
          <p class="muted">${escapeHtml(trip.notes || "No trip notes were stored for this drive.")}</p>
        </div>
        <section class="section-stack">
          <div class="panel-head">
            <h3>Detection timeline</h3>
            <span class="muted">${detections.length} archived events</span>
          </div>
          <div class="detection-grid">
            ${detections.length ? detections.slice().reverse().map((item) => renderDetectionCard(item, { context: "trip" })).join("") : `<div class="empty-state">No detections were saved for this trip.</div>`}
          </div>
        </section>
      </section>

      <aside class="panel section-stack sticky-col">
        <div>
          <p class="eyebrow">Trip Media</p>
          <h3>Uploaded segments</h3>
        </div>
        <div class="list-stack">
          ${videoSegments.length ? videoSegments.map(renderVideoSegmentCard).join("") : `<div class="empty-state">No uploaded trip segments yet.</div>`}
        </div>
      </aside>
    </div>
  `;

  if (gpsPoints.length || mappedDetections.length) {
    mountTripMap("trip-map", gpsPoints, mappedDetections);
  }
}

async function renderDetectionDetail(eventId) {
  const payload = await apiFetch(`/public/detections/${encodeURIComponent(eventId)}`);
  const detection = payload.detection;
  const tripPayload = detection.tripId ? await apiFetch(`/public/trips/${encodeURIComponent(detection.tripId)}`) : { detections: [], gpsPoints: [] };
  const nearbyDetections = (tripPayload.detections || [])
    .filter((item) => item.eventId !== detection.eventId)
    .sort((left, right) => Math.abs(new Date(left.timestampUtc) - new Date(detection.timestampUtc)) - Math.abs(new Date(right.timestampUtc) - new Date(detection.timestampUtc)))
    .slice(0, 4);

  const mediaUrls = uniqueValues([
    detection.cleanFrameUrl,
    detection.annotatedFrameUrl,
    detection.signCropUrl,
  ].filter(Boolean));

  app.innerHTML = `
    <div class="detail-grid">
      <section class="panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Detection Detail</p>
            <h2>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h2>
          </div>
          <div class="inline-actions">
            <a class="button ghost" data-nav href="/">Archive</a>
            <a class="button ghost" data-nav href="/trips/${encodeURIComponent(detection.tripId)}">Trip</a>
          </div>
        </div>
        <div class="meta-grid">
          ${renderMetaCard("Timestamp", formatDate(detection.timestampUtc))}
          ${renderMetaCard("Trip", detection.tripId)}
          ${renderMetaCard("Review", formatReviewState(detection.reviewState))}
          ${renderMetaCard("Detector", formatPercent(detection.detectorConfidence))}
          ${renderMetaCard("Classifier", formatPercent(detection.classifierConfidence))}
          ${renderMetaCard("Coords", formatCoords(detection.gpsLat, detection.gpsLon))}
        </div>
        <div class="media-grid">
          ${mediaUrls.length ? mediaUrls.map((url, index) => `<figure class="media-card"><img src="${escapeAttribute(url)}" alt="${index === 0 ? "Detection frame" : "Detection reference"}" loading="lazy" /></figure>`).join("") : `<div class="empty-state">No stored media assets are available for this detection yet.</div>`}
        </div>
        ${hasGps(detection) ? `<div id="detail-map" class="leaflet-frame medium"></div>` : `<div class="empty-state">This detection was stored without GPS coordinates.</div>`}
      </section>

      <aside class="panel section-stack sticky-col">
        <div>
          <p class="eyebrow">Metadata</p>
          <h3>Review context</h3>
        </div>
        <div class="card section-stack">
          <div class="pill-row">
            <span class="pill ${escapeAttribute(detection.reviewState)}">${escapeHtml(formatReviewState(detection.reviewState))}</span>
            <span class="pill">${escapeHtml(detection.categoryLabel)}</span>
            ${detection.specificLabel ? `<span class="pill">${escapeHtml(detection.specificLabel)}</span>` : ""}
          </div>
          <dl class="definition-list">
            ${renderDefinitionItem("Event ID", detection.eventId)}
            ${renderDefinitionItem("Raw detector label", detection.rawDetectorLabel || "n/a")}
            ${renderDefinitionItem("Raw classifier label", detection.rawClassifierLabel || "n/a")}
            ${renderDefinitionItem("Bounding box", formatBbox(detection))}
            ${renderDefinitionItem("Suppressed nearby", String(detection.suppressedNearbyCount != null ? detection.suppressedNearbyCount : 0))}
            ${renderDefinitionItem("Video offset", detection.videoTimestampOffsetMs != null ? `${detection.videoTimestampOffsetMs} ms` : "n/a")}
          </dl>
          <p class="muted">${escapeHtml(detection.notes || "No review notes yet.")}</p>
        </div>
        <div class="card section-stack">
          <div class="panel-head">
            <h3>Nearby on this trip</h3>
            <span class="muted">${nearbyDetections.length} related events</span>
          </div>
          <div class="list-stack">
            ${nearbyDetections.length ? nearbyDetections.map((item) => renderDetectionCard(item, { compact: true, context: "detail" })).join("") : `<div class="empty-state">No nearby detections to compare on this trip.</div>`}
          </div>
        </div>
      </aside>
    </div>
  `;

  if (hasGps(detection)) {
    mountDetectionMap("detail-map", detection, tripPayload.gpsPoints || []);
  }
}

async function renderReview() {
  if (!state.adminToken) {
    app.innerHTML = renderAdminLocked("Admin review is locked until you set the archive admin token in the settings panel.");
    return;
  }

  try {
    const [payload, summaryPayload] = await Promise.all([
      apiFetch("/admin/review/queue?limit=120", {}, { admin: true }),
      apiFetch("/admin/training/summary", {}, { admin: true }),
    ]);
    const detections = payload.detections || [];
    const metrics = summaryPayload.modelMetrics || {};

    app.innerHTML = `
      <section class="panel hero-panel section-stack">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Admin Review</p>
            <h2>Confirm detections quickly, relabel the usable ones, and reject the misses.</h2>
          </div>
          <span class="status-line">Protected by the admin token in this browser.</span>
        </div>
        <div class="stats-grid">
          <div class="stat"><span class="muted">Reviewed sample</span><strong>${metrics.reviewedSampleSize || 0}</strong></div>
          <div class="stat"><span class="muted">Confirmed signs</span><strong>${metrics.confirmedSignCount || 0}</strong></div>
          <div class="stat"><span class="muted">False positives</span><strong>${metrics.falsePositiveCount || 0}</strong></div>
          <div class="stat"><span class="muted">Precision estimate</span><strong>${metrics.reviewedPrecisionEstimate != null ? `${Math.round(metrics.reviewedPrecisionEstimate * 100)}%` : "n/a"}</strong></div>
        </div>
        <div id="review-status" class="status-line">Review queue loaded from ${escapeHtml(state.apiBase)}</div>
      </section>

      <section class="panel section-stack">
        <div class="detection-grid review-grid">
          ${detections.length ? detections.map(renderReviewCard).join("") : `<div class="empty-state">No detections are waiting in the review queue.</div>`}
        </div>
      </section>
    `;

    attachReviewHandlers();
  } catch (error) {
    app.innerHTML = renderAdminLocked(error.message);
  }
}

async function renderTraining() {
  if (!state.adminToken) {
    app.innerHTML = renderAdminLocked("Training tools are locked until you set the archive admin token in the settings panel.");
    return;
  }

  try {
    const [summaryPayload, jobsPayload, tripsPayload] = await Promise.all([
      apiFetch("/admin/training/summary", {}, { admin: true }),
      apiFetch("/admin/training/jobs", {}, { admin: true }),
      apiFetch("/public/trips?limit=100"),
    ]);
    const reviewCounts = summaryPayload.reviewCounts || [];
    const topReviewedCategories = summaryPayload.topReviewedCategories || [];
    const topReviewedTrips = summaryPayload.topReviewedTrips || [];
    const jobs = jobsPayload.jobs || [];
    const trips = tripsPayload.trips || [];

    app.innerHTML = `
      <div class="detail-grid">
        <section class="panel section-stack">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Training Lab</p>
              <h2>Turn reviewed archive slices into repeatable export drafts.</h2>
            </div>
            <span class="status-line">Exports stay lightweight and point back to the Worker for download.</span>
          </div>
          <div class="stats-grid">
            ${reviewCounts.map((item) => `<div class="stat"><span class="muted">${escapeHtml(formatReviewState(item.reviewState))}</span><strong>${item.count}</strong></div>`).join("")}
          </div>
          <div class="card section-stack">
            <div class="panel-head">
              <h3>Create training draft</h3>
              <div id="training-status" class="status-line">Pick a scope and create a reusable export.</div>
            </div>
            <form id="training-form" class="training-form">
              <label class="field-group">
                <span>Draft name</span>
                <input class="field" name="name" placeholder="Optional human-readable label" />
              </label>
              <label class="field-group">
                <span>Model type</span>
                <select name="modelType">
                  <option value="detector">Detector</option>
                  <option value="classifier">Classifier</option>
                </select>
              </label>
              <label class="field-group">
                <span>Trip scope</span>
                <select name="tripId">
                  <option value="">All reviewed trips</option>
                  ${trips.map((trip) => `<option value="${escapeAttribute(trip.tripId)}">${escapeHtml(trip.tripId)}</option>`).join("")}
                </select>
              </label>
              <label class="field-group">
                <span>Review state</span>
                <select name="reviewState">
                  <option value="reviewed">Reviewed</option>
                  <option value="unreviewed">Unreviewed</option>
                  <option value="false_positive">False positive</option>
                </select>
              </label>
              <label class="checkbox-chip">
                <input type="checkbox" name="includeFalsePositives" />
                Include false positives for error analysis
              </label>
              <label class="field-group span-all">
                <span>Notes</span>
                <textarea class="textarea" name="notes" placeholder="What this draft is meant to test"></textarea>
              </label>
              <button class="button primary" type="submit">Create draft</button>
            </form>
          </div>
          <div class="card">
            <div class="panel-head">
              <h3>Reviewed category mix</h3>
              <span class="muted">What already has support</span>
            </div>
            <div class="pill-row">
              ${topReviewedCategories.length ? topReviewedCategories.map((item) => `<span class="pill">${escapeHtml(item.categoryLabel)} · ${item.count}</span>`).join("") : `<span class="muted">No reviewed categories yet.</span>`}
            </div>
          </div>
        </section>

        <aside class="panel section-stack sticky-col">
          <div>
            <p class="eyebrow">Saved Drafts</p>
            <h3>Export scopes</h3>
          </div>
          <div class="card">
            <div class="pill-row">
              ${topReviewedTrips.length ? topReviewedTrips.map((item) => `<span class="pill">${escapeHtml(item.tripId)} · ${item.count}</span>`).join("") : `<span class="muted">No reviewed trip clusters yet.</span>`}
            </div>
          </div>
          <div class="list-stack" id="training-job-list">
            ${jobs.length ? jobs.map(renderTrainingJobCard).join("") : `<div class="empty-state">No training drafts saved yet.</div>`}
          </div>
        </aside>
      </div>
    `;

    attachTrainingHandlers();
  } catch (error) {
    app.innerHTML = renderAdminLocked(error.message);
  }
}

function attachArchiveFilterHandlers() {
  const form = document.getElementById("archive-filter-form");
  if (!form) {
    return;
  }

  let timer = 0;
  const commit = () => {
    const formData = new FormData(form);
    const next = new URLSearchParams();
    setIfPresent(next, "q", valueOrNull(formData.get("q")));
    setIfPresent(next, "category", valueOrNull(formData.get("category")));
    setIfPresent(next, "reviewState", valueOrNull(formData.get("reviewState")));
    setIfPresent(next, "tripId", valueOrNull(formData.get("tripId")));
    if (formData.get("gpsOnly") === "on") {
      next.set("gpsOnly", "1");
    }
    navigate(`/?${next.toString()}`, { replace: true });
  };

  form.addEventListener("change", commit);
  form.addEventListener("input", (event) => {
    if (event.target.name !== "q") {
      return;
    }
    window.clearTimeout(timer);
    timer = window.setTimeout(commit, 180);
  });
}

function attachArchiveSelectionHandlers() {
  document.querySelectorAll("[data-select-detection]").forEach((button) => {
    button.addEventListener("click", () => {
      const eventId = button.getAttribute("data-select-detection");
      if (!eventId) {
        return;
      }
      const route = parseRoute();
      const next = new URLSearchParams(route.searchParams);
      next.set("selected", eventId);
      navigate(`/?${next.toString()}`, { replace: true });
    });
  });
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
      statusNode.className = "status-line";
      try {
        await apiFetch(`/admin/detections/${encodeURIComponent(eventId)}/review`, {
          method: "PATCH",
          body: JSON.stringify({
            reviewState,
            notes,
            categoryLabel,
            specificLabel,
          }),
        }, { admin: true });
        state.archiveBundle = null;
        state.archiveBundlePromise = null;
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
  if (!form) {
    return;
  }

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
      }, { admin: true });
      statusNode.textContent = "Training draft created.";
      statusNode.className = "status-line success";
      await renderTraining();
    } catch (error) {
      statusNode.textContent = error.message;
      statusNode.className = "status-line error";
    }
  });

  document.querySelectorAll("[data-export-url]").forEach((button) => {
    button.addEventListener("click", async () => {
      const exportUrl = button.getAttribute("data-export-url");
      const filename = button.getAttribute("data-export-filename") || "signomat-export.json";
      if (!exportUrl) {
        return;
      }
      button.disabled = true;
      statusNode.textContent = "Preparing export download...";
      statusNode.className = "status-line";
      try {
        await downloadAdminExport(exportUrl, filename);
        statusNode.textContent = `Downloaded ${filename}.`;
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

async function getArchiveBundle(force = false) {
  if (state.archiveBundle && !force) {
    return state.archiveBundle;
  }
  if (state.archiveBundlePromise && !force) {
    return state.archiveBundlePromise;
  }

  state.archiveBundlePromise = Promise.all([
    apiFetch("/public/stats"),
    apiFetch("/public/detections?limit=500"),
    apiFetch("/public/trips?limit=100"),
  ]).then(([statsPayload, detectionsPayload, tripsPayload]) => {
    state.archiveBundle = {
      totals: statsPayload.totals || {},
      categories: statsPayload.categories || [],
      detections: detectionsPayload.detections || [],
      trips: tripsPayload.trips || [],
    };
    state.archiveBundlePromise = null;
    return state.archiveBundle;
  }).catch((error) => {
    state.archiveBundlePromise = null;
    throw error;
  });

  return state.archiveBundlePromise;
}

async function refreshConfigCheck() {
  try {
    const payload = await apiFetch("/config-check");
    const adminState = payload.hasAdminToken ? "admin auth ready" : "admin auth missing on worker";
    configStatus.textContent = `${payload.hasPublicBaseUrl ? "Public base URL ready" : "Public base URL missing"} · ${adminState}`;
    configStatus.className = "status-line";
  } catch (error) {
    configStatus.textContent = error.message;
    configStatus.className = "status-line error";
  }
}

function renderSelectedDetection(detection, trip) {
  const thumb = bestThumbnail(detection);
  return `
    <article class="feature-card section-stack">
      ${thumb ? `<img class="hero-thumb" src="${escapeAttribute(thumb)}" alt="${escapeAttribute(detection.categoryLabel || "detection")}" loading="lazy" />` : `<div class="empty-state">No image stored for this detection.</div>`}
      <div class="pill-row">
        <span class="pill ${escapeAttribute(detection.reviewState)}">${escapeHtml(formatReviewState(detection.reviewState))}</span>
        <span class="pill">${escapeHtml(detection.categoryLabel || "Unknown")}</span>
        ${trip ? `<span class="pill">${escapeHtml(trip.tripId)}</span>` : ""}
      </div>
      <div class="section-stack tight">
        <div class="meta-inline">
          <span>${escapeHtml(formatDate(detection.timestampUtc))}</span>
          <span>${escapeHtml(formatCoords(detection.gpsLat, detection.gpsLon))}</span>
        </div>
        <p class="muted">${escapeHtml(detection.notes || "No review notes on this event yet.")}</p>
      </div>
      <div class="inline-actions">
        <button class="button primary" type="button" data-select-detection="${escapeAttribute(detection.eventId)}">Keep selected</button>
        <a class="button ghost" data-nav href="/detections/${encodeURIComponent(detection.eventId)}">Open detail</a>
        <a class="button ghost" data-nav href="/trips/${encodeURIComponent(detection.tripId)}">Open trip</a>
      </div>
    </article>
  `;
}

function renderDetectionCard(detection, options = {}) {
  const thumb = bestThumbnail(detection);
  const compactClass = options.compact ? "compact-card" : "";
  const selectedClass = options.selected ? "selected" : "";
  return `
    <article class="detection-card ${compactClass} ${selectedClass}">
      <div class="card-media">
        ${thumb ? `<img src="${escapeAttribute(thumb)}" alt="${escapeAttribute(detection.categoryLabel || "detection")}" loading="lazy" />` : `<div class="empty-state compact">No thumb</div>`}
      </div>
      <div class="section-stack">
        <div class="panel-head">
          <div>
            <div class="pill-row">
              <span class="pill ${escapeAttribute(detection.reviewState)}">${escapeHtml(formatReviewState(detection.reviewState))}</span>
              <span class="pill">${escapeHtml(detection.categoryLabel || "unknown")}</span>
            </div>
            <h3>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h3>
            <p class="muted">${escapeHtml(formatDate(detection.timestampUtc))}</p>
          </div>
          <div class="inline-actions">
            ${options.context === "archive" ? `<button class="button ghost" type="button" data-select-detection="${escapeAttribute(detection.eventId)}">Select</button>` : ""}
            <a class="button ghost" data-nav href="/detections/${encodeURIComponent(detection.eventId)}">Open</a>
          </div>
        </div>
        <div class="meta-inline wrap">
          <span>Trip ${escapeHtml(detection.tripId)}</span>
          <span>Detector ${escapeHtml(formatPercent(detection.detectorConfidence))}</span>
          <span>${escapeHtml(formatCoords(detection.gpsLat, detection.gpsLon))}</span>
        </div>
      </div>
    </article>
  `;
}

function renderTripCard(trip) {
  return `
    <article class="trip-card">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(trip.tripId)}</h3>
          <p class="muted">${escapeHtml(formatDate(trip.startedAtUtc))}</p>
        </div>
        <a class="button ghost" data-nav href="/trips/${encodeURIComponent(trip.tripId)}">Open trip</a>
      </div>
      <div class="meta-inline wrap">
        <span>${escapeHtml(trip.status || "unknown")}</span>
        <span>${trip.detectionCount || 0} detections</span>
        <span>${trip.recordingEnabled ? "Recording on" : "Recording off"}</span>
      </div>
    </article>
  `;
}

function renderVideoSegmentCard(segment) {
  return `
    <article class="card section-stack">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(segment.videoSegmentId)}</h3>
          <p class="muted">${escapeHtml(formatDate(segment.startTimestampUtc))}</p>
        </div>
        ${segment.mediaUrl ? `<a class="button ghost" href="${escapeAttribute(segment.mediaUrl)}" target="_blank" rel="noreferrer">Open media</a>` : ""}
      </div>
      <div class="meta-inline wrap">
        <span>${segment.durationSec != null ? `${segment.durationSec.toFixed(1)} s` : "Duration n/a"}</span>
        <span>${segment.fileSize != null ? formatMegabytes(segment.fileSize) : "Size n/a"}</span>
      </div>
    </article>
  `;
}

function renderReviewCard(detection) {
  const thumb = bestThumbnail(detection) || detection.cleanFrameUrl || detection.annotatedFrameUrl || detection.signCropUrl;
  return `
    <article class="review-card" data-review-card="${escapeAttribute(detection.eventId)}">
      <div class="card-media">
        ${thumb ? `<img src="${escapeAttribute(thumb)}" alt="${escapeAttribute(detection.categoryLabel || "review image")}" loading="lazy" />` : `<div class="empty-state compact">No image</div>`}
      </div>
      <div class="section-stack">
        <div class="panel-head">
          <div>
            <div class="pill-row">
              <span class="pill ${escapeAttribute(detection.reviewState)}">${escapeHtml(formatReviewState(detection.reviewState))}</span>
              <span class="pill">${escapeHtml(detection.tripId)}</span>
            </div>
            <h3>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</h3>
            <p class="muted">${escapeHtml(formatDate(detection.timestampUtc))}</p>
          </div>
          <a class="button ghost" data-nav href="/detections/${encodeURIComponent(detection.eventId)}">Open detail</a>
        </div>
        <div class="review-form-grid">
          <label class="field-group">
            <span>Review state</span>
            <select name="reviewState">
              ${["unreviewed", "reviewed", "false_positive"].map((value) => `<option value="${value}" ${detection.reviewState === value ? "selected" : ""}>${escapeHtml(formatReviewState(value))}</option>`).join("")}
            </select>
          </label>
          <label class="field-group">
            <span>Category label</span>
            <input class="field" name="categoryLabel" value="${escapeAttribute(detection.categoryLabel || "")}" />
          </label>
          <label class="field-group">
            <span>Specific label</span>
            <input class="field" name="specificLabel" value="${escapeAttribute(detection.specificLabel || "")}" />
          </label>
          <label class="field-group span-all">
            <span>Notes</span>
            <textarea class="textarea" name="notes">${escapeHtml(detection.notes || "")}</textarea>
          </label>
        </div>
        <div class="inline-actions">
          <button class="button primary" type="button" data-review-save="${escapeAttribute(detection.eventId)}">Save review</button>
          <a class="button ghost" data-nav href="/trips/${encodeURIComponent(detection.tripId)}">Trip</a>
        </div>
      </div>
    </article>
  `;
}

function renderTrainingJobCard(job) {
  return `
    <article class="card section-stack">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(job.name)}</h3>
          <p class="muted">${escapeHtml(formatDate(job.createdAtUtc))}</p>
        </div>
        ${job.exportUrl ? `<button class="button ghost" type="button" data-export-url="${escapeAttribute(job.exportUrl)}" data-export-filename="${escapeAttribute(`${job.jobId || "training-job"}.json`)}">Export JSON</button>` : ""}
      </div>
      <div class="meta-inline wrap">
        <span>${escapeHtml(job.modelType)}</span>
        <span>${escapeHtml(job.tripId || "all reviewed trips")}</span>
        <span>${escapeHtml(formatReviewState(job.reviewState))}</span>
        <span>${job.selectedCount || 0} selected</span>
      </div>
      <pre class="code-block">${escapeHtml(job.suggestedCommand || "No command generated")}</pre>
      ${job.notes ? `<p class="muted">${escapeHtml(job.notes)}</p>` : ""}
    </article>
  `;
}

function renderMetaCard(label, value) {
  return `<div class="meta-card"><span class="muted">${escapeHtml(label)}</span><strong>${escapeHtml(value || "n/a")}</strong></div>`;
}

function renderDefinitionItem(label, value) {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "n/a")}</dd></div>`;
}

function renderLoadingCard(title) {
  return `
    <section class="panel loading-panel">
      <p class="eyebrow">${escapeHtml(title)}</p>
      <h2>Loading archive data...</h2>
    </section>
  `;
}

function renderAdminLocked(message) {
  return `
    <section class="panel locked-panel section-stack">
      <div>
        <p class="eyebrow">Admin Locked</p>
        <h2>Review and training tools are not public.</h2>
      </div>
      <p class="muted">${escapeHtml(message)}</p>
      <p class="muted">Open the settings panel in the header and add the admin token for this Worker.</p>
    </section>
  `;
}

function mountArchiveMap(containerId, detections, selectedEventId) {
  const map = createMap(containerId);
  if (!map) {
    return;
  }

  const markers = detections.map((detection) => {
    const selected = detection.eventId === selectedEventId;
    const marker = L.circleMarker([detection.gpsLat, detection.gpsLon], {
      radius: selected ? 9 : 6,
      weight: selected ? 3 : 2,
      color: "#f9f4e8",
      fillColor: colorForReviewState(detection.reviewState),
      fillOpacity: 0.92,
    });
    marker.bindPopup(`
      <div class="popup-card">
        <strong>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</strong>
        <div>${escapeHtml(formatDate(detection.timestampUtc))}</div>
        <div>${escapeHtml(formatReviewState(detection.reviewState))}</div>
        <div class="popup-actions">
          <a data-nav href="/detections/${encodeURIComponent(detection.eventId)}">Open detail</a>
        </div>
      </div>
    `);
    marker.on("click", () => {
      const route = parseRoute();
      const next = new URLSearchParams(route.searchParams);
      next.set("selected", detection.eventId);
      navigate(`/?${next.toString()}`, { replace: true });
    });
    return marker;
  });

  const group = L.featureGroup(markers).addTo(map);
  fitBounds(map, group.getBounds());

  if (selectedEventId) {
    const selectedMarker = markers.find((marker, index) => detections[index].eventId === selectedEventId);
    if (selectedMarker) {
      selectedMarker.openPopup();
    }
  }
}

function mountTripMap(containerId, gpsPoints, detections) {
  const map = createMap(containerId);
  if (!map) {
    return;
  }

  const routePoints = gpsPoints
    .filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon))
    .map((item) => [item.lat, item.lon]);
  const bounds = [];

  if (routePoints.length >= 2) {
    const line = L.polyline(routePoints, {
      color: "#0d6c63",
      weight: 4,
      opacity: 0.88,
    }).addTo(map);
    bounds.push(line.getBounds());
  }

  detections.forEach((detection) => {
    const marker = L.circleMarker([detection.gpsLat, detection.gpsLon], {
      radius: 6,
      weight: 2,
      color: "#f9f4e8",
      fillColor: colorForReviewState(detection.reviewState),
      fillOpacity: 0.9,
    }).addTo(map);
    marker.bindPopup(`
      <div class="popup-card">
        <strong>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</strong>
        <div>${escapeHtml(formatDate(detection.timestampUtc))}</div>
        <div class="popup-actions">
          <a data-nav href="/detections/${encodeURIComponent(detection.eventId)}">Open detail</a>
        </div>
      </div>
    `);
    bounds.push(marker.getBounds());
  });

  fitCompositeBounds(map, bounds);
}

function mountDetectionMap(containerId, detection, gpsPoints) {
  const map = createMap(containerId);
  if (!map) {
    return;
  }

  const routePoints = gpsPoints
    .filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon))
    .map((item) => [item.lat, item.lon]);
  const bounds = [];

  if (routePoints.length >= 2) {
    const route = L.polyline(routePoints, {
      color: "#658a85",
      weight: 3,
      opacity: 0.55,
      dashArray: "8 6",
    }).addTo(map);
    bounds.push(route.getBounds());
  }

  const marker = L.circleMarker([detection.gpsLat, detection.gpsLon], {
    radius: 8,
    weight: 3,
    color: "#f9f4e8",
    fillColor: colorForReviewState(detection.reviewState),
    fillOpacity: 0.95,
  }).addTo(map);
  marker.bindPopup(`
    <div class="popup-card">
      <strong>${escapeHtml(detection.specificLabel || detection.categoryLabel || detection.eventId)}</strong>
      <div>${escapeHtml(formatCoords(detection.gpsLat, detection.gpsLon))}</div>
    </div>
  `).openPopup();
  bounds.push(marker.getBounds());

  fitCompositeBounds(map, bounds);
}

function createMap(containerId) {
  const container = document.getElementById(containerId);
  if (!container || !window.L) {
    return null;
  }

  const map = L.map(container, {
    zoomControl: true,
    scrollWheelZoom: true,
  });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  state.activeMaps.push(map);
  return map;
}

function fitBounds(map, bounds) {
  if (!bounds || !bounds.isValid()) {
    map.setView([39.5, -98.35], 4);
    return;
  }
  map.fitBounds(bounds, { padding: [24, 24] });
}

function fitCompositeBounds(map, boundsList) {
  const valid = boundsList.filter((bounds) => bounds && bounds.isValid && bounds.isValid());
  if (!valid.length) {
    map.setView([39.5, -98.35], 4);
    return;
  }
  const merged = valid.slice(1).reduce((acc, bounds) => acc.extend(bounds), valid[0]);
  fitBounds(map, merged);
}

function disposeMaps() {
  state.activeMaps.forEach((map) => map.remove());
  state.activeMaps = [];
}

async function apiFetch(path, options = {}, config = {}) {
  const url = `${normalizeBase(state.apiBase)}${path}`;
  const headers = {
    ...(options.body ? { "content-type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  if (config.admin && state.adminToken) {
    headers["x-signomat-admin-token"] = state.adminToken;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function downloadAdminExport(url, filename) {
  const response = await fetch(url, {
    headers: {
      "x-signomat-admin-token": state.adminToken,
    },
  });
  const payload = await response.text();
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const parsed = JSON.parse(payload);
      message = parsed.error || message;
    } catch (_error) {
      // Ignore JSON parse failures and use the status text fallback.
    }
    throw new Error(message);
  }

  const blob = new Blob([payload], { type: "application/json;charset=utf-8" });
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

function navigate(path, options = {}) {
  const next = path.startsWith("/") ? path : `/${path.replace(/^\/+/, "")}`;
  if (options.replace) {
    window.history.replaceState({}, "", next);
  } else {
    window.history.pushState({}, "", next);
  }
  renderRoute().catch(renderFatalError);
}

function archiveFiltersFromSearch(searchParams) {
  return {
    q: searchParams.get("q") || "",
    category: searchParams.get("category") || "",
    reviewState: searchParams.get("reviewState") || "",
    tripId: searchParams.get("tripId") || "",
    gpsOnly: searchParams.get("gpsOnly") === "1",
    selected: searchParams.get("selected") || "",
  };
}

function filterDetections(detections, filters) {
  const needle = filters.q.trim().toLowerCase();
  return detections.filter((item) => {
    if (filters.category && item.categoryLabel !== filters.category) {
      return false;
    }
    if (filters.reviewState && item.reviewState !== filters.reviewState) {
      return false;
    }
    if (filters.tripId && item.tripId !== filters.tripId) {
      return false;
    }
    if (filters.gpsOnly && !hasGps(item)) {
      return false;
    }
    if (!needle) {
      return true;
    }
    const haystack = [
      item.tripId,
      item.categoryLabel,
      item.specificLabel,
      item.notes,
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(needle);
  }).sort(byTimestampDescending);
}

function filterTrips(trips, filters) {
  return trips.filter((trip) => {
    if (filters.tripId && trip.tripId !== filters.tripId) {
      return false;
    }
    if (!filters.q) {
      return true;
    }
    return trip.tripId.toLowerCase().includes(filters.q.trim().toLowerCase());
  });
}

function chooseSelectedDetection(detections, selectedId) {
  return detections.find((item) => item.eventId === selectedId) || detections[0] || null;
}

function bestThumbnail(detection) {
  return detection.cleanThumbnailUrl || detection.annotatedThumbnailUrl || detection.signCropThumbnailUrl || null;
}

function hasGps(item) {
  const lat = item.gpsLat != null ? item.gpsLat : item.lat;
  const lon = item.gpsLon != null ? item.gpsLon : item.lon;
  return Number.isFinite(lat) && Number.isFinite(lon);
}

function colorForReviewState(reviewState) {
  if (reviewState === "reviewed") {
    return "#0d6c63";
  }
  if (reviewState === "false_positive") {
    return "#c46a3d";
  }
  return "#8f7a3f";
}

function byTimestampDescending(left, right) {
  return new Date(right.timestampUtc).getTime() - new Date(left.timestampUtc).getTime();
}

function byTimestampAscending(left, right) {
  return new Date(left.timestampUtc).getTime() - new Date(right.timestampUtc).getTime();
}

function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))];
}

function setIfPresent(searchParams, key, value) {
  if (value) {
    searchParams.set(key, value);
  }
}

function valueOrNull(value) {
  const text = String(value || "").trim();
  return text || null;
}

function normalizeBase(value) {
  return String(value || window.location.origin).replace(/\/+$/, "");
}

function defaultApiBase() {
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return "http://127.0.0.1:8787";
  }
  return "https://signomat-api.burgat-james.workers.dev";
}

function formatDate(value) {
  if (!value) {
    return "";
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
  const parts = [detection.bboxLeft, detection.bboxTop, detection.bboxRight, detection.bboxBottom];
  return parts.every(Number.isFinite) ? parts.join(", ") : "n/a";
}

function formatMegabytes(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatReviewState(value) {
  if (value === "false_positive") {
    return "False positive";
  }
  if (value === "unreviewed") {
    return "Unreviewed";
  }
  return "Reviewed";
}

function escapeHtml(value) {
  return String(value != null ? value : "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function renderFatalError(error) {
  disposeMaps();
  app.innerHTML = `
    <section class="panel locked-panel section-stack">
      <div>
        <p class="eyebrow">Archive Error</p>
        <h2>The archive could not be rendered.</h2>
      </div>
      <p class="muted">${escapeHtml(error.message || "Unknown error")}</p>
    </section>
  `;
}
