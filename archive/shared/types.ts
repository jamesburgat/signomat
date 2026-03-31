export type DetectionRecord = {
  eventId: string;
  tripId: string;
  timestampUtc: string;
  categoryId: string;
  categoryLabel: string;
  specificLabel: string | null;
  annotatedFramePath: string | null;
  cleanFramePath: string | null;
  signCropPath: string | null;
  gpsLat: number | null;
  gpsLon: number | null;
  videoSegmentId: string | null;
};

