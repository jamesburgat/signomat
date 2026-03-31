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

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

type RouteContext = {
  env: Env;
  request: Request;
  url: URL;
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const ctx: RouteContext = { env, request, url };

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

    if (request.method === "GET" && url.pathname === "/public/detections") {
      return handlePublicDetections(ctx);
    }

    if (request.method === "GET" && url.pathname.startsWith("/public/detections/")) {
      const eventId = decodeURIComponent(url.pathname.split("/").pop() ?? "");
      return handlePublicDetectionDetail(ctx, eventId);
    }

    if (request.method === "GET" && url.pathname.startsWith("/public/assets/")) {
      return handlePublicAsset(ctx);
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};

async function handleIngestBatch(ctx: RouteContext): Promise<Response> {
  const auth = ctx.request.headers.get("authorization");
  const expected = `Bearer ${ctx.env.SIGNOMAT_INGEST_TOKEN}`;
  if (auth !== expected) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }

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

async function handlePublicDetections(ctx: RouteContext): Promise<Response> {
  const limit = clampInt(ctx.url.searchParams.get("limit"), 1, 200, 50);
  const category = ctx.url.searchParams.get("category");
  const tripId = ctx.url.searchParams.get("tripId");

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
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";

  const result = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT
       event_id,
       trip_id,
       timestamp_utc,
       category_id,
       category_label,
       specific_label,
       detector_confidence,
       classifier_confidence,
       gps_lat,
       gps_lon,
       annotated_thumb_bucket,
       annotated_thumb_key,
       clean_thumb_bucket,
       clean_thumb_key,
       sign_crop_thumb_bucket,
       sign_crop_thumb_key
     FROM detections
     ${where}
     ORDER BY timestamp_utc DESC
     LIMIT ?`
  )
    .bind(...bindings, limit)
    .all<Record<string, unknown>>();

  return json({
    ok: true,
    detections: (result.results ?? []).map((row) => ({
      eventId: row.event_id,
      tripId: row.trip_id,
      timestampUtc: row.timestamp_utc,
      categoryId: row.category_id,
      categoryLabel: row.category_label,
      specificLabel: row.specific_label,
      detectorConfidence: row.detector_confidence,
      classifierConfidence: row.classifier_confidence,
      gpsLat: row.gps_lat,
      gpsLon: row.gps_lon,
      annotatedThumbnailUrl: publicAssetUrl(ctx.env, row.annotated_thumb_bucket, row.annotated_thumb_key),
      cleanThumbnailUrl: publicAssetUrl(ctx.env, row.clean_thumb_bucket, row.clean_thumb_key),
      signCropThumbnailUrl: publicAssetUrl(ctx.env, row.sign_crop_thumb_bucket, row.sign_crop_thumb_key),
    })),
  });
}

async function handlePublicDetectionDetail(ctx: RouteContext, eventId: string): Promise<Response> {
  const row = await ctx.env.ARCHIVE_DB.prepare(
    `SELECT * FROM detections WHERE event_id = ?1 LIMIT 1`
  )
    .bind(eventId)
    .first<Record<string, unknown>>();

  if (!row) {
    return json({ ok: false, error: "not_found" }, 404);
  }

  return json({
    ok: true,
    detection: {
      eventId: row.event_id,
      tripId: row.trip_id,
      timestampUtc: row.timestamp_utc,
      categoryId: row.category_id,
      categoryLabel: row.category_label,
      specificLabel: row.specific_label,
      groupingMode: row.grouping_mode,
      rawDetectorLabel: row.raw_detector_label,
      rawClassifierLabel: row.raw_classifier_label,
      detectorConfidence: row.detector_confidence,
      classifierConfidence: row.classifier_confidence,
      gpsLat: row.gps_lat,
      gpsLon: row.gps_lon,
      annotatedFrameUrl: publicAssetUrl(ctx.env, row.annotated_frame_bucket, row.annotated_frame_key),
      cleanFrameUrl: publicAssetUrl(ctx.env, row.clean_frame_bucket, row.clean_frame_key),
      signCropUrl: publicAssetUrl(ctx.env, row.sign_crop_bucket, row.sign_crop_key),
    },
  });
}

async function handlePublicAsset(ctx: RouteContext): Promise<Response> {
  const prefix = "/public/assets/";
  const raw = ctx.url.pathname.slice(prefix.length);
  const [bucketName, ...keyParts] = raw.split("/");
  const key = keyParts.join("/");
  if (!bucketName || !key) {
    return json({ ok: false, error: "invalid_asset_path" }, 400);
  }

  const bucket = selectBucket(ctx.env, bucketName);
  if (!bucket) {
    return json({ ok: false, error: "unknown_bucket" }, 404);
  }

  const object = await bucket.get(key);
  if (!object) {
    return json({ ok: false, error: "not_found" }, 404);
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=3600");
  return new Response(object.body, { headers });
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
      segment.media?.bucket ?? null,
      segment.media?.key ?? null,
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
    throw new Error("deviceId and uploadedAtUtc are required");
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

function clampInt(raw: string | null, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function publicAssetUrl(env: Env, bucket: unknown, key: unknown): string | null {
  if (!bucket || !key || !env.PUBLIC_BASE_URL) {
    return null;
  }
  const url = new URL(env.PUBLIC_BASE_URL);
  url.pathname = `/public/assets/${String(bucket)}/${String(key)}`;
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
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
    },
  });
}
