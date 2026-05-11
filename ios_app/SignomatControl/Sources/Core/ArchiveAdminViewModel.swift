import Foundation

@MainActor
final class ArchiveAdminViewModel: ObservableObject {
    @Published var reviewQueue: [ArchiveDetection] = []
    @Published var trips: [ArchiveTripSummary] = []
    @Published var reviewCounts: [ArchiveReviewCount] = []
    @Published var trainingJobs: [ArchiveTrainingJob] = []
    @Published var modelMetrics = ArchiveModelMetrics.empty
    @Published var isLoading = false
    @Published var statusMessage: String?
    @Published var errorMessage: String?

    private static let reviewQueueLimit = 50

    func reload(apiBaseURLString: String) async {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            async let queue: ArchiveReviewQueueResponse = fetch(reviewQueuePath(), baseURL: baseURL)
            async let summary: ArchiveTrainingSummaryResponse = fetch("/admin/training/summary", baseURL: baseURL)
            async let jobs: ArchiveTrainingJobsResponse = fetch("/admin/training/jobs", baseURL: baseURL)
            async let tripPayload: ArchiveTripsResponse = fetch("/public/trips?limit=100", baseURL: baseURL)

            let (queueResponse, summaryResponse, jobsResponse, tripsResponse) = try await (queue, summary, jobs, tripPayload)
            reviewQueue = queueResponse.detections
            reviewCounts = summaryResponse.reviewCounts
            modelMetrics = summaryResponse.modelMetrics
            trainingJobs = jobsResponse.jobs
            trips = tripsResponse.trips
            statusMessage = "Loaded archive review and training data."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func quickUpdateReview(
        apiBaseURLString: String,
        detection: ArchiveDetection,
        reviewState: ArchiveReviewState
    ) async {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return
        }

        let request = ArchiveReviewUpdateRequest(
            reviewState: reviewState,
            notes: detection.notes,
            categoryLabel: detection.categoryLabel,
            specificLabel: detection.specificLabel
        )
        let originalIndex = reviewQueue.firstIndex { $0.eventID == detection.eventID }
        removeDetectionFromQueue(eventID: detection.eventID)

        do {
            let updatedDetection = try await saveReview(baseURL: baseURL, eventID: detection.eventID, request: request)
            applyReviewUpdate(updatedDetection)
            errorMessage = nil
            statusMessage = "Saved review for \(detection.eventID)."
            try await refreshSummary(baseURL: baseURL)
        } catch {
            restoreDetectionToQueue(detection, at: originalIndex)
            errorMessage = error.localizedDescription
        }
    }

    func updateReview(
        apiBaseURLString: String,
        eventID: String,
        request: ArchiveReviewUpdateRequest
    ) async -> Bool {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return false
        }

        do {
            let updatedDetection = try await saveReview(baseURL: baseURL, eventID: eventID, request: request)
            applyReviewUpdate(updatedDetection)
            statusMessage = "Saved review for \(eventID)."
            errorMessage = nil
            try await refreshSummary(baseURL: baseURL)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func createTrainingJob(
        apiBaseURLString: String,
        request: ArchiveTrainingJobCreateRequest
    ) async {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return
        }

        do {
            let _: ArchiveTrainingJobCreateResponse = try await send(
                path: "/admin/training/jobs",
                method: "POST",
                payload: request,
                baseURL: baseURL
            )
            statusMessage = "Created a new training draft."
            errorMessage = nil
            await reload(apiBaseURLString: apiBaseURLString)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func normalizedBaseURL(from raw: String) -> URL? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let candidate = trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") ? trimmed : "https://\(trimmed)"
        return URL(string: candidate)
    }

    private func reviewQueuePath() -> String {
        "/admin/review/queue?limit=\(Self.reviewQueueLimit)&reviewState=\(ArchiveReviewState.unreviewed.rawValue)"
    }

    private func fetch<Response: Decodable>(_ path: String, baseURL: URL) async throws -> Response {
        var request = URLRequest(url: resolvedURL(path: path, baseURL: baseURL))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        return try decode(Response.self, data: data, response: response)
    }

    private func send<RequestBody: Encodable, Response: Decodable>(
        path: String,
        method: String,
        payload: RequestBody,
        baseURL: URL
    ) async throws -> Response {
        var request = URLRequest(url: resolvedURL(path: path, baseURL: baseURL))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        return try decode(Response.self, data: data, response: response)
    }

    private func saveReview(
        baseURL: URL,
        eventID: String,
        request: ArchiveReviewUpdateRequest
    ) async throws -> ArchiveDetection {
        let response: ArchiveDetectionDetailResponse = try await send(
            path: "/admin/detections/\(eventID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? eventID)/review",
            method: "PATCH",
            payload: request,
            baseURL: baseURL
        )
        return response.detection
    }

    private func refreshSummary(baseURL: URL) async throws {
        let summary: ArchiveTrainingSummaryResponse = try await fetch("/admin/training/summary", baseURL: baseURL)
        reviewCounts = summary.reviewCounts
        modelMetrics = summary.modelMetrics
    }

    private func applyReviewUpdate(_ detection: ArchiveDetection) {
        if detection.reviewState == .unreviewed {
            if let index = reviewQueue.firstIndex(where: { $0.eventID == detection.eventID }) {
                reviewQueue[index] = detection
            } else {
                reviewQueue.insert(detection, at: 0)
            }
        } else {
            removeDetectionFromQueue(eventID: detection.eventID)
        }
    }

    private func removeDetectionFromQueue(eventID: String) {
        reviewQueue.removeAll { $0.eventID == eventID }
    }

    private func restoreDetectionToQueue(_ detection: ArchiveDetection, at index: Int?) {
        guard reviewQueue.contains(where: { $0.eventID == detection.eventID }) == false else { return }
        let insertionIndex = min(index ?? reviewQueue.count, reviewQueue.count)
        reviewQueue.insert(detection, at: insertionIndex)
    }

    private func resolvedURL(path: String, baseURL: URL) -> URL {
        let normalizedBase = baseURL.absoluteString.hasSuffix("/") ? String(baseURL.absoluteString.dropLast()) : baseURL.absoluteString
        return URL(string: normalizedBase + path) ?? baseURL
    }

    private func decode<Response: Decodable>(_ type: Response.Type, data: Data, response: URLResponse) throws -> Response {
        let decoder = JSONDecoder()
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            let apiError = try? decoder.decode(ArchiveAPIErrorResponse.self, from: data)
            throw ArchiveAdminError.server(apiError?.error ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode))
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw ArchiveAdminError.decoding(error.localizedDescription)
        }
    }
}

enum ArchiveAdminError: LocalizedError {
    case server(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .server(let message):
            return message
        case .decoding(let message):
            return "Failed to decode archive response: \(message)"
        }
    }
}

struct ArchiveAPIErrorResponse: Decodable {
    let error: String
}

struct ArchiveReviewQueueResponse: Decodable {
    let detections: [ArchiveDetection]
}

struct ArchiveTrainingSummaryResponse: Decodable {
    let reviewCounts: [ArchiveReviewCount]
    let modelMetrics: ArchiveModelMetrics
}

struct ArchiveTrainingJobsResponse: Decodable {
    let jobs: [ArchiveTrainingJob]
}

struct ArchiveTripsResponse: Decodable {
    let trips: [ArchiveTripSummary]
}

struct ArchiveTrainingJobCreateResponse: Decodable {
    let job: ArchiveTrainingJob
}

struct ArchiveModelMetrics: Decodable {
    let reviewedSampleSize: Int
    let confirmedSignCount: Int
    let falsePositiveCount: Int
    let reviewedPrecisionEstimate: Double?
    let avgConfirmedDetectorConfidence: Double?
    let avgFalsePositiveDetectorConfidence: Double?

    static let empty = ArchiveModelMetrics(
        reviewedSampleSize: 0,
        confirmedSignCount: 0,
        falsePositiveCount: 0,
        reviewedPrecisionEstimate: nil,
        avgConfirmedDetectorConfidence: nil,
        avgFalsePositiveDetectorConfidence: nil
    )
}

struct ArchiveDetectionDetailResponse: Decodable {
    let detection: ArchiveDetection
}

struct ArchiveReviewCount: Decodable, Identifiable {
    let reviewState: ArchiveReviewState
    let count: Int

    var id: String { reviewState.rawValue }
}

struct ArchiveTripSummary: Decodable, Identifiable {
    let tripId: String
    let startedAtUtc: String
    let endedAtUtc: String?
    let status: String
    let recordingEnabled: Bool
    let inferenceEnabled: Bool
    let notes: String?
    let detectionCount: Int

    var id: String { tripId }
}

struct ArchiveTrainingJob: Decodable, Identifiable {
    let jobId: String
    let name: String
    let modelType: ArchiveTrainingModelType
    let status: String
    let tripId: String?
    let reviewState: ArchiveReviewState
    let includeFalsePositives: Bool
    let selectedCount: Int
    let notes: String?
    let createdAtUtc: String?
    let updatedAtUtc: String?
    let exportUrl: String?
    let suggestedCommand: String?

    var id: String { jobId }
}

struct ArchiveDetection: Codable, Identifiable, Equatable {
    let eventId: String
    let tripId: String
    let timestampUtc: String
    let categoryId: String?
    var categoryLabel: String
    var specificLabel: String?
    let groupingMode: String?
    let rawDetectorLabel: String?
    let rawClassifierLabel: String?
    let detectorConfidence: Double?
    let classifierConfidence: Double?
    let gpsLat: Double?
    let gpsLon: Double?
    let gpsSpeed: Double?
    let heading: Double?
    let bboxLeft: Double?
    let bboxTop: Double?
    let bboxRight: Double?
    let bboxBottom: Double?
    let annotatedFrameUrl: String?
    let cleanFrameUrl: String?
    let signCropUrl: String?
    let annotatedThumbnailUrl: String?
    let cleanThumbnailUrl: String?
    let signCropThumbnailUrl: String?
    var reviewState: ArchiveReviewState
    var notes: String?

    var id: String { eventId }
    var eventID: String { eventId }

    var primaryReviewImageURL: URL? {
        url(from: signCropThumbnailUrl ?? signCropUrl ?? cleanThumbnailUrl ?? cleanFrameUrl ?? annotatedThumbnailUrl ?? annotatedFrameUrl)
    }

    var secondaryContextImageURL: URL? {
        guard cropImageURL != nil else { return nil }
        return url(from: cleanThumbnailUrl ?? cleanFrameUrl)
    }

    private var cropImageURL: URL? {
        url(from: signCropThumbnailUrl ?? signCropUrl)
    }

    private func url(from raw: String?) -> URL? {
        guard let raw, !raw.isEmpty else { return nil }
        return URL(string: raw)
    }
}

enum ArchiveReviewState: String, Codable, Identifiable {
    case unreviewed
    case classificationUnknown = "classification_unknown"
    case machineClassified = "machine_classified"
    case reviewed
    case falsePositive = "false_positive"

    static let writableCases: [ArchiveReviewState] = [
        .unreviewed,
        .reviewed,
        .falsePositive
    ]

    var id: String { rawValue }
    var isWritable: Bool { Self.writableCases.contains(self) }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawValue = try container.decode(String.self)
        self = ArchiveReviewState(rawValue: rawValue) ?? .classificationUnknown
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }

    var title: String {
        switch self {
        case .unreviewed:
            return "Unreviewed"
        case .classificationUnknown:
            return "Classification Unknown"
        case .machineClassified:
            return "Machine Classified"
        case .reviewed:
            return "Confirmed Sign"
        case .falsePositive:
            return "Not a Sign"
        }
    }
}

enum ArchiveTrainingModelType: String, Codable, CaseIterable, Identifiable {
    case detector
    case classifier

    var id: String { rawValue }
}

struct ArchiveReviewUpdateRequest: Encodable {
    let reviewState: ArchiveReviewState
    let notes: String?
    let categoryLabel: String?
    let specificLabel: String?
}

struct ArchiveTrainingJobCreateRequest: Encodable {
    let name: String?
    let modelType: ArchiveTrainingModelType
    let tripId: String?
    let reviewState: ArchiveReviewState
    let includeFalsePositives: Bool
    let notes: String?
}
