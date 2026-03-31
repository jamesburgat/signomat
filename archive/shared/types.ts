export type AssetPointer = {
  bucket: "media" | "thumbs";
  key: string;
  contentType?: string | null;
  byteSize?: number | null;
};

export type DetectionRecord = {
  eventId: string;
  tripId: string;
  timestampUtc: string;
  categoryId: string;
  categoryLabel: string;
  specificLabel: string | null;
  groupingMode: string;
  rawDetectorLabel?: string | null;
  rawClassifierLabel?: string | null;
  detectorConfidence?: number | null;
  classifierConfidence?: number | null;
  gpsLat: number | null;
  gpsLon: number | null;
  gpsSpeed?: number | null;
  heading?: number | null;
  bboxLeft?: number | null;
  bboxTop?: number | null;
  bboxRight?: number | null;
  bboxBottom?: number | null;
  annotatedFrame?: AssetPointer | null;
  cleanFrame?: AssetPointer | null;
  signCrop?: AssetPointer | null;
  annotatedThumbnail?: AssetPointer | null;
  cleanThumbnail?: AssetPointer | null;
  signCropThumbnail?: AssetPointer | null;
  videoSegmentId: string | null;
  videoTimestampOffsetMs?: number | null;
  dedupeGroupId?: string | null;
  suppressedNearbyCount?: number | null;
  reviewState?: "unreviewed" | "reviewed" | "false_positive";
  notes?: string | null;
};

export type TripRecord = {
  tripId: string;
  startedAtUtc: string;
  endedAtUtc: string | null;
  status: string;
  recordingEnabled: boolean;
  inferenceEnabled: boolean;
  notes?: string | null;
};

export type GPSPointRecord = {
  gpsPointId: string;
  tripId: string;
  timestampUtc: string;
  lat: number | null;
  lon: number | null;
  speed?: number | null;
  heading?: number | null;
  altitude?: number | null;
  fixQuality?: string | null;
  source?: string | null;
};

export type VideoSegmentRecord = {
  videoSegmentId: string;
  tripId: string;
  startTimestampUtc: string;
  endTimestampUtc: string | null;
  media?: AssetPointer | null;
  durationSec?: number | null;
  fileSize?: number | null;
};

export type IngestBatchRequest = {
  deviceId: string;
  uploadedAtUtc: string;
  trips?: TripRecord[];
  detections?: DetectionRecord[];
  gpsPoints?: GPSPointRecord[];
  videoSegments?: VideoSegmentRecord[];
};

export type IngestBatchResponse = {
  ok: boolean;
  receiptId: string;
  counts: {
    trips: number;
    detections: number;
    gpsPoints: number;
    videoSegments: number;
  };
};
