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

    func reload(apiBaseURLString: String) async {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            async let queue: ArchiveReviewQueueResponse = fetch("/admin/review/queue?limit=50", baseURL: baseURL)
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
        let request = ArchiveReviewUpdateRequest(
            reviewState: reviewState,
            notes: detection.notes,
            categoryLabel: detection.categoryLabel,
            specificLabel: detection.specificLabel
        )
        await updateReview(apiBaseURLString: apiBaseURLString, eventID: detection.eventID, request: request)
    }

    func updateReview(
        apiBaseURLString: String,
        eventID: String,
        request: ArchiveReviewUpdateRequest
    ) async {
        guard let baseURL = normalizedBaseURL(from: apiBaseURLString) else {
            errorMessage = "Enter a valid archive API URL."
            return
        }

        do {
            let _: ArchiveDetectionDetailResponse = try await send(
                path: "/admin/detections/\(eventID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? eventID)/review",
                method: "PATCH",
                payload: request,
                baseURL: baseURL
            )
            statusMessage = "Saved review for \(eventID)."
            errorMessage = nil
            await reload(apiBaseURLString: apiBaseURLString)
        } catch {
            errorMessage = error.localizedDescription
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

    var bestThumbnailURL: URL? {
        let raw = cleanThumbnailUrl ?? annotatedThumbnailUrl ?? signCropThumbnailUrl ?? cleanFrameUrl ?? annotatedFrameUrl ?? signCropUrl
        guard let raw, !raw.isEmpty else { return nil }
        return URL(string: raw)
    }
}

enum ArchiveReviewState: String, Codable, CaseIterable, Identifiable {
    case unreviewed
    case reviewed
    case falsePositive = "false_positive"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .unreviewed:
            return "Unreviewed"
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
