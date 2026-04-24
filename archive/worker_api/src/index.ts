import type {
  AssetPointer,
  DetectionRecord,
  GPSPointRecord,
  IngestBatchRequest,
  IngestBatchResponse,
  TripRecord,
  VideoSegmentRecord,
} from "../../shared/types";

export interface Env {
  ARCHIVE_DB: D1Database;
  MEDIA_BUCKET: R2Bucket;
  THUMBS_BUCKET: R2Bucket;
  SIGNOMAT_INGEST_TOKEN: string;
  PUBLIC_BASE_URL?: string;
}

type JsonPrimitive = null | boolean | number | string;
type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;
type JsonObject = { [key: string]: JsonValue };

type RouteContext = {
  env: Env;
  request: Request;
  url: URL;
};

type DetectionRow = Record<string, unknown>;
type ReviewState = "unreviewed" | "reviewed" | "false_positive";
type TrainingJobRow = Record<string, unknown>;

const REVIEW_STATES = new Set<ReviewState>(["unreviewed", "reviewed", "false_positive"]);

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return corsResponse(new Response(null, { status: 204 }));
    }

    const url = new URL(request.url);
    const ctx: RouteContext = { env, request, url };

    try {
      if (request.method === "GET" && url.pathname === "/health") {
        return json({ ok: true, service: "signomat-api" });
      }

      if (request.method === "GET" && url.pathname === "/config-check") {
        return json({
          ok: true,
          hasIngestToken: Boolean(env.SIGNOMAT_INGEST_TOKEN),
          hasPublicBaseUrl: Boolean(env.PUBLIC_BASE_URL),
        });
      }

      if (request.method === "POST" && url.pathname === "/ingest/batch") {
        return handleIngestBatch(ctx);
      }

      if (request.method === "PUT" && url.pathname === "/ingest/media") {
        return handleIngestMedia(ctx);
      }

      if (request.method === "GET" && url.pathname === "/public/detections") {
        return handlePublicDetections(ctx);
      }

      if (request.method === "GET" && url.pathname.startsWith("/public/detections/")) {
        const eventId = decodeURIComponent(url.pathname.split("/").pop() ?? "");
        return handlePublicDetectionDetail(ctx, eventId);
      }

      if (request.method === "GET" && url.pathname === "/public/trips") {
        return handlePublicTrips(ctx);
      }

      if (request.method === "GET" && url.pathname.startsWith("/public/trips/")) {
        const tripId = decodeURIComponent(url.pathname.split("/").pop() ?? "");
        return handlePublicTripDetail(ctx, tripId);
      }

      if (request.method === "GET" && url.pathname.startsWith("/public/assets/")) {
        return handlePublicAsset(ctx);
      }

      if (request.method === "GET" && url.pathname === "/admin/review/queue") {
        return handleAdminReviewQueue(ctx);
      }

      if (request.method === "PATCH" && url.pathname.startsWith("/admin/detections/") && url.pathname.endsWith("/review")) {
        const parts = url.pathname.split("/");
        const eventId = decodeURIComponent(parts[3] ?? "");
        return handleAdminDetectionReviewUpdate(ctx, eventId);
      }

      if (request.method === "GET" && url.pathname === "/admin/training/summary") {
        return handleAdminTrainingSummary(ctx);
      }

      if (request.method === "GET" && url.pathname === "/admin/training/jobs") {
        return handleAdminTrainingJobs(ctx);
      }

      if (request.method === "POST" && url.pathname === "/admin/training/jobs") {
        return handleAdminTrainingJobCreate(ctx);
      }

      if (request.method === "GET" && url.pathname.startsWith("/admin/training/jobs/") && url.pathname.endsWith("/export")) {
        const parts = url.pathname.split("/");
        const jobId = decodeURIComponent(parts[4] ?? "");
        return handleAdminTrainingJobExport(ctx, jobId);
      }

      return json({ ok: false, error: "not_found" }, 404);
    } catch (error) {
      if (error instanceof HttpError) {
        return json({ ok: false, error: error.message }, error.status);
      }
      const message = error instanceof Error ? error.message : "internal_error";
      return json({ ok: false, error: message }, 500);
    }
  },
};

class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handleIngestBatch(ctx: RouteContext): Promise<Response> {
  requireIngestAuth(ctx);

  const body = (await ctx.request.json()) as IngestBatchRequest;
  validateBatch(body);

  const requestText = JSON.stringify(body);
  const requestSha256 = await sha256Hex(requestText);
  const receiptId = `receipt_${requestSha256.slice(0, 24)}`;
  const now = new Date().toISOString();

  await ctx.env.ARCHIVE_DB.batch([
    ctx.env.ARCHIVE_DB
      .prepare(
        `INSERT INTO ingest_receipts (receipt_id, device_id, uploaded_at_utc, request_sha256, created_at_utc)
         VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(receipt_id) DO UPDATE SET
           device_id=excluded.device_id,
           uploaded_at_utc=excluded.uploaded_at_utc`
      )
      .bind(receiptId, body.deviceId, body.uploadedAtUtc, requestSha256, now),
    ...buildTripStatements(ctx.env.ARCHIVE_DB, body.trips ?? [], now),
    ...buildVideoStatements(ctx.env.ARCHIVE_DB, body.videoSegments ?? [], now),
    ...buildGPSStatements(ctx.env.ARCHIVE_DB, body.gpsPoints ?? [], now),
    ...buildDetectionStatements(ctx.env.ARCHIVE_DB, body.detections ?? [], now),
  ]);

  const response: IngestBatchResponse = {
    ok: true,
    receiptId,
    counts: {
      trips: body.trips?.length ?? 0,
      detections: body.detections?.length ?? 0,
      gpsPoints: body.gpsPoints?.length ?? 0,
      videoSegments: body.videoSegments?.length ?? 0,
    },
  };
  return json(response, 202);
}

async function handleIngestMedia(ctx: RouteContext): Promise<Response> {
  requireIngestAuth(ctx);

  const bucketName = ctx.url.searchParams.get("bucket");
  const key = ctx.url.searchParams.get("key");
  if (!bucketName || !key) {
    throw new HttpError(400, "bucket_and_key_required");
  }

  const bucket = selectBucket(ctx.env, bucketName);
  if (!bucket) {
    throw new HttpError(404, "unknown_bucket");
  }
  if (!ctx.request.body) {
    throw new HttpError(400, "missing_body");
  }

  const contentType = ctx.request.headers.get("content-type") ?? undefined;
  await bucket.put(key, ctx.request.body, {
    httpMetadata: contentType ? { contentType } : undefined,
  });

  return json({ ok: true, bucket: bucketName, key }, 201);
}

async function handlePublicDetections(ctx: RouteContext): Promise<Response> {
  const limit = clampInt(ctx.url.searchParams.get("limit"), 1, 300, 60);
  const category = ctx.url.searchParams.get("category");
  const tripId = ctx.url.searchParams.get("tripId");
  const reviewState = parseReviewStateParam(ctx.url.searchParams.get("reviewState"));

  const filters: string[] = [];
  const bindings: unknown[] = [];
  if (category) {
    filters.push("category_label = ?");
    bindings.push(category);
  }
  if (tripId) {
    filters.push("trip_id = ?");
    bindings.push(tripId);
  }
  if (reviewState) {
    filters.push("review_state = ?");
    bindings.push(reviewState);
  }
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";

  const result = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       event_id,
       trip_id,
       timestamp_utc,
       category_id,
       category_label,
       specific_label,
       grouping_mode,
       raw_detector_label,
       raw_classifier_label,
       detector_confidence,
       classifier_confidence,
       gps_lat,
       gps_lon,
       gps_speed,
       heading,
       bbox_left,
       bbox_top,
       bbox_right,
       bbox_bottom,
       annotated_frame_bucket,
       annotated_frame_key,
       clean_frame_bucket,
       clean_frame_key,
       sign_crop_bucket,
       sign_crop_key,
       annotated_thumb_bucket,
       annotated_thumb_key,
       clean_thumb_bucket,
       clean_thumb_key,
       sign_crop_thumb_bucket,
       sign_crop_thumb_key,
       review_state,
       notes
     FROM detections
     ${where}
     ORDER BY timestamp_utc DESC
     LIMIT ?`
  )
    .bind(...bindings, limit)
    .all<DetectionRow>();

  return json({
    ok: true,
    detections: (result.results ?? []).map((row) => serializeDetectionCard(ctx.env, row)),
  });
}

async function handlePublicDetectionDetail(ctx: RouteContext, eventId: string): Promise<Response> {
  const row = await fetchDetectionRow(ctx.env.ARCHIVE_DB, eventId);
  return json({
    ok: true,
    detection: serializeDetectionDetail(ctx.env, row),
  });
}

async function handlePublicTrips(ctx: RouteContext): Promise<Response> {
  const limit = clampInt(ctx.url.searchParams.get("limit"), 1, 200, 40);
  const result = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       t.trip_id,
       t.started_at_utc,
       t.ended_at_utc,
       t.status,
       t.recording_enabled,
       t.inference_enabled,
       t.notes,
       COUNT(d.event_id) AS detection_count,
       MIN(d.timestamp_utc) AS first_detection_utc,
       MAX(d.timestamp_utc) AS last_detection_utc,
       AVG(d.gps_lat) AS avg_lat,
       AVG(d.gps_lon) AS avg_lon
     FROM trips t
     LEFT JOIN detections d ON d.trip_id = t.trip_id
     GROUP BY t.trip_id
     ORDER BY t.started_at_utc DESC
     LIMIT ?1`
  )
    .bind(limit)
    .all<Record<string, unknown>>();

  return json({
    ok: true,
    trips: (result.results ?? []).map((row) => ({
      tripId: row.trip_id,
      startedAtUtc: row.started_at_utc,
      endedAtUtc: row.ended_at_utc,
      status: row.status,
      recordingEnabled: asBoolean(row.recording_enabled),
      inferenceEnabled: asBoolean(row.inference_enabled),
      notes: row.notes,
      detectionCount: asNumber(row.detection_count, 0),
      firstDetectionUtc: row.first_detection_utc,
      lastDetectionUtc: row.last_detection_utc,
      avgLat: asNullableNumber(row.avg_lat),
      avgLon: asNullableNumber(row.avg_lon),
    })),
  });
}

async function handlePublicTripDetail(ctx: RouteContext, tripId: string): Promise<Response> {
  const trip = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       trip_id,
       started_at_utc,
       ended_at_utc,
       status,
       recording_enabled,
       inference_enabled,
       notes
     FROM trips
     WHERE trip_id = ?1
     LIMIT 1`
  )
    .bind(tripId)
    .first<Record<string, unknown>>();

  if (!trip) {
    throw new HttpError(404, "not_found");
  }

  const detections = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       event_id,
       trip_id,
       timestamp_utc,
       category_id,
       category_label,
       specific_label,
       grouping_mode,
       raw_detector_label,
       raw_classifier_label,
       detector_confidence,
       classifier_confidence,
       gps_lat,
       gps_lon,
       gps_speed,
       heading,
       bbox_left,
       bbox_top,
       bbox_right,
       bbox_bottom,
       annotated_frame_bucket,
       annotated_frame_key,
       clean_frame_bucket,
       clean_frame_key,
       sign_crop_bucket,
       sign_crop_key,
       annotated_thumb_bucket,
       annotated_thumb_key,
       clean_thumb_bucket,
       clean_thumb_key,
       sign_crop_thumb_bucket,
       sign_crop_thumb_key,
       review_state,
       notes
     FROM detections
     WHERE trip_id = ?1
     ORDER BY timestamp_utc DESC
     LIMIT 300`
  )
    .bind(tripId)
    .all<DetectionRow>();

  const gpsPoints = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       gps_point_id,
       timestamp_utc,
       lat,
       lon,
       speed,
       heading,
       altitude,
       fix_quality,
       source
     FROM gps_points
     WHERE trip_id = ?1
     ORDER BY timestamp_utc ASC
     LIMIT 500`
  )
    .bind(tripId)
    .all<Record<string, unknown>>();

  const videoSegments = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       video_segment_id,
       start_timestamp_utc,
       end_timestamp_utc,
       media_bucket,
       media_key,
       file_size,
       duration_sec
     FROM video_segments
     WHERE trip_id = ?1
     ORDER BY start_timestamp_utc ASC`
  )
    .bind(tripId)
    .all<Record<string, unknown>>();

  return json({
    ok: true,
    trip: {
      tripId: trip.trip_id,
      startedAtUtc: trip.started_at_utc,
      endedAtUtc: trip.ended_at_utc,
      status: trip.status,
      recordingEnabled: asBoolean(trip.recording_enabled),
      inferenceEnabled: asBoolean(trip.inference_enabled),
      notes: trip.notes,
    },
    detections: (detections.results ?? []).map((row) => serializeDetectionCard(ctx.env, row)),
    gpsPoints: (gpsPoints.results ?? []).map((row) => ({
      gpsPointId: row.gps_point_id,
      timestampUtc: row.timestamp_utc,
      lat: asNullableNumber(row.lat),
      lon: asNullableNumber(row.lon),
      speed: asNullableNumber(row.speed),
      heading: asNullableNumber(row.heading),
      altitude: asNullableNumber(row.altitude),
      fixQuality: row.fix_quality,
      source: row.source,
    })),
    videoSegments: (videoSegments.results ?? []).map((row) => ({
      videoSegmentId: row.video_segment_id,
      startTimestampUtc: row.start_timestamp_utc,
      endTimestampUtc: row.end_timestamp_utc,
      mediaUrl: publicAssetUrl(ctx.env, row.media_bucket, row.media_key),
      fileSize: asNullableNumber(row.file_size),
      durationSec: asNullableNumber(row.duration_sec),
    })),
  });
}

async function handlePublicAsset(ctx: RouteContext): Promise<Response> {
  const prefix = "/public/assets/";
  const raw = ctx.url.pathname.slice(prefix.length);
  const [bucketName, ...keyParts] = raw.split("/");
  const key = keyParts.join("/");
  if (!bucketName || !key) {
    throw new HttpError(400, "invalid_asset_path");
  }

  const bucket = selectBucket(ctx.env, bucketName);
  if (!bucket) {
    throw new HttpError(404, "unknown_bucket");
  }

  const object = await bucket.get(key);
  if (!object) {
    throw new HttpError(404, "not_found");
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=3600");
  applyCorsHeaders(headers);
  return new Response(object.body, { headers });
}

async function handleAdminReviewQueue(ctx: RouteContext): Promise<Response> {
  const limit = clampInt(ctx.url.searchParams.get("limit"), 1, 300, 80);
  const tripId = ctx.url.searchParams.get("tripId");
  const reviewState = parseReviewStateParam(ctx.url.searchParams.get("reviewState"));

  const filters: string[] = [];
  const bindings: unknown[] = [];
  if (tripId) {
    filters.push("trip_id = ?");
    bindings.push(tripId);
  }
  if (reviewState) {
    filters.push("review_state = ?");
    bindings.push(reviewState);
  }
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";

  const rows = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       event_id,
       trip_id,
       timestamp_utc,
       category_id,
       category_label,
       specific_label,
       grouping_mode,
       raw_detector_label,
       raw_classifier_label,
       detector_confidence,
       classifier_confidence,
       gps_lat,
       gps_lon,
       gps_speed,
       heading,
       bbox_left,
       bbox_top,
       bbox_right,
       bbox_bottom,
       annotated_frame_bucket,
       annotated_frame_key,
       clean_frame_bucket,
       clean_frame_key,
       sign_crop_bucket,
       sign_crop_key,
       annotated_thumb_bucket,
       annotated_thumb_key,
       clean_thumb_bucket,
       clean_thumb_key,
       sign_crop_thumb_bucket,
       sign_crop_thumb_key,
       review_state,
       notes
     FROM detections
     ${where}
     ORDER BY timestamp_utc DESC
     LIMIT ?`
  )
    .bind(...bindings, limit)
    .all<DetectionRow>();

  return json({
    ok: true,
    detections: (rows.results ?? []).map((row) => serializeDetectionCard(ctx.env, row)),
  });
}

async function handleAdminDetectionReviewUpdate(ctx: RouteContext, eventId: string): Promise<Response> {
  const payload = (await ctx.request.json()) as {
    reviewState?: ReviewState | null;
    notes?: string | null;
    categoryLabel?: string | null;
    specificLabel?: string | null;
  };

  if (payload.reviewState !== undefined && payload.reviewState !== null && !REVIEW_STATES.has(payload.reviewState)) {
    throw new HttpError(400, "invalid_review_state");
  }

  const existing = await fetchDetectionRow(ctx.env.ARCHIVE_DB, eventId);
  const reviewState = payload.reviewState ?? asReviewState(existing.review_state);
  const categoryLabel = trimOrNull(payload.categoryLabel) ?? String(existing.category_label);
  const specificLabel = payload.specificLabel === undefined ? existing.specific_label : trimOrNull(payload.specificLabel);
  const notes = payload.notes === undefined ? existing.notes : trimOrNull(payload.notes);
  const now = new Date().toISOString();

  await ctx.env.ARCHIVE_DB.prepare(
    `UPDATE detections
     SET review_state = ?1,
         category_label = ?2,
         specific_label = ?3,
         notes = ?4,
         updated_at_utc = ?5
     WHERE event_id = ?6`
  )
    .bind(reviewState, categoryLabel, specificLabel, notes, now, eventId)
    .run();

  const updated = await fetchDetectionRow(ctx.env.ARCHIVE_DB, eventId);
  return json({
    ok: true,
    detection: serializeDetectionDetail(ctx.env, updated),
  });
}

async function handleAdminTrainingSummary(ctx: RouteContext): Promise<Response> {
  const reviewCounts = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT review_state, COUNT(*) AS count
     FROM detections
     GROUP BY review_state
     ORDER BY review_state ASC`
  ).all<Record<string, unknown>>();

  const precisionRow = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       SUM(CASE WHEN review_state = 'reviewed' THEN 1 ELSE 0 END) AS confirmed_sign_count,
       SUM(CASE WHEN review_state = 'false_positive' THEN 1 ELSE 0 END) AS false_positive_count,
       AVG(CASE WHEN review_state = 'reviewed' THEN detector_confidence END) AS avg_confirmed_detector_confidence,
       AVG(CASE WHEN review_state = 'false_positive' THEN detector_confidence END) AS avg_false_positive_detector_confidence
     FROM detections
     WHERE review_state IN ('reviewed', 'false_positive')`
  ).first<Record<string, unknown>>();

  const categories = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT category_label, COUNT(*) AS count
     FROM detections
     WHERE review_state = 'reviewed'
     GROUP BY category_label
     ORDER BY count DESC, category_label ASC
     LIMIT 20`
  ).all<Record<string, unknown>>();

  const trips = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT trip_id, COUNT(*) AS count
     FROM detections
     WHERE review_state = 'reviewed'
     GROUP BY trip_id
     ORDER BY count DESC, trip_id ASC
     LIMIT 20`
  ).all<Record<string, unknown>>();

  const confirmedSignCount = asNumber(precisionRow?.confirmed_sign_count, 0);
  const falsePositiveCount = asNumber(precisionRow?.false_positive_count, 0);
  const reviewedSampleSize = confirmedSignCount + falsePositiveCount;
  const reviewedPrecisionEstimate = reviewedSampleSize > 0 ? confirmedSignCount / reviewedSampleSize : null;

  return json({
    ok: true,
    reviewCounts: (reviewCounts.results ?? []).map((row) => ({
      reviewState: row.review_state,
      count: asNumber(row.count, 0),
    })),
    modelMetrics: {
      reviewedSampleSize,
      confirmedSignCount,
      falsePositiveCount,
      reviewedPrecisionEstimate,
      avgConfirmedDetectorConfidence: asNullableNumber(precisionRow?.avg_confirmed_detector_confidence),
      avgFalsePositiveDetectorConfidence: asNullableNumber(precisionRow?.avg_false_positive_detector_confidence),
    },
    topReviewedCategories: (categories.results ?? []).map((row) => ({
      categoryLabel: row.category_label,
      count: asNumber(row.count, 0),
    })),
    topReviewedTrips: (trips.results ?? []).map((row) => ({
      tripId: row.trip_id,
      count: asNumber(row.count, 0),
    })),
  });
}

async function handleAdminTrainingJobs(ctx: RouteContext): Promise<Response> {
  const result = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       job_id,
       name,
       model_type,
       status,
       trip_id,
       review_state,
       include_false_positives,
       selected_count,
       notes,
       created_at_utc,
       updated_at_utc
     FROM training_jobs
     ORDER BY created_at_utc DESC
     LIMIT 50`
  ).all<TrainingJobRow>();

  return json({
    ok: true,
    jobs: (result.results ?? []).map((row) => serializeTrainingJob(ctx.env, row)),
  });
}

async function handleAdminTrainingJobCreate(ctx: RouteContext): Promise<Response> {
  const payload = (await ctx.request.json()) as {
    name?: string | null;
    modelType?: string | null;
    tripId?: string | null;
    reviewState?: ReviewState | null;
    includeFalsePositives?: boolean | null;
    notes?: string | null;
  };

  const modelType = payload.modelType === "classifier" ? "classifier" : "detector";
  const tripId = trimOrNull(payload.tripId);
  const includeFalsePositives = Boolean(payload.includeFalsePositives);
  const requestedReviewState = payload.reviewState ?? "reviewed";
  if (!REVIEW_STATES.has(requestedReviewState)) {
    throw new HttpError(400, "invalid_review_state");
  }

  const states = includeFalsePositives
    ? Array.from(new Set<ReviewState>([requestedReviewState, "false_positive"]))
    : [requestedReviewState];
  const stats = await countTrainingSelection(ctx.env.ARCHIVE_DB, tripId, states);
  const now = new Date().toISOString();
  const seed = `${now}:${payload.name ?? ""}:${tripId ?? ""}:${modelType}:${states.join(",")}`;
  const jobId = `job_${(await sha256Hex(seed)).slice(0, 16)}`;
  const name = trimOrNull(payload.name) ?? defaultTrainingJobName(modelType, tripId);
  const notes = trimOrNull(payload.notes);

  await ctx.env.ARCHIVE_DB.prepare(
    `INSERT INTO training_jobs (
       job_id,
       name,
       model_type,
       status,
       trip_id,
       review_state,
       include_false_positives,
       selected_count,
       notes,
       created_at_utc,
       updated_at_utc
     ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)`
  )
    .bind(
      jobId,
      name,
      modelType,
      "draft",
      tripId,
      requestedReviewState,
      boolInt(includeFalsePositives),
      stats.selectedCount,
      notes,
      now,
      now,
    )
    .run();

  const row = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       job_id,
       name,
       model_type,
       status,
       trip_id,
       review_state,
       include_false_positives,
       selected_count,
       notes,
       created_at_utc,
       updated_at_utc
     FROM training_jobs
     WHERE job_id = ?1
     LIMIT 1`
  )
    .bind(jobId)
    .first<TrainingJobRow>();

  return json({
    ok: true,
    job: serializeTrainingJob(ctx.env, row ?? {}),
    selection: stats,
  }, 201);
}

async function handleAdminTrainingJobExport(ctx: RouteContext, jobId: string): Promise<Response> {
  const row = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       job_id,
       name,
       model_type,
       status,
       trip_id,
       review_state,
       include_false_positives,
       selected_count,
       notes,
       created_at_utc,
       updated_at_utc
     FROM training_jobs
     WHERE job_id = ?1
     LIMIT 1`
  )
    .bind(jobId)
    .first<TrainingJobRow>();

  if (!row) {
    throw new HttpError(404, "not_found");
  }

  const states = trainingJobReviewStates(row);
  const { sql, bindings } = buildDetectionSelectionQuery(row.trip_id ? String(row.trip_id) : null, states, 1000);
  const detections = await ctx.env.ARCHIVE_DB.prepare(sql).bind(...bindings).all<DetectionRow>();

  return json({
    ok: true,
    job: serializeTrainingJob(ctx.env, row),
    detections: (detections.results ?? []).map((detection) => serializeDetectionDetail(ctx.env, detection)),
    exportNotes: [
      "This low-fi export is meant to get your reviewed archive data into a repeatable training loop quickly.",
      "Detector jobs include both positives and optional false positives so you can audit failure modes.",
      "Classifier jobs are best when you have relabeled reviewed detections into stable specific labels.",
    ],
  });
}

async function fetchDetectionRow(db: D1Database, eventId: string): Promise<DetectionRow> {
  const row = await db.prepare(`SELECT * FROM detections WHERE event_id = ?1 LIMIT 1`).bind(eventId).first<DetectionRow>();
  if (!row) {
    throw new HttpError(404, "not_found");
  }
  return row;
}

function serializeDetectionCard(env: Env, row: DetectionRow): JsonObject {
  return {
    eventId: asString(row.event_id),
    tripId: asString(row.trip_id),
    timestampUtc: asString(row.timestamp_utc),
    categoryId: asString(row.category_id),
    categoryLabel: asString(row.category_label),
    specificLabel: asNullableString(row.specific_label),
    groupingMode: asNullableString(row.grouping_mode),
    rawDetectorLabel: asNullableString(row.raw_detector_label),
    rawClassifierLabel: asNullableString(row.raw_classifier_label),
    detectorConfidence: asNullableNumber(row.detector_confidence),
    classifierConfidence: asNullableNumber(row.classifier_confidence),
    gpsLat: asNullableNumber(row.gps_lat),
    gpsLon: asNullableNumber(row.gps_lon),
    gpsSpeed: asNullableNumber(row.gps_speed),
    heading: asNullableNumber(row.heading),
    bboxLeft: asNullableNumber(row.bbox_left),
    bboxTop: asNullableNumber(row.bbox_top),
    bboxRight: asNullableNumber(row.bbox_right),
    bboxBottom: asNullableNumber(row.bbox_bottom),
    annotatedFrameUrl: publicAssetUrl(env, row.annotated_frame_bucket, row.annotated_frame_key),
    cleanFrameUrl: publicAssetUrl(env, row.clean_frame_bucket, row.clean_frame_key),
    signCropUrl: publicAssetUrl(env, row.sign_crop_bucket, row.sign_crop_key),
    annotatedThumbnailUrl: publicAssetUrl(env, row.annotated_thumb_bucket, row.annotated_thumb_key),
    cleanThumbnailUrl: publicAssetUrl(env, row.clean_thumb_bucket, row.clean_thumb_key),
    signCropThumbnailUrl: publicAssetUrl(env, row.sign_crop_thumb_bucket, row.sign_crop_thumb_key),
    reviewState: asReviewState(row.review_state),
    notes: asNullableString(row.notes),
  };
}

function serializeDetectionDetail(env: Env, row: DetectionRow): JsonObject {
  return {
    ...serializeDetectionCard(env, row),
    videoSegmentId: asNullableString(row.video_segment_id),
    videoTimestampOffsetMs: asNullableNumber(row.video_timestamp_offset_ms),
    dedupeGroupId: asNullableString(row.dedupe_group_id),
    suppressedNearbyCount: asNullableNumber(row.suppressed_nearby_count),
  };
}

function serializeTrainingJob(env: Env, row: TrainingJobRow): JsonObject {
  const tripId = asNullableString(row.trip_id);
  const modelType = asString(row.model_type, "detector");
  const reviewState = asReviewState(row.review_state);
  const includeFalsePositives = asBoolean(row.include_false_positives);
  const jobId = asString(row.job_id);
  const exportUrl = buildPathUrl(env, `/admin/training/jobs/${encodeURIComponent(jobId)}/export`);

  return {
    jobId,
    name: asString(row.name),
    modelType,
    status: asString(row.status, "draft"),
    tripId,
    reviewState,
    includeFalsePositives,
    selectedCount: asNumber(row.selected_count, 0),
    notes: asNullableString(row.notes),
    createdAtUtc: asNullableString(row.created_at_utc),
    updatedAtUtc: asNullableString(row.updated_at_utc),
    exportUrl,
    suggestedCommand: suggestedTrainingCommand(jobId, exportUrl, modelType, tripId, reviewState, includeFalsePositives),
  };
}

async function countTrainingSelection(
  db: D1Database,
  tripId: string | null,
  reviewStates: ReviewState[],
): Promise<{ selectedCount: number; falsePositiveCount: number; reviewStates: ReviewState[] }> {
  const { sql, bindings } = buildDetectionSelectionQuery(tripId, reviewStates, 5000, true);
  const row = await db.prepare(sql).bind(...bindings).first<Record<string, unknown>>();
  return {
    selectedCount: asNumber(row?.selected_count, 0),
    falsePositiveCount: asNumber(row?.false_positive_count, 0),
    reviewStates,
  };
}

function buildDetectionSelectionQuery(
  tripId: string | null,
  reviewStates: ReviewState[],
  limit: number,
  countOnly = false,
): { sql: string; bindings: unknown[] } {
  const filters: string[] = [];
  const bindings: unknown[] = [];
  if (tripId) {
    filters.push("trip_id = ?");
    bindings.push(tripId);
  }
  if (reviewStates.length > 0) {
    const placeholders = reviewStates.map(() => "?").join(",");
    filters.push(`review_state IN (${placeholders})`);
    bindings.push(...reviewStates);
  }
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";
  if (countOnly) {
    return {
      sql: `SELECT
              COUNT(*) AS selected_count,
              SUM(CASE WHEN review_state = 'false_positive' THEN 1 ELSE 0 END) AS false_positive_count
            FROM detections
            ${where}`,
      bindings,
    };
  }
  return {
    sql: `SELECT *
          FROM detections
          ${where}
          ORDER BY timestamp_utc DESC
          LIMIT ?`,
    bindings: [...bindings, limit],
  };
}

function trainingJobReviewStates(row: TrainingJobRow): ReviewState[] {
  const reviewState = asReviewState(row.review_state);
  return asBoolean(row.include_false_positives)
    ? Array.from(new Set<ReviewState>([reviewState, "false_positive"]))
    : [reviewState];
}

function suggestedTrainingCommand(
  jobId: string,
  exportUrl: string | null,
  modelType: string,
  tripId: string | null,
  reviewState: ReviewState,
  includeFalsePositives: boolean,
): string {
  const scopeNote = tripId ? `trip ${tripId}` : "all reviewed trips";
  const falsePositiveNote = includeFalsePositives ? " + false positives" : "";
  if (!exportUrl) {
    return `Download the ${modelType} draft export for ${scopeNote}${falsePositiveNote} and convert it into a local training dataset.`;
  }
  if (modelType === "classifier") {
    return `curl -L "${exportUrl}" -o data/training/archive_exports/${jobId}.json  # classifier archive export from ${scopeNote}, filtered to ${reviewState}${falsePositiveNote}`;
  }
  return `python scripts/export_yolo_detection_dataset.py --archive-export-url "${exportUrl}" --output-dir data/training/exports/${jobId} --image-mode copy  # detector dataset from ${scopeNote}, filtered to ${reviewState}${falsePositiveNote}`;
}

function defaultTrainingJobName(modelType: string, tripId: string | null): string {
  return tripId ? `${modelType}-tune-${tripId}` : `${modelType}-tune-latest`;
}

function requireIngestAuth(ctx: RouteContext): void {
  const auth = ctx.request.headers.get("authorization");
  const expected = `Bearer ${ctx.env.SIGNOMAT_INGEST_TOKEN}`;
  if (auth !== expected) {
    throw new HttpError(401, "unauthorized");
  }
}

function buildTripStatements(db: D1Database, trips: TripRecord[], now: string): D1PreparedStatement[] {
  return trips.map((trip) =>
    db.prepare(
      `INSERT INTO trips (
         trip_id, started_at_utc, ended_at_utc, status, recording_enabled, inference_enabled, notes, updated_at_utc
       ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
       ON CONFLICT(trip_id) DO UPDATE SET
         started_at_utc=excluded.started_at_utc,
         ended_at_utc=excluded.ended_at_utc,
         status=excluded.status,
         recording_enabled=excluded.recording_enabled,
         inference_enabled=excluded.inference_enabled,
         notes=excluded.notes,
         updated_at_utc=excluded.updated_at_utc`
    ).bind(
      trip.tripId,
      trip.startedAtUtc,
      trip.endedAtUtc,
      trip.status,
      boolInt(trip.recordingEnabled),
      boolInt(trip.inferenceEnabled),
      trip.notes ?? null,
      now,
    ),
  );
}

function buildVideoStatements(db: D1Database, segments: VideoSegmentRecord[], now: string): D1PreparedStatement[] {
  return segments.map((segment) =>
    db.prepare(
      `INSERT INTO video_segments (
         video_segment_id, trip_id, start_timestamp_utc, end_timestamp_utc, media_bucket, media_key, file_size, duration_sec, updated_at_utc
       ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
       ON CONFLICT(video_segment_id) DO UPDATE SET
         trip_id=excluded.trip_id,
         start_timestamp_utc=excluded.start_timestamp_utc,
         end_timestamp_utc=excluded.end_timestamp_utc,
         media_bucket=excluded.media_bucket,
         media_key=excluded.media_key,
         file_size=excluded.file_size,
         duration_sec=excluded.duration_sec,
         updated_at_utc=excluded.updated_at_utc`
    ).bind(
      segment.videoSegmentId,
      segment.tripId,
      segment.startTimestampUtc,
      segment.endTimestampUtc,
      bucketName(segment.media),
      bucketKey(segment.media),
      segment.fileSize ?? null,
      segment.durationSec ?? null,
      now,
    ),
  );
}

function buildGPSStatements(db: D1Database, points: GPSPointRecord[], now: string): D1PreparedStatement[] {
  return points.map((point) =>
    db.prepare(
      `INSERT INTO gps_points (
         gps_point_id, trip_id, timestamp_utc, lat, lon, speed, heading, altitude, fix_quality, source, updated_at_utc
       ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
       ON CONFLICT(gps_point_id) DO UPDATE SET
         trip_id=excluded.trip_id,
         timestamp_utc=excluded.timestamp_utc,
         lat=excluded.lat,
         lon=excluded.lon,
         speed=excluded.speed,
         heading=excluded.heading,
         altitude=excluded.altitude,
         fix_quality=excluded.fix_quality,
         source=excluded.source,
         updated_at_utc=excluded.updated_at_utc`
    ).bind(
      point.gpsPointId,
      point.tripId,
      point.timestampUtc,
      point.lat,
      point.lon,
      point.speed ?? null,
      point.heading ?? null,
      point.altitude ?? null,
      point.fixQuality ?? null,
      point.source ?? null,
      now,
    ),
  );
}

function buildDetectionStatements(db: D1Database, detections: DetectionRecord[], now: string): D1PreparedStatement[] {
  return detections.map((detection) =>
    db.prepare(
      `INSERT INTO detections (
         event_id, trip_id, timestamp_utc, category_id, category_label, specific_label, grouping_mode,
         raw_detector_label, raw_classifier_label, detector_confidence, classifier_confidence,
         gps_lat, gps_lon, gps_speed, heading,
         bbox_left, bbox_top, bbox_right, bbox_bottom,
         annotated_frame_bucket, annotated_frame_key,
         clean_frame_bucket, clean_frame_key,
         sign_crop_bucket, sign_crop_key,
         annotated_thumb_bucket, annotated_thumb_key,
         clean_thumb_bucket, clean_thumb_key,
         sign_crop_thumb_bucket, sign_crop_thumb_key,
         video_segment_id, video_timestamp_offset_ms, dedupe_group_id, suppressed_nearby_count, review_state, notes, updated_at_utc
       ) VALUES (
         ?1, ?2, ?3, ?4, ?5, ?6, ?7,
         ?8, ?9, ?10, ?11,
         ?12, ?13, ?14, ?15,
         ?16, ?17, ?18, ?19,
         ?20, ?21,
         ?22, ?23,
         ?24, ?25,
         ?26, ?27,
         ?28, ?29,
         ?30, ?31,
         ?32, ?33, ?34, ?35, ?36, ?37, ?38
       )
       ON CONFLICT(event_id) DO UPDATE SET
         trip_id=excluded.trip_id,
         timestamp_utc=excluded.timestamp_utc,
         category_id=excluded.category_id,
         category_label=excluded.category_label,
         specific_label=excluded.specific_label,
         grouping_mode=excluded.grouping_mode,
         raw_detector_label=excluded.raw_detector_label,
         raw_classifier_label=excluded.raw_classifier_label,
         detector_confidence=excluded.detector_confidence,
         classifier_confidence=excluded.classifier_confidence,
         gps_lat=excluded.gps_lat,
         gps_lon=excluded.gps_lon,
         gps_speed=excluded.gps_speed,
         heading=excluded.heading,
         bbox_left=excluded.bbox_left,
         bbox_top=excluded.bbox_top,
         bbox_right=excluded.bbox_right,
         bbox_bottom=excluded.bbox_bottom,
         annotated_frame_bucket=excluded.annotated_frame_bucket,
         annotated_frame_key=excluded.annotated_frame_key,
         clean_frame_bucket=excluded.clean_frame_bucket,
         clean_frame_key=excluded.clean_frame_key,
         sign_crop_bucket=excluded.sign_crop_bucket,
         sign_crop_key=excluded.sign_crop_key,
         annotated_thumb_bucket=excluded.annotated_thumb_bucket,
         annotated_thumb_key=excluded.annotated_thumb_key,
         clean_thumb_bucket=excluded.clean_thumb_bucket,
         clean_thumb_key=excluded.clean_thumb_key,
         sign_crop_thumb_bucket=excluded.sign_crop_thumb_bucket,
         sign_crop_thumb_key=excluded.sign_crop_thumb_key,
         video_segment_id=excluded.video_segment_id,
         video_timestamp_offset_ms=excluded.video_timestamp_offset_ms,
         dedupe_group_id=excluded.dedupe_group_id,
         suppressed_nearby_count=excluded.suppressed_nearby_count,
         review_state=excluded.review_state,
         notes=excluded.notes,
         updated_at_utc=excluded.updated_at_utc`
    ).bind(
      detection.eventId,
      detection.tripId,
      detection.timestampUtc,
      detection.categoryId,
      detection.categoryLabel,
      detection.specificLabel,
      detection.groupingMode,
      detection.rawDetectorLabel ?? null,
      detection.rawClassifierLabel ?? null,
      detection.detectorConfidence ?? null,
      detection.classifierConfidence ?? null,
      detection.gpsLat,
      detection.gpsLon,
      detection.gpsSpeed ?? null,
      detection.heading ?? null,
      detection.bboxLeft ?? null,
      detection.bboxTop ?? null,
      detection.bboxRight ?? null,
      detection.bboxBottom ?? null,
      bucketName(detection.annotatedFrame),
      bucketKey(detection.annotatedFrame),
      bucketName(detection.cleanFrame),
      bucketKey(detection.cleanFrame),
      bucketName(detection.signCrop),
      bucketKey(detection.signCrop),
      bucketName(detection.annotatedThumbnail),
      bucketKey(detection.annotatedThumbnail),
      bucketName(detection.cleanThumbnail),
      bucketKey(detection.cleanThumbnail),
      bucketName(detection.signCropThumbnail),
      bucketKey(detection.signCropThumbnail),
      detection.videoSegmentId,
      detection.videoTimestampOffsetMs ?? null,
      detection.dedupeGroupId ?? null,
      detection.suppressedNearbyCount ?? 0,
      detection.reviewState ?? "unreviewed",
      detection.notes ?? null,
      now,
    ),
  );
}

function validateBatch(body: IngestBatchRequest): void {
  if (!body.deviceId || !body.uploadedAtUtc) {
    throw new HttpError(400, "deviceId_and_uploadedAtUtc_required");
  }
}

function bucketName(asset: AssetPointer | null | undefined): string | null {
  return asset?.bucket ?? null;
}

function bucketKey(asset: AssetPointer | null | undefined): string | null {
  return asset?.key ?? null;
}

function boolInt(value: boolean): number {
  return value ? 1 : 0;
}

function asBoolean(value: unknown): boolean {
  return value === true || value === 1 || value === "1";
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asReviewState(value: unknown): ReviewState {
  return typeof value === "string" && REVIEW_STATES.has(value as ReviewState) ? (value as ReviewState) : "unreviewed";
}

function trimOrNull(value: string | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function clampInt(raw: string | null, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function parseReviewStateParam(raw: string | null): ReviewState | null {
  if (!raw) {
    return null;
  }
  if (!REVIEW_STATES.has(raw as ReviewState)) {
    throw new HttpError(400, "invalid_review_state");
  }
  return raw as ReviewState;
}

function publicAssetUrl(env: Env, bucket: unknown, key: unknown): string | null {
  if (!bucket || !key || !env.PUBLIC_BASE_URL) {
    return null;
  }
  const url = new URL(env.PUBLIC_BASE_URL);
  url.pathname = `/public/assets/${String(bucket)}/${String(key)}`;
  return url.toString();
}

function buildPathUrl(env: Env, path: string): string | null {
  if (!env.PUBLIC_BASE_URL) {
    return null;
  }
  const url = new URL(env.PUBLIC_BASE_URL);
  url.pathname = path;
  return url.toString();
}

function selectBucket(env: Env, bucketName: string): R2Bucket | null {
  if (bucketName === "media") {
    return env.MEDIA_BUCKET;
  }
  if (bucketName === "thumbs") {
    return env.THUMBS_BUCKET;
  }
  return null;
}

async function sha256Hex(input: string): Promise<string> {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function json(payload: JsonValue, status = 200): Response {
  const headers = new Headers({
    "content-type": "application/json; charset=utf-8",
  });
  applyCorsHeaders(headers);
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers,
  });
}

function corsResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  applyCorsHeaders(headers);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function applyCorsHeaders(headers: Headers): void {
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET,POST,PUT,PATCH,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,authorization");
}
